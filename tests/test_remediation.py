import base64
import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from gzctf_mcp.client import GZCTFError, normalize_cookie
from gzctf_mcp.models import ChallengeUpdate


def test_deadline_score_cookie_validation():
    assert ChallengeUpdate(clear_deadline=True).payload() == {"deadlineUtc": "1970-01-01T00:00:00Z"}
    for body in [
        {"deadlineUtc": None},
        {"deadlineUtc": "2026-01-01T00:00:00"},
        {"difficulty": 0},
        {"difficulty": float("nan")},
        {"originalScore": -1},
    ]:
        with pytest.raises(ValidationError):
            ChallengeUpdate.model_validate(body)
    assert normalize_cookie("abc==") == "GZCTF_Token=abc=="
    assert normalize_cookie(" raw ") == "GZCTF_Token=raw"
    assert normalize_cookie("Cookie: a=b; c=d") == "a=b; c=d"
    with pytest.raises(ValueError):
        normalize_cookie("a=b\r\nx=y")


async def test_encrypted_login_submit_and_cookie_refresh(harness, settings):
    private = X25519PrivateKey.generate()
    key = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    settings.player_username, settings.player_password = "tester", "environment-secret"
    posted = []

    def decrypt(text):
        data = base64.b64decode(text)
        shared = private.exchange(X25519PublicKey.from_public_bytes(data[:32]))
        return (
            AESGCM(hashlib.sha256(shared).digest()).decrypt(data[32:44], data[44:], None).decode()
        )

    def handler(r):
        if r.url.path == "/api/config":
            assert "cookie" not in r.headers
            return httpx.Response(200, json={"apiPublicKey": key})
        if r.url.path == "/api/captcha":
            return httpx.Response(200, json={"type": "None"})
        if r.url.path.endswith("/LogIn"):
            body = json.loads(r.content)
            assert decrypt(body["password"]) == settings.player_password
            return httpx.Response(200, headers={"Set-Cookie": "GZCTF_Token=new-session; Path=/"})
        posted.append(r)
        assert "GZCTF_Token=new-session" in r.headers["cookie"]
        assert decrypt(json.loads(r.content)["flag"]) == "flag{candidate}"
        return httpx.Response(200, json=42)

    server, client = harness(handler)
    await client.login("player")
    await server.call_tool(
        "submit_flag", {"game_id": 1, "challenge_id": 2, "flag": "flag{candidate}"}
    )
    assert len(posted) == 1


async def test_business_errors_redact_request_secrets(harness):
    def handler(r):
        return httpx.Response(
            400, json={"status": "InvalidInviteCode", "title": "bad sensitive-invite flag{hidden}"}
        )

    _, client = harness(handler)
    with pytest.raises(GZCTFError) as error:
        await client.request(
            "player", "POST", "/api/game/1", json={"inviteCode": "sensitive-invite"}
        )
    message = str(error.value)
    assert "InvalidInviteCode" in message
    assert "sensitive-invite" not in message and "hidden" not in message


async def test_join_explicit_division_pending_and_review(harness):
    calls = []

    def handler(r):
        calls.append(r)
        if r.url.path.endswith("/Check"):
            return httpx.Response(200, json={"joinableDivisions": [3]})
        if r.method == "GET":
            return httpx.Response(
                200, json={"divisions": [{"id": 3, "name": "Player"}], "status": "Pending"}
            )
        assert json.loads(r.content)["divisionId"] == 3
        return httpx.Response(200)

    server, _ = harness(handler)
    with pytest.raises(Exception, match="explicit division"):
        await server.call_tool("join_game", {"game_id": 1, "team_id": 2})
    value = await server.call_tool(
        "join_game", {"game_id": 1, "team_id": 2, "division_name": "Player"}
    )
    from test_contract import unpack

    assert unpack(value)["status"] == "Pending" and not unpack(value)["accepted"]
    assert sum(r.method == "POST" for r in calls) == 1


async def test_game_merge_preserves_settings_and_division_masks(harness):
    from gzctf_mcp.models import DivisionConfig

    value = DivisionConfig(
        name="player",
        default_permissions=["JoinGame", "ViewChallenge"],
        challenge_configs=[{"challengeId": 3, "permissions": []}],
    ).payload()
    assert value["defaultPermissions"] == 257
    assert value["challengeConfigs"] == [{"challengeId": 3, "permissions": 0}]
    current = {
        "title": "kept",
        "start": "2026-10-01T00:00:00Z",
        "end": "2026-11-01T00:00:00Z",
        "hidden": True,
        "inviteCode": "keep",
        "bloodBonus": 1,
        "publicKey": "key",
    }

    def handler(r):
        if r.method == "PUT":
            body = json.loads(r.content)
            assert body["hidden"] is True and body["inviteCode"] == "keep"
            assert body["title"] == "changed" and body["publicKey"] == "key"
            current.update(body)
        return httpx.Response(200, json=current)

    server, _ = harness(handler)
    await server.call_tool("admin_update_game", {"game_id": 1, "patch": {"title": "changed"}})


async def test_batch_uncertain_create_requires_reconciliation(harness, settings):
    from gzctf_mcp.batch import batch_deploy

    plan = {
        "items": [
            {
                "key": "one",
                "manifest": {"challenge": {"title": "one"}, "flags": [{"flag": "flag{secret}"}]},
            }
        ]
    }
    (settings.workspace / "plan.json").write_text(json.dumps(plan))
    calls = []

    def handler(r):
        calls.append(r)
        if r.method == "POST":
            raise httpx.ReadTimeout("uncertain", request=r)
        return httpx.Response(200, json={})

    _, client = harness(handler)
    preview = await batch_deploy(client, 1, "plan.json", "test")
    assert preview["dryRun"] and not calls
    result = await batch_deploy(client, 1, "plan.json", "test", False)
    assert not result["completed"]
    result = await batch_deploy(client, 1, "plan.json", "test", False)
    assert result["stage"] == "creating" and len(calls) == 1
    ledger = settings.workspace / ".mcp-state/test.json"
    assert "flag{" not in ledger.read_text()
    assert ledger.stat().st_mode & 0o777 == 0o600
    plan["items"][0]["manifest"]["challenge"]["title"] = "modified"
    (settings.workspace / "plan.json").write_text(json.dumps(plan))
    with pytest.raises(GZCTFError, match="fingerprint"):
        await batch_deploy(client, 1, "plan.json", "test", False)


async def test_batch_upload_timeout_keeps_id_without_reupload(harness, settings):
    from gzctf_mcp.batch import batch_deploy

    (settings.workspace / "payload.txt").write_bytes(b"payload")
    plan = {
        "items": [
            {
                "key": "one",
                "manifest": {"challenge": {"title": "one"}, "attachmentPath": "payload.txt"},
            }
        ]
    }
    (settings.workspace / "plan.json").write_text(json.dumps(plan))
    calls = []

    def handler(r):
        calls.append(r)
        if r.url.path == "/api/assets":
            raise httpx.ReadTimeout("uncertain", request=r)
        return httpx.Response(
            200,
            json={
                "id": 9,
                "title": "one",
                "type": "StaticAttachment",
                "isEnabled": False,
                "attachment": None,
                "flags": [],
            },
        )

    _, client = harness(handler)
    result = await batch_deploy(client, 1, "plan.json", "test", False)
    assert not result["completed"]
    result = await batch_deploy(client, 1, "plan.json", "test", False)
    assert result["stage"] == "uploading"
    ledger = json.loads((settings.workspace / ".mcp-state/test.json").read_text())
    assert ledger["items"]["one"]["challengeId"] == 9
    assert sum(r.url.path == "/api/assets" for r in calls) == 1


async def test_binary_export_limit_error_cleanup_and_exclusive(harness, settings):
    _, client = harness(
        lambda r: httpx.Response(
            200, content=b"PK-test", headers={"Content-Type": "application/zip"}
        )
    )
    settings.max_file_bytes = 4
    with pytest.raises(GZCTFError, match="size limit"):
        await client.export_binary("admin", "POST", "/api/edit/Games/1/Export", "game.zip")
    assert not (settings.workspace / "downloads/game.zip").exists()
    settings.max_file_bytes = 100
    result = await client.export_binary("admin", "POST", "/api/edit/Games/1/Export", "game.zip")
    assert result["sha256"] == hashlib.sha256(b"PK-test").hexdigest()
    with pytest.raises(FileExistsError):
        await client.export_binary("admin", "POST", "/api/edit/Games/1/Export", "game.zip")


async def test_binary_upstream_error_remains_sanitized(harness):
    _, client = harness(lambda r: httpx.Response(403, json={"title": "Denied", "status": 403}))
    with pytest.raises(GZCTFError, match="HTTP 403"):
        await client.export_binary("admin", "GET", "/api/admin/Writeups/1/All", "all.tar")
