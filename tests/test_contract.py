import hashlib
import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from gzctf_mcp.client import GZCTFError
from gzctf_mcp.models import ChallengeManifest, ChallengeUpdate
from gzctf_mcp.workflow import deploy


def unpack(result):
    # FastMCP may return content or (content, structured content).
    if isinstance(result, tuple):
        return result[1]
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


async def test_identity_submission_and_pending(harness):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/config":
            return httpx.Response(200, json={"apiPublicKey": None})
        if request.method == "POST":
            assert json.loads(request.content) == {"flag": "flag{candidate}"}
            return httpx.Response(200, json=42)
        if "/Status/" in request.url.path:
            return httpx.Response(200, json="FlagSubmitted")
        return httpx.Response(200, json=[])

    server, _ = harness(handler)
    args = {"game_id": 2, "challenge_id": 5}
    result = unpack(await server.call_tool("submit_flag", {**args, "flag": "flag{candidate}"}))
    assert result["submissionId"] == 42
    verdict = unpack(await server.call_tool("submission_status", {**args, "submission_id": 42}))
    assert verdict["pending"] and not verdict["accepted"]
    await server.call_tool("admin_list_challenges", {"game_id": 2})
    assert [r.url.path for r in calls] == [
        "/api/config",
        "/api/game/2/Challenges/5",
        "/api/game/2/Challenges/5/Status/42",
        "/api/edit/Games/2/Challenges",
    ]
    assert calls[1].headers["cookie"] == "player-session=secret-p"
    assert calls[3].headers["cookie"] == "admin-session=secret-a"


async def test_multipart_asset_and_pdf(harness, settings):
    requests = []
    server, _ = harness(lambda r: requests.append(r) or httpx.Response(200, json=[]))
    (settings.workspace / "challenge.zip").write_bytes(b"zip data")
    (settings.workspace / "writeup.pdf").write_bytes(b"%PDF-1.7 test")
    await server.call_tool("admin_upload_file", {"path": "challenge.zip"})
    await server.call_tool("submit_writeup", {"game_id": 2, "path": "writeup.pdf"})
    assert requests[0].url.path == "/api/assets"
    assert b'name="files"' in requests[0].content
    assert b"zip data" in requests[0].content
    assert requests[1].url.path == "/api/game/2/Writeup"
    assert b'name="file"' in requests[1].content
    assert b"Content-Type: application/pdf" in requests[1].content
    with pytest.raises(ToolError):
        await server.call_tool("submit_writeup", {"game_id": 2, "path": "challenge.zip"})
    assert len(requests) == 2


@pytest.mark.parametrize("code", [401, 403, 429, 302, 500])
async def test_sanitized_errors_no_write_retry(harness, code):
    requests = []
    server, _ = harness(
        lambda r: (
            requests.append(r)
            or httpx.Response(
                code,
                text="secret flag{must-not-leak}",
                headers={"Retry-After": "4", "Location": "https://evil.test"},
            )
        )
    )
    with pytest.raises(ToolError) as error:
        await server.call_tool("submit_flag", {"game_id": 1, "challenge_id": 2, "flag": "flag{x}"})
    assert f"HTTP {code}" in str(error.value)
    assert "must-not-leak" not in str(error.value)
    assert len(requests) == 1
    if code == 429:
        assert "Retry-After: 4" in str(error.value)


async def test_missing_cookie(harness, settings):
    settings.player_cookie = ""
    requests = []
    server, _ = harness(lambda r: requests.append(r) or httpx.Response(200, json=[]))
    with pytest.raises(ToolError, match="GZCTF_PLAYER_COOKIE"):
        await server.call_tool("list_teams", {})
    assert requests == []


async def test_paths_and_download(harness, settings, tmp_path):
    payload = b"challenge content"
    digest = hashlib.sha256(payload).hexdigest()
    requests = []
    server, client = harness(lambda r: requests.append(r) or httpx.Response(200, content=payload))
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.write_text("outside")
    (tmp_path / "escape").symlink_to(outside)
    try:
        for path in [str(outside), "../" + outside.name, "escape"]:
            with pytest.raises(GZCTFError):
                client.local_file(path)
        for url in [
            "https://evil.test/a",
            "//evil.test/a",
            "/api/account/Profile",
            f"/assets/{digest}/%2e%2e",
            f"/assets/{digest}/a%2fb",
        ]:
            with pytest.raises(ToolError):
                await server.call_tool("download_attachment", {"asset_path": url, "filename": "x"})
        result = unpack(
            await server.call_tool(
                "download_attachment",
                {"asset_path": f"/assets/{digest}/a.zip", "filename": "a.zip"},
            )
        )
        assert result["sha256"] == digest
        with pytest.raises(ToolError):
            await server.call_tool(
                "download_attachment",
                {"asset_path": f"/assets/{digest}/a.zip", "filename": "a.zip"},
            )
        assert (tmp_path / "downloads/a.zip").read_bytes() == payload
    finally:
        outside.unlink()


async def test_size_limit_cleans_download(harness, settings):
    settings.max_file_bytes = 4
    _, client = harness(lambda r: httpx.Response(200, content=b"12345"))
    with pytest.raises(GZCTFError, match="exceeds"):
        await client.download("/assets/" + "0" * 64 + "/x", "x")
    assert not (settings.workspace / "downloads/x").exists()


async def test_network_write_uncertainty(harness):
    def handler(request):
        raise httpx.ReadTimeout("secret", request=request)

    server, _ = harness(handler)
    with pytest.raises(ToolError, match="may already have completed"):
        await server.call_tool("submit_flag", {"game_id": 1, "challenge_id": 2, "flag": "flag{x}"})


def manifest(**kwargs):
    base = {
        "challenge": {"title": "Example", "category": "Web"},
        "configuration": {"content": "Solve this", "originalScore": 500},
        "flags": [{"flag": "flag{test}"}],
        "publish": True,
    }
    base.update(kwargs)
    return ChallengeManifest.model_validate(base)


async def test_deploy_order_and_resume(harness, settings):
    state = {
        "flags": [],
        "id": 9,
        "title": "Example",
        "type": "StaticAttachment",
        "isEnabled": False,
    }
    calls = []
    fail_flags = True
    digest = hashlib.sha256(b"zip").hexdigest()
    (settings.workspace / "challenge.zip").write_bytes(b"zip")

    def handler(request):
        nonlocal fail_flags
        calls.append((request.method, request.url.path, request.content))
        if request.url.path.startswith("/assets/"):
            return httpx.Response(200, content=b"zip")
        if request.url.path.endswith("/Attachment"):
            state["attachment"] = {"type": "Local", "url": f"/assets/{digest}/challenge.zip"}
        if request.url.path == "/api/assets":
            return httpx.Response(200, json=[{"hash": digest, "name": "challenge.zip"}])
        if request.url.path.endswith("/Flags"):
            # Simulate a write that succeeded remotely but whose response timed out.
            state["flags"] = [{"flag": "flag{test}", "attachment": None}]
            if fail_flags:
                fail_flags = False
                raise httpx.ReadTimeout("timeout", request=request)
        if request.method == "GET" or (
            request.method == "POST" and request.url.path.endswith("/Challenges")
        ):
            return httpx.Response(200, json=state)
        return httpx.Response(200)

    _, client = harness(handler)
    spec = manifest(attachmentPath="challenge.zip")
    preview = await deploy(client, 1, spec)
    assert preview["dryRun"] and calls == []
    result = await deploy(client, 1, spec, dry_run=False)
    assert not result["completed"] and result["stage"] == "flags" and result["challengeId"] == 9
    assert not any(b'"isEnabled":true' in body for _, _, body in calls)
    result = await deploy(client, 1, spec, dry_run=False, challenge_id=9)
    assert result["completed"] and result["stage"] == "complete"
    assert sum(method == "POST" and path.endswith("/Challenges") for method, path, _ in calls) == 1
    assert sum(path.endswith("/Flags") for _, path, _ in calls) == 1
    assert json.loads(calls[-1][2]) == {"isEnabled": True}


async def test_resume_matches_attachment_url(harness):
    digest = hashlib.sha256(b"zip").hexdigest()
    attachment = {"type": "Local", "url": f"/assets/{digest}/x.zip"}
    current = {
        "id": 9,
        "title": "Example",
        "type": "DynamicAttachment",
        "isEnabled": False,
        "flags": [{"flag": "flag{test}", "attachment": attachment}],
    }
    calls = []
    _, client = harness(
        lambda r: (
            calls.append(r)
            or (
                httpx.Response(200, content=b"zip")
                if r.url.path.startswith("/assets/")
                else httpx.Response(200, json=current)
            )
        )
    )
    spec = manifest(
        challenge={"title": "Example", "type": "DynamicAttachment"},
        configuration={"fileName": "x.zip"},
        flags=[{"flag": "flag{test}", "attachmentType": "Local", "fileHash": digest}],
    )
    result = await deploy(client, 1, spec, dry_run=False, challenge_id=9)
    assert result["completed"]
    assert all(not r.url.path.endswith("/Flags") for r in calls)


async def test_resume_refuses_enabled_or_wrong_type(harness):
    _, client = harness(
        lambda r: httpx.Response(
            200, json={"id": 9, "title": "Example", "type": "StaticAttachment", "isEnabled": True}
        )
    )
    result = await deploy(client, 1, manifest(), dry_run=False, challenge_id=9)
    assert result["stage"] == "inspect" and not result["completed"]


def test_model_contract():
    assert ChallengeUpdate(cpu_count=2, is_enabled=False).payload() == {
        "cpuCount": 2,
        "isEnabled": False,
    }
    for data in [{"typo": 1}, {"cpuCount": 0}, {"minScoreRate": 2}]:
        with pytest.raises(ValidationError):
            ChallengeUpdate.model_validate(data)
    with pytest.raises(ValidationError):
        manifest(challenge={"title": "x", "type": "DynamicAttachment"}, attachmentPath="x")
    with pytest.raises(ValidationError):
        manifest(flags=[{"flag": "same"}, {"flag": "same"}])
    with pytest.raises(ValidationError):
        manifest(challenge={"title": "x", "type": "DynamicContainer"})


@pytest.mark.parametrize(
    ("tool", "args", "method", "path"),
    [
        (
            "container_action",
            {"game_id": 1, "challenge_id": 2, "action": "start"},
            "POST",
            "/api/game/1/Container/2",
        ),
        (
            "container_action",
            {"game_id": 1, "challenge_id": 2, "action": "extend"},
            "POST",
            "/api/game/1/Container/2/Extend",
        ),
        (
            "container_action",
            {"game_id": 1, "challenge_id": 2, "action": "stop"},
            "DELETE",
            "/api/game/1/Container/2",
        ),
        (
            "admin_test_container",
            {"game_id": 1, "challenge_id": 2, "action": "start"},
            "POST",
            "/api/edit/Games/1/Challenges/2/Container",
        ),
    ],
)
async def test_action_routes(harness, tool, args, method, path):
    requests = []
    server, _ = harness(lambda r: requests.append(r) or httpx.Response(200))
    await server.call_tool(tool, args)
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == path
    if tool == "join_game":
        assert json.loads(requests[0].content) == {
            "teamId": 3,
            "divisionId": None,
            "inviteCode": None,
        }


async def test_examples_and_game_dates(harness):
    from pathlib import Path

    from gzctf_mcp.models import GameCreate

    for example in Path("examples").glob("*.json"):
        if example.name.startswith("mcp-client"):
            continue
        ChallengeManifest.model_validate_json(example.read_text())
    with pytest.raises(ValidationError):
        GameCreate(title="Test", start="2026-10-21T00:00:00", end="2026-10-22T00:00:00")
    requests = []
    server, _ = harness(lambda r: requests.append(r) or httpx.Response(200, json={"id": 1}))
    await server.call_tool(
        "admin_create_game",
        {
            "game": {
                "title": "Test",
                "start": "2026-10-21T00:00:00+08:00",
                "end": "2026-10-22T00:00:00+08:00",
            }
        },
    )
    assert requests[0].url.path == "/api/edit/Games"
    assert json.loads(requests[0].content)["hidden"] is True


async def test_download_hash_mismatch_cleans_file(harness, settings):
    _, client = harness(lambda r: httpx.Response(200, content=b"corrupt"))
    with pytest.raises(GZCTFError, match="SHA256"):
        await client.download("/assets/" + "0" * 64 + "/x", "x")
    assert not (settings.workspace / "downloads/x").exists()
