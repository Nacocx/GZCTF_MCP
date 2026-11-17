import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import re
from collections import Counter, defaultdict
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from .config import Settings


class GZCTFError(RuntimeError):
    """Sanitized operational error safe for MCP output."""

    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


def normalize_cookie(value):
    if "\r" in value or "\n" in value:
        raise ValueError("Cookie must not contain line breaks")
    value = value.strip()
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    if value and ("=" not in value or re.fullmatch(r"[A-Za-z0-9+/_-]+={1,2}", value)):
        return "GZCTF_Token=" + value
    return value


class Client:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.sessions = {
            role: httpx.AsyncClient(
                base_url=settings.base_url,
                timeout=settings.timeout,
                follow_redirects=False,
                headers={"Cookie": normalize_cookie(cookie)} if cookie else {},
                transport=transport,
            )
            for role, cookie in [
                ("admin", settings.admin_cookie),
                ("player", settings.player_cookie),
            ]
        }
        self.public = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout,
            follow_redirects=False,
            transport=transport,
        )
        self.authenticated = set()
        self.auth_locks = {role: asyncio.Lock() for role in self.sessions}
        self.game_locks = defaultdict(asyncio.Lock)
        self.attachment_locks = defaultdict(asyncio.Lock)
        self.upload_references = Counter()

    def take_upload_reference(self, digest):
        """Consume once, before binding; an uncertain write never releases its reference."""
        self.take_upload_references([digest])

    def check_upload_references(self, digests):
        required = Counter(digests)
        if any(self.upload_references[h] < count for h, count in required.items()):
            raise GZCTFError(
                "No unused upload reference for fileHash. Upload this file once per new "
                "attachment in this MCP session, or deploy using attachmentPath. "
                "A stored hash alone cannot safely be reused across attachments."
            )
        return required

    def take_upload_references(self, digests):
        self.upload_references.subtract(self.check_upload_references(digests))

    def refresh_cookie(self, role, response):
        if role != "public" and response.cookies.get("GZCTF_Token"):
            self.sessions[role].headers.pop("Cookie", None)
            self.authenticated.add(role)

    @asynccontextmanager
    async def stream(self, role, method, path, **kwargs):
        if role != "public":
            await self.ensure_auth(role)
        session = self.public if role == "public" else self.session(role)
        try:
            async with session.stream(method, path, **kwargs) as response:
                self.refresh_cookie(role, response)
                self.check_response(response)
                yield response
        except httpx.RequestError:
            raise GZCTFError(
                "Stream interrupted. A write may already have completed; inspect remote "
                "state before retrying."
            ) from None

    async def close(self):
        for session in [*self.sessions.values(), self.public]:
            await session.aclose()

    def session(self, role):
        cookie = getattr(self.settings, f"{role}_cookie")
        if not cookie and role not in self.authenticated:
            raise GZCTFError(f"Configure GZCTF_{role.upper()}_COOKIE for this operation")
        return self.sessions[role]

    async def ensure_auth(self, role):
        if getattr(self.settings, f"{role}_cookie") or role in self.authenticated:
            return
        async with self.auth_locks[role]:
            if role not in self.authenticated:
                if not getattr(self.settings, f"{role}_username"):
                    self.session(role)  # reports missing configuration
                await self.login(role)

    async def encrypt(self, value):
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
            X25519PublicKey,
        )
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        config = await self.request("public", "GET", "/api/config")
        if not isinstance(config, dict):
            raise GZCTFError("Invalid platform configuration")
        public_key = config.get("apiPublicKey")
        if not public_key:
            return value
        try:
            ephemeral = X25519PrivateKey.generate()
            peer = X25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
            key = hashlib.sha256(ephemeral.exchange(peer)).digest()
            nonce = os.urandom(12)
            encrypted = AESGCM(key).encrypt(nonce, value.encode(), None)
            return base64.b64encode(
                ephemeral.public_key().public_bytes_raw() + nonce + encrypted
            ).decode()
        except (ValueError, TypeError):
            raise GZCTFError(
                "Invalid API encryption public key; refresh platform configuration"
            ) from None

    async def login(self, role, challenge=None):
        username = getattr(self.settings, f"{role}_username")
        password = getattr(self.settings, f"{role}_password")
        if not username or not password:
            raise GZCTFError("Configure environment username/password for this role")
        captcha = await self.request("public", "GET", "/api/captcha")
        if captcha.get("type", "None") != "None" and not challenge:
            raise GZCTFError(
                "Captcha required; use auth_requirements and provide a valid challenge response"
            )
        encrypted = await self.encrypt(password)
        session = self.sessions[role]
        try:
            response = await session.post(
                "/api/account/LogIn",
                json={"userName": username, "password": encrypted, "challenge": challenge},
            )
        except httpx.RequestError:
            raise GZCTFError("Login response uncertain; inspect session before retrying") from None
        self.check_response(response)
        if not session.cookies.get("GZCTF_Token"):
            raise GZCTFError("Login did not return a session Cookie")
        session.headers.pop("Cookie", None)
        self.authenticated.add(role)
        return {"role": role, "authenticated": True}

    async def logout(self, role):
        await self.request(role, "POST", "/api/account/LogOut")
        self.sessions[role].cookies.clear()
        self.sessions[role].headers.pop("Cookie", None)
        self.authenticated.discard(role)
        setattr(self.settings, f"{role}_cookie", "")
        return {"role": role, "authenticated": False}

    def local_file(self, path: str) -> Path:
        candidate = (self.settings.workspace / path).resolve(strict=True)
        if not candidate.is_relative_to(self.settings.workspace) or not candidate.is_file():
            raise GZCTFError("File must be a regular file inside GZCTF_WORKSPACE")
        if not 0 < candidate.stat().st_size <= self.settings.max_file_bytes:
            raise GZCTFError("File is empty or exceeds GZCTF_MAX_FILE_BYTES")
        return candidate

    def check_response(self, response, sensitive=()):
        code = response.status_code
        if code >= 300:
            hints = {
                400: "Invalid request or game/challenge state. Check the configuration.",
                401: "Session expired or missing; refresh the corresponding Cookie.",
                403: "Account lacks permission or game participation is not approved.",
                404: "Resource unavailable; verify IDs, participation, and game visibility.",
                429: "Rate limited; wait before explicitly retrying.",
            }
            retry = response.headers.get("retry-after", "")
            if retry and not re.fullmatch(r"[0-9]{1,8}", retry):
                retry = "see server rate limit policy"
            details = {
                "httpStatus": code,
                "nextStep": hints.get(code, "Upstream request failed."),
                "retryable": code == 429,
                "automaticRetry": False,
            }
            if code == 401:
                details["nextTool"] = "auth_login"
            elif code == 403:
                details["nextTool"] = "check_session"
            try:
                body = response.json()
            except (ValueError, httpx.ResponseNotRead):
                body = {}
            # Never echo arbitrary upstream text or reflected request secrets.
            if isinstance(body, dict):
                status = body.get("status")
                if isinstance(status, (int, str)) and re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,64}", str(status)
                ):
                    details["businessStatus"] = status
                title = body.get("title")
                if isinstance(title, str):
                    secrets = list(sensitive) + [
                        getattr(self.settings, f"{r}_{k}")
                        for r in self.sessions
                        for k in ("cookie", "password", "username")
                    ]
                    try:
                        request_body = json.loads(response.request.content)

                        def values(obj):
                            if isinstance(obj, str):
                                yield obj
                            elif isinstance(obj, dict):
                                for value in obj.values():
                                    yield from values(value)
                            elif isinstance(obj, list):
                                for value in obj:
                                    yield from values(value)

                        secrets.extend(values(request_body))
                    except (ValueError, RuntimeError, httpx.RequestNotRead):
                        pass
                    for secret in sorted(filter(None, secrets), key=len, reverse=True):
                        title = title.replace(secret, "[redacted]")
                    title = re.sub(r"(?i)(?:flag|ctf)\{[^}]*\}", "[redacted]", title)
                    title = re.sub(r"[\x00-\x1f\x7f]", " ", title)
                    details["title"] = title[:200]
            if code == 429 and retry:
                details["retryHint"] = f"Retry-After: {retry}"
            raise GZCTFError(
                f"HTTP {code}: " + json.dumps(details, ensure_ascii=False), http_status=code
            )

    async def request(self, role, method, path, _sensitive=(), **kwargs):
        try:
            if role != "public":
                await self.ensure_auth(role)
            session = self.public if role == "public" else self.session(role)
            response = await session.request(method, path, **kwargs)
        except httpx.RequestError:
            raise GZCTFError(
                "Network request failed. A write may already have completed; "
                "inspect remote state before retrying."
            ) from None
        self.refresh_cookie(role, response)
        self.check_response(response, _sensitive)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise GZCTFError(
                "Expected JSON from GZCTF; check origin, proxy, and server version"
            ) from None

    async def multipart(self, role, method, endpoint, path, max_bytes=None):
        file = self.local_file(path)
        if max_bytes and file.stat().st_size > max_bytes:
            raise GZCTFError("Upload exceeds endpoint file size limit")
        with file.open("rb") as stream:
            return await self.request(
                role,
                method,
                endpoint,
                files={
                    "file": (
                        file.name,
                        stream,
                        mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                    )
                },
            )

    async def upload(self, path: str, *, writeup_game: int | None = None):
        file = self.local_file(path)
        if writeup_game is not None and (
            file.suffix != ".pdf" or file.stat().st_size > 20 * 1024 * 1024
        ):
            raise GZCTFError("Writeup must be a .pdf file no larger than 20 MiB")
        role = "player" if writeup_game else "admin"
        endpoint = f"/api/game/{writeup_game}/Writeup" if writeup_game else "/api/assets"
        async with AsyncExitStack() as stack:
            stream = stack.enter_context(file.open("rb"))
            result = await self.request(
                role,
                "POST",
                endpoint,
                files={
                    "file" if writeup_game else "files": (
                        file.name,
                        stream,
                        "application/pdf" if writeup_game else "application/octet-stream",
                    )
                },
            )
            if writeup_game is None and isinstance(result, list):
                stream.seek(0)
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if (
                    len(result) == 1
                    and isinstance(result[0], dict)
                    and result[0].get("hash") == digest
                ):
                    self.upload_references[digest] += 1
            return result

    async def download(self, asset_path: str, filename: str, role="public"):
        decoded = unquote(asset_path)
        if (
            urlsplit(decoded).scheme
            or urlsplit(decoded).netloc
            or "\\" in decoded
            or not re.fullmatch(r"/assets/[0-9a-f]{64}/[^/?#]+", decoded)
            or decoded.split("/")[-1] in (".", "..")
        ):
            raise GZCTFError(
                "Use a same-site /assets/<sha256>/<name> path; external URLs are not fetched"
            )
        if not re.fullmatch(r"[\w. -]{1,180}", filename) or filename in (".", ".."):
            raise GZCTFError("filename must be a simple file name")
        folder = self.settings.workspace / "downloads"
        folder.mkdir(exist_ok=True)
        if not folder.resolve().is_relative_to(self.settings.workspace):
            raise GZCTFError("downloads must remain inside GZCTF_WORKSPACE")
        destination = folder / filename
        async with self.stream(role, "GET", asset_path) as response:
            size = 0
            digest = hashlib.sha256()
            # Exclusive creation also rejects existing symlinks and prevents overwrites.
            with destination.open("xb") as output:
                try:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.max_file_bytes:
                            raise GZCTFError("Download exceeds GZCTF_MAX_FILE_BYTES")
                        output.write(chunk)
                        digest.update(chunk)
                    if digest.hexdigest() != decoded.split("/")[2]:
                        raise GZCTFError("Downloaded asset SHA256 does not match its URL")
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
        return {"path": str(destination), "bytes": size, "sha256": digest.hexdigest()}

    async def export_binary(self, role, method, endpoint, filename):
        if not re.fullmatch(r"[\w. -]{1,180}", filename) or filename in (".", ".."):
            raise GZCTFError("Use a simple output filename")
        folder = self.settings.workspace / "downloads"
        folder.mkdir(exist_ok=True)
        if not folder.resolve().is_relative_to(self.settings.workspace):
            raise GZCTFError("downloads must remain inside workspace")
        destination = folder / filename
        async with self.stream(role, method, endpoint) as response:
            if any(t in response.headers.get("content-type", "") for t in ("json", "text/html")):
                raise GZCTFError("Expected binary export, received JSON/HTML")
            digest, size = hashlib.sha256(), 0
            with destination.open("xb") as output:
                try:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.max_file_bytes:
                            raise GZCTFError("Export exceeds file size limit")
                        digest.update(chunk)
                        output.write(chunk)
                    if size == 0:
                        raise GZCTFError("Empty binary export")
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
        return {"path": str(destination), "bytes": size, "sha256": digest.hexdigest()}
