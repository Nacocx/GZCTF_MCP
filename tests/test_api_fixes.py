"""Targeted regressions for the 2026-11-17 API review; no live services."""

import asyncio
import hashlib
import json
from datetime import datetime

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from gzctf_mcp.batch import batch_deploy
from gzctf_mcp.client import GZCTFError
from gzctf_mcp.models import Attachment, ChallengeManifest
from gzctf_mcp.workflow import deploy, set_attachment


async def test_one_upload_per_binding_and_same_target_resume(harness, settings):
    payload = b"shared attachment"
    digest = hashlib.sha256(payload).hexdigest()
    (settings.workspace / "asset.bin").write_bytes(payload)
    attachments = {}
    references = 0
    posts = []

    def handler(r):
        nonlocal references
        if r.url.path == "/api/assets":
            references += 1
            return httpx.Response(200, json=[{"hash": digest}])
        if r.url.path.startswith("/assets/"):
            return httpx.Response(200, content=payload) if references else httpx.Response(404)
        identifier = int(r.url.path.split("/")[6])
        if r.method == "POST":
            posts.append(identifier)
            attachments[identifier] = {"type": "Local", "url": f"/assets/{digest}/asset.bin"}
            return httpx.Response(200)
        if r.method == "DELETE":
            del attachments[identifier]
            references -= 1
            return httpx.Response(200)
        return httpx.Response(200, json={"attachment": attachments.get(identifier)})

    server, api = harness(handler)
    desired = Attachment(attachment_type="Local", file_hash=digest)
    with pytest.raises(GZCTFError, match="No unused upload"):
        await set_attachment(api, 1, 1, desired)
    await api.upload("asset.bin")
    await set_attachment(api, 1, 1, desired)
    await set_attachment(api, 1, 1, desired)
    assert references == 1 and posts == [1]
    with pytest.raises(GZCTFError, match="No unused upload"):
        await set_attachment(api, 1, 2, desired)
    await api.upload("asset.bin")
    await set_attachment(api, 1, 2, desired)
    await server.call_tool("admin_delete_challenge", {"game_id": 1, "challenge_id": 1})
    assert references == 1 and posts == [1, 2]
    assert (await set_attachment(api, 1, 2, desired))["verified"]


async def test_dynamic_flag_references_are_counted_atomically(harness, settings):
    payload = b"dynamic"
    digest = hashlib.sha256(payload).hexdigest()
    (settings.workspace / "a").write_bytes(payload)
    writes = []

    def handler(r):
        if r.url.path == "/api/assets":
            return httpx.Response(200, json=[{"hash": digest}])
        writes.append(r)
        return httpx.Response(200)

    server, api = harness(handler)
    flags = [
        {"flag": f"answer-{n}", "attachmentType": "Local", "fileHash": digest} for n in range(2)
    ]
    await api.upload("a")
    with pytest.raises(ToolError, match="No unused upload"):
        await server.call_tool("admin_add_flags", {"game_id": 1, "challenge_id": 9, "flags": flags})
    assert not writes and api.upload_references[digest] == 1
    await api.upload("a")
    await server.call_tool("admin_add_flags", {"game_id": 1, "challenge_id": 9, "flags": flags})
    assert len(writes) == 1 and api.upload_references[digest] == 0


async def test_batch_restart_preserves_flag_reference_ownership(harness, settings):
    payload = b"same contents"
    digest = hashlib.sha256(payload).hexdigest()
    (settings.workspace / "a").write_bytes(payload)
    manifest = {
        "challenge": {"title": "batch", "type": "DynamicAttachment"},
        "flags": [
            {"flag": f"answer-{i}", "attachmentType": "Local", "attachmentPath": "a"}
            for i in range(2)
        ],
    }
    (settings.workspace / "plan.json").write_text(
        json.dumps({"items": [{"key": "one", "manifest": manifest}]})
    )
    remote = {
        "id": 9,
        "title": "batch",
        "type": "DynamicAttachment",
        "isEnabled": False,
        "flags": [],
    }
    uploads, appends = 0, 0

    def handler(r):
        nonlocal uploads, appends
        if r.url.path == "/api/assets":
            uploads += 1
            return httpx.Response(200, json=[{"hash": digest}])
        if r.url.path.startswith("/assets/"):
            return httpx.Response(200, content=payload)
        if r.url.path.endswith("/Flags"):
            appends += 1
            remote["flags"] = [
                {"flag": f["flag"], "attachment": {"type": "Local", "url": f"/assets/{digest}/a"}}
                for f in json.loads(r.content)
            ]
            raise httpx.ReadTimeout("lost reply", request=r)
        return httpx.Response(200, json=remote)

    _, api = harness(handler)
    first = await batch_deploy(api, 1, "plan.json", "restart", False)
    assert not first["completed"]
    _, restarted = harness(handler)
    result = await batch_deploy(restarted, 1, "plan.json", "restart", False)
    assert result["completed"] and (uploads, appends) == (2, 1)
    slots = result["items"]["one"]["uploadReferences"]
    assert slots == {f"flag:{i}": {"hash": digest, "state": "bound"} for i in range(2)}


async def test_attachment_readback_timeout_keeps_recovery_result(harness, settings):
    payload = b"asset"
    digest = hashlib.sha256(payload).hexdigest()
    (settings.workspace / "a").write_bytes(payload)
    state = {"id": 9, "title": "review", "type": "StaticAttachment", "isEnabled": False}

    def handler(r):
        if r.url.path == "/api/assets":
            return httpx.Response(200, json=[{"hash": digest}])
        if r.url.path.startswith("/assets/"):
            raise httpx.ReadTimeout("private network details", request=r)
        if r.url.path.endswith("/Attachment"):
            state["attachment"] = {"type": "Local", "url": f"/assets/{digest}/a"}
        return httpx.Response(200, json=state)

    _, api = harness(handler)
    result = await deploy(
        api,
        1,
        ChallengeManifest.model_validate({"challenge": {"title": "review"}, "attachmentPath": "a"}),
        False,
    )
    assert (
        not result["completed"] and result["challengeId"] == 9 and result["stage"] == "attachment"
    )
    assert result["resources"]["uploadReferences"]["attachment"]["state"] == "bound"
    assert "private network details" not in str(result)


async def test_batch_reconciles_one_unbound_slot_without_reupload(harness, settings):
    payload = b"reserved"
    digest = hashlib.sha256(payload).hexdigest()
    (settings.workspace / "a").write_bytes(payload)
    (settings.workspace / "plan.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "key": "one",
                        "manifest": {"challenge": {"title": "one"}, "attachmentPath": "a"},
                    }
                ]
            }
        )
    )
    remote = {"id": 9, "title": "one", "type": "StaticAttachment", "isEnabled": False}
    uploads, binds = 0, 0

    def handler(r):
        nonlocal uploads, binds
        if r.url.path == "/api/assets":
            uploads += 1
            return httpx.Response(200, json=[{"hash": digest}])
        if r.url.path.startswith("/assets/"):
            return httpx.Response(200, content=payload)
        if r.url.path.endswith("/Attachment"):
            binds += 1
            if binds == 1:
                raise httpx.ConnectError("request not applied", request=r)
            remote["attachment"] = {"type": "Local", "url": f"/assets/{digest}/a"}
        return httpx.Response(200, json=remote)

    _, api = harness(handler)
    assert not (await batch_deploy(api, 1, "plan.json", "slots", False))["completed"]
    server, restarted = harness(handler)
    # No automatic replay when the upload might already have been consumed.
    assert not (await batch_deploy(restarted, 1, "plan.json", "slots", False))["completed"]
    assert (uploads, binds) == (1, 1)
    await server.call_tool(
        "admin_batch_reconcile",
        {
            "state_name": "slots",
            "key": "one",
            "challenge_id": 9,
            "uploaded_hashes": [digest],
            "reference_slot": "attachment",
        },
    )
    assert (await batch_deploy(restarted, 1, "plan.json", "slots", False))["completed"]
    assert (uploads, binds) == (1, 2)


async def test_raw_hash_preflight_does_not_create_orphan(harness):
    calls = []
    _, api = harness(lambda r: calls.append(r) or httpx.Response(200, json={"id": 9}))
    manifest = ChallengeManifest.model_validate(
        {
            "challenge": {"title": "one"},
            "attachment": {"attachmentType": "Local", "fileHash": "a" * 64},
        }
    )
    result = await deploy(api, 1, manifest, False)
    assert not result["completed"] and not calls


@pytest.mark.parametrize("status", [200, 403])
async def test_stream_cookie_refresh_on_success_and_error(harness, status):
    cookies = []

    def handler(r):
        cookies.append(r.headers.get("cookie"))
        if len(cookies) == 1:
            return httpx.Response(
                status,
                content=b"archive",
                headers={
                    "Content-Type": "application/zip",
                    "Set-Cookie": "GZCTF_Token=renewed; Path=/",
                },
            )
        return httpx.Response(200, content=b"archive", headers={"Content-Type": "application/zip"})

    _, api = harness(handler)
    if status == 403:
        with pytest.raises(GZCTFError) as error:
            await api.export_binary("admin", "POST", "/export", "first.zip")
        assert error.value.http_status == 403
    else:
        await api.export_binary("admin", "POST", "/export", "first.zip")
    await api.export_binary("admin", "POST", "/export", "second.zip")
    assert cookies[1] == "GZCTF_Token=renewed"


async def test_public_download_and_explicit_role(harness, settings):
    settings.player_cookie = ""
    payload = b"public"
    digest = hashlib.sha256(payload).hexdigest()
    cookies = []
    server, api = harness(
        lambda r: cookies.append(r.headers.get("cookie")) or httpx.Response(200, content=payload)
    )
    await server.call_tool(
        "download_attachment", {"asset_path": f"/assets/{digest}/a", "filename": "public.bin"}
    )
    await api.download(f"/assets/{digest}/a", "admin.bin", "admin")
    assert cookies == [None, "admin-session=secret-a"]


async def test_concurrent_game_patches_preserve_both_changes(harness):
    state = {"title": "old", "hidden": True, "start": 1793491200000, "end": 1796083200000}

    async def handler(r):
        if r.method == "GET":
            snapshot = dict(state)
            await asyncio.sleep(0.01)
            return httpx.Response(200, json=snapshot)
        state.update(json.loads(r.content))
        return httpx.Response(200)

    server, _ = harness(handler)
    await asyncio.gather(
        server.call_tool("admin_update_game", {"game_id": 1, "patch": {"title": "new"}}),
        server.call_tool("admin_update_game", {"game_id": 1, "patch": {"hidden": False}}),
    )
    assert state["title"] == "new" and state["hidden"] is False


async def test_game_readback_conflict_is_reported(harness):
    server, _ = harness(
        lambda r: httpx.Response(
            200, json={"title": "concurrent edit", "start": 1793491200000, "end": 1796083200000}
        )
    )
    with pytest.raises(ToolError, match="readback differs"):
        await server.call_tool("admin_update_game", {"game_id": 1, "patch": {"title": "mine"}})


async def test_game_datetime_readback_uses_upstream_millisecond_precision(harness):
    state = {"title": "test", "start": 1793491200000, "end": 1796083200000}

    def handler(r):
        if r.method == "PUT":
            state.update(json.loads(r.content))
            deadline = datetime.fromisoformat(state["writeupDeadline"])
            state["writeupDeadline"] = int(deadline.timestamp() * 1000)
        return httpx.Response(200, json=state)

    server, _ = harness(handler)
    await server.call_tool(
        "admin_update_game",
        {
            "game_id": 1,
            "patch": {
                "writeupRequired": True,
                "writeupDeadline": "2026-12-01T12:34:56.123456+08:00",
            },
        },
    )
    assert state["writeupDeadline"] % 1000 == 123


async def test_cleanup_recovers_lost_delete_reply_and_checks_parent(harness, settings):
    directory = settings.workspace / ".mcp-state"
    directory.mkdir()
    path = directory / "cleanup.json"
    path.write_text(
        json.dumps(
            {
                "identity": {"origin": settings.base_url, "gameId": 1},
                "items": {
                    "one": {"challengeId": 9, "stage": "complete"},
                    "two": {"challengeId": 10, "stage": "complete"},
                },
            }
        )
    )
    existing = {9, 10}
    deleted = []
    parent_access = True

    def handler(r):
        if r.url.path.endswith("/Games/1"):
            return httpx.Response(200, json={"id": 1}) if parent_access else httpx.Response(403)
        if r.method == "GET":
            return httpx.Response(200, json=[{"id": i} for i in existing])
        identifier = int(r.url.path.rsplit("/", 1)[1])
        assert identifier in existing
        existing.remove(identifier)
        deleted.append(identifier)
        if identifier == 9:
            raise httpx.ReadTimeout("lost reply", request=r)
        return httpx.Response(200)

    server, _ = harness(handler)
    args = {"state_name": "cleanup", "dry_run": False}
    with pytest.raises(ToolError, match="may already have completed"):
        await server.call_tool("admin_cleanup_batch", args)
    assert json.loads(path.read_text())["items"]["one"]["stage"] == "deleting"
    parent_access = False
    restarted, _ = harness(handler)
    with pytest.raises(ToolError, match="HTTP 403"):
        await restarted.call_tool("admin_cleanup_batch", args)
    assert deleted == [9]
    parent_access = True
    await restarted.call_tool("admin_cleanup_batch", args)
    assert deleted == [9, 10] and not existing
    assert all(e["stage"] == "deleted" for e in json.loads(path.read_text())["items"].values())


@pytest.mark.parametrize("configuration", [{"fileName": "  "}, {"enableTrafficCapture": True}])
async def test_invalid_deployment_preflight_never_writes(harness, configuration):
    calls = []
    server, _ = harness(lambda r: calls.append(r) or httpx.Response(200))
    with pytest.raises((ToolError, ValidationError, ValueError)):
        await server.call_tool(
            "admin_deploy_challenge",
            {
                "game_id": 1,
                "dry_run": False,
                "manifest": {"challenge": {"title": "invalid"}, "configuration": configuration},
            },
        )
    assert not calls
