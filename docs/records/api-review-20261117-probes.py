"""Offline review probes; run with .conda/bin/python from the repository root.

These assertions document current defects, not desired regression-test behavior.
All HTTP traffic uses MockTransport; temporary state is removed automatically.
"""

import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import httpx

from gzctf_mcp.client import Client, GZCTFError
from gzctf_mcp.config import Settings
from gzctf_mcp.models import ChallengeManifest
from gzctf_mcp.server import create_server
from gzctf_mcp.workflow import deploy


def settings(root, **extra):
    return Settings(
        base_url="https://review.invalid", workspace=root,
        admin_cookie="GZCTF_Token=old-admin", **extra,
    )


async def streaming_cookie(root):
    seen = []

    def handler(request):
        seen.append(request.headers.get("cookie"))
        return httpx.Response(
            200, content=b"archive",
            headers={"Content-Type": "application/zip",
                     "Set-Cookie": "GZCTF_Token=renewed; Path=/"},
        )

    api = Client(settings(root), transport=httpx.MockTransport(handler))
    try:
        for i in range(2):
            await api.export_binary("admin", "POST", "/api/edit/Games/1/Export", f"{i}.zip")
        assert api.sessions["admin"].cookies.get("GZCTF_Token") == "renewed"
        assert seen == ["GZCTF_Token=old-admin"] * 2
        return {"renewed_cookie_stored": True, "next_request_still_uses_old_cookie": True}
    finally:
        await api.close()


async def public_download_requires_player(root):
    calls = []
    api = Client(settings(root), transport=httpx.MockTransport(
        lambda r: calls.append(r) or httpx.Response(200, content=b"asset")))
    try:
        try:
            await api.download(f"/assets/{hashlib.sha256(b'asset').hexdigest()}/a", "a")
        except GZCTFError as error:
            assert "GZCTF_PLAYER_COOKIE" in str(error) and not calls
            return {"public_asset_blocked_locally_without_player_credentials": True}
        raise AssertionError("Expected missing player configuration")
    finally:
        await api.close()


async def attachment_timeout(root):
    digest = hashlib.sha256(b"asset").hexdigest()
    challenge = {"id": 9, "title": "review", "type": "StaticAttachment",
                 "isEnabled": False, "flags": [], "attachment": None}
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.startswith("/assets/"):
            raise httpx.ReadTimeout("mock readback timeout", request=request)
        if request.url.path.endswith("/Attachment"):
            challenge["attachment"] = {"type": "Local", "url": f"/assets/{digest}/a"}
            return httpx.Response(200)
        return httpx.Response(200, json=challenge)

    api = Client(settings(root), transport=httpx.MockTransport(handler))
    try:
        manifest = ChallengeManifest.model_validate({
            "challenge": {"title": "review"},
            "attachment": {"attachmentType": "Local", "fileHash": digest},
        })
        try:
            await deploy(api, 1, manifest, dry_run=False)
        except httpx.ReadTimeout:
            assert any(m == "POST" and p.endswith("/Attachment") for m, p in calls)
            return {"created_challenge_id": 9, "attachment_bound": True,
                    "escaped_exception": "httpx.ReadTimeout", "structured_recovery_result": False}
        raise AssertionError("Expected raw timeout")
    finally:
        await api.close()


async def concurrent_game_patches(root):
    state = {"title": "original", "start": 1793491200000, "end": 1796083200000,
             "hidden": True, "summary": "original summary"}
    reads = 0
    barrier = asyncio.Event()

    async def handler(request):
        nonlocal reads
        if request.method == "GET":
            snapshot = dict(state)
            reads += 1
            if reads <= 2:
                if reads == 2:
                    barrier.set()
                await barrier.wait()
            return httpx.Response(200, json=snapshot)
        state.update(json.loads(request.content))
        return httpx.Response(200)

    api = Client(settings(root), transport=httpx.MockTransport(handler))
    try:
        server = create_server(api.settings, api)
        await asyncio.gather(
            server.call_tool("admin_update_game", {"game_id": 1, "patch": {"title": "changed"}}),
            server.call_tool("admin_update_game", {"game_id": 1, "patch": {"hidden": False}}),
        )
        assert not (state["title"] == "changed" and state["hidden"] is False)
        return {"both_calls_succeeded": True, "final_title": state["title"],
                "final_hidden": state["hidden"], "one_patch_lost": True}
    finally:
        await api.close()


async def cleanup_after_uncertain_delete(root):
    directory = root / ".mcp-state"
    directory.mkdir(exist_ok=True)
    path = directory / "cleanup.json"
    path.write_text(json.dumps({"identity": {"origin": "https://review.invalid", "gameId": 1},
                               "items": {"one": {"challengeId": 9, "stage": "complete"},
                                         "two": {"challengeId": 10, "stage": "complete"}}}))
    existing = {9, 10}

    def handler(request):
        identifier = int(request.url.path.rsplit("/", 1)[1])
        if identifier not in existing:
            return httpx.Response(404, json={"title": "Challenge not found"})
        existing.remove(identifier)
        raise httpx.ReadTimeout("response lost after delete", request=request)

    api = Client(settings(root), transport=httpx.MockTransport(handler))
    try:
        server = create_server(api.settings, api)
        errors = []
        for _ in range(2):
            try:
                await server.call_tool("admin_cleanup_batch", {"state_name": "cleanup", "dry_run": False})
            except Exception as error:
                errors.append(str(error))
        assert len(errors) == 2 and "HTTP 404" in errors[1]
        assert existing == {10}
        assert json.loads(path.read_text())["items"]["one"]["stage"] == "complete"
        return {"first_delete_committed": True, "retry_stops_on_404": True,
                "next_challenge_not_cleaned": True, "ledger_not_reconciled": True}
    finally:
        await api.close()


async def main():
    with tempfile.TemporaryDirectory(prefix="gzctf-api-review-") as directory:
        root = Path(directory)
        results = {}
        for probe in (streaming_cookie, public_download_requires_player, attachment_timeout,
                      concurrent_game_patches, cleanup_after_uncertain_delete):
            results[probe.__name__] = await probe(root)
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
