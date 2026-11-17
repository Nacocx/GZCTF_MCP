"""Managed, loopback-only wsrx CLI tunnels for GZCTF PlatformProxy instances."""

import asyncio
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from .client import Client, GZCTFError


class _HideProxyCapabilities(logging.Filter):
    def filter(self, record):
        return "/api/proxy/" not in record.getMessage().lower()


@dataclass
class Tunnel:
    id: str
    game_id: int
    challenge_id: int
    role: str
    instance: str
    port: int
    process: asyncio.subprocess.Process
    drain_task: asyncio.Task

    def public(self):
        return {
            "proxyId": self.id,
            "gameId": self.game_id,
            "challengeId": self.challenge_id,
            "role": self.role,
            "localAddress": f"127.0.0.1:{self.port}",
            "localHost": "127.0.0.1",
            "localPort": self.port,
            "state": "listening" if self.process.returncode is None else "exited",
            "exitCode": self.process.returncode,
        }


class ProxyManager:
    def __init__(self, api: Client):
        self.api = api
        self.settings = api.settings
        self.tunnels: dict[str, Tunnel] = {}
        self.lock = asyncio.Lock()
        self.closed = False
        logger = logging.getLogger("httpx")
        if not any(isinstance(item, _HideProxyCapabilities) for item in logger.filters):
            logger.addFilter(_HideProxyCapabilities())

    def binary(self):
        executable = shutil.which(self.settings.wsrx_binary)
        if executable is None:
            raise GZCTFError(
                "wsrx CLI was not found. Run python scripts/install_wsrx.py and set "
                "GZCTF_WSRX_BINARY to the installed executable, or install wsrx on PATH."
            )
        return str(Path(executable).resolve())

    @staticmethod
    def child_env():
        # In particular, never pass GZCTF cookies or other credential variables to wsrx.
        allowed = {
            "PATH",
            "SystemRoot",
            "SYSTEMROOT",
            "WINDIR",
            "HOME",
            "USERPROFILE",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "LANG",
            "LC_ALL",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.update(RUST_LOG="wsrx=info", NO_COLOR="1", RUST_BACKTRACE="0")
        return env

    @staticmethod
    async def stop_process(process):
        if process.returncode is not None:
            return
        if process.stdin is not None:
            # Closing the supervisor lifeline also works on Windows, whose
            # terminate() would otherwise kill the supervisor before its child.
            process.stdin.close()
        else:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    async def version(self, executable):
        process = await asyncio.create_subprocess_exec(
            executable,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=self.child_env(),
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), 5)
            text = stdout.decode("utf-8", errors="replace").strip()
            if process.returncode != 0 or not re.fullmatch(
                r"wsrx \d+\.\d+\.\d+(?:[-+][\w.-]+)?", text
            ):
                raise GZCTFError(
                    "Configured binary is not a supported wsrx CLI; use the pinned 0.6.2 installer"
                )
            return text
        except TimeoutError:
            raise GZCTFError("wsrx --version timed out") from None
        finally:
            await self.stop_process(process)

    @staticmethod
    async def drain(reader):
        # Drop logs; they can contain instance-capability URLs and must not reach MCP stdout.
        while await reader.read(4096):
            pass

    @staticmethod
    async def startup_port(process, requested):
        for _ in range(100):
            line = await process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line).get("fields", {}).get("message", "")
            except (ValueError, AttributeError):
                continue
            # 0.6.2 connect prints its actual bound listener, including port=0 assignment.
            if "Hi, I am not RX, RX is here ->" in message:
                match = re.search(r"127\.0\.0\.1:(\d{1,5})", message)
                if match:
                    port = int(match[1])
                    if 0 < port < 65536 and (requested == 0 or requested == port):
                        return port
        raise GZCTFError("wsrx did not start its loopback listener; check the port and CLI version")

    async def close_instance(self, instance):
        for tunnel in list(self.tunnels.values()):
            if tunnel.instance == str(instance):
                await self.close_one(tunnel.id)

    async def platform_config(self, role):
        return await self.api.request(role, "GET", "/api/config")

    async def open(self, game_id: int, challenge_id: int, role: str, local_port: int):
        # Validate even when called outside MCP's argument parser.
        if role not in ("admin", "player") or not 0 <= local_port <= 65535:
            raise GZCTFError("Invalid role or local port")
        async with self.lock:
            if self.closed:
                raise GZCTFError("Proxy manager is shutting down")
            config = await self.platform_config(role)
            if role == "admin":
                detail = await self.api.request(
                    role, "GET", f"/api/edit/Games/{game_id}/Challenges/{challenge_id}"
                )
                container = detail.get("testContainer") or {}
                entry = container.get("entry")
                expires = container.get("expectStopAt")
            else:
                detail = await self.api.request(
                    role, "GET", f"/api/game/{game_id}/Challenges/{challenge_id}"
                )
                context = detail.get("context") or {}
                entry = context.get("instanceEntry")
                expires = context.get("closeTime")
            if not entry:
                raise GZCTFError(
                    "No running container entry. Start the corresponding player or admin test container first."
                )
            if config.get("portMapping") == "Default":
                return {
                    "mode": "direct",
                    "entry": entry,
                    "expiresAt": expires,
                    "proxyId": None,
                    "note": "This platform uses a direct address; no wsrx process started.",
                }
            if config.get("portMapping") != "PlatformProxy":
                raise GZCTFError("Unknown platform port mapping; no tunnel was started")
            try:
                instance = str(UUID(entry))
            except (ValueError, TypeError, AttributeError):
                raise GZCTFError("PlatformProxy did not return a valid container UUID") from None
            prefix = "/api/proxy/noinst/" if role == "admin" else "/api/proxy/"
            path = prefix + instance
            # GZCTF returns 204 for a valid instance without a WebSocket upgrade.
            await self.api.request(role, "GET", path)
            for identifier, tunnel in list(self.tunnels.items()):
                if tunnel.process.returncode is not None:
                    await self._close(identifier)
                elif (tunnel.game_id, tunnel.challenge_id, tunnel.role) == (
                    game_id,
                    challenge_id,
                    role,
                ):
                    if tunnel.instance == instance:
                        if local_port not in (0, tunnel.port):
                            raise GZCTFError(
                                "This instance already has a tunnel on another local port; close it first"
                            )
                        return {
                            **tunnel.public(),
                            "mode": "PlatformProxy",
                            "reused": True,
                            "expiresAt": expires,
                        }
                    await self._close(identifier)
            if len(self.tunnels) >= self.settings.max_tunnels:
                raise GZCTFError("GZCTF_MAX_TUNNELS reached; close an existing proxy first")
            executable = self.binary()
            version = await self.version(executable)
            scheme = "wss" if self.settings.base_url.startswith("https://") else "ws"
            remote = scheme + self.settings.base_url[self.settings.base_url.index(":") :] + path
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "gzctf_mcp._wsrx_runner",
                executable,
                "connect",
                remote,
                "--host",
                "127.0.0.1",
                "--port",
                str(local_port),
                "--log-json",
                "true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self.child_env(),
                stdin=asyncio.subprocess.PIPE,
            )
            try:
                port = await asyncio.wait_for(self.startup_port(process, local_port), 8)
                if process.returncode is not None:
                    raise GZCTFError("wsrx exited before the listener became ready")
                identifier = str(uuid4())
                tunnel = Tunnel(
                    identifier,
                    game_id,
                    challenge_id,
                    role,
                    instance,
                    port,
                    process,
                    asyncio.create_task(self.drain(process.stdout)),
                )
                self.tunnels[identifier] = tunnel
                return {
                    **tunnel.public(),
                    "mode": "PlatformProxy",
                    "reused": False,
                    "expiresAt": expires,
                    "wsrxVersion": version,
                    "note": "Listener ready. The WebSocket connects when a local TCP client connects; "
                    "test the challenge protocol to confirm end-to-end reachability.",
                }
            except BaseException as error:
                await self.stop_process(process)
                if isinstance(error, TimeoutError):
                    raise GZCTFError("wsrx listener startup timed out") from None
                raise

    def list(self):
        return [tunnel.public() for tunnel in self.tunnels.values()]

    async def _close(self, identifier):
        tunnel = self.tunnels.pop(identifier)
        await self.stop_process(tunnel.process)
        await asyncio.gather(tunnel.drain_task, return_exceptions=True)
        return {"proxyId": identifier, "closed": True, "localPort": tunnel.port}

    async def close_one(self, identifier):
        async with self.lock:
            if identifier not in self.tunnels:
                raise GZCTFError("Proxy ID is not managed by this MCP process")
            return await self._close(identifier)

    async def close_for(self, game_id, challenge_id, role=None):
        async with self.lock:
            for identifier, tunnel in list(self.tunnels.items()):
                if (tunnel.game_id, tunnel.challenge_id) == (game_id, challenge_id) and (
                    role is None or tunnel.role == role
                ):
                    await self._close(identifier)

    async def close(self):
        async with self.lock:
            self.closed = True
            for identifier in list(self.tunnels):
                await self._close(identifier)
