"""Authorized administrator-only smoke test for the specified GZCTF site.

Creates a hidden, future test competition. Never enrolls or submits an answer.
Uses only this run's unique resources and verifies their cleanup in finally.
"""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://covteam-ctf.nacocx.top"
ALLOWED_TOOLS = {
    "connection_info",
    "check_session",
    "admin_create_game",
    "admin_get_game",
    "admin_list_challenges",
    "admin_get_challenge",
    "admin_upload_file",
    "admin_deploy_challenge",
    "admin_update_challenge",
    "admin_add_flags",
    "admin_delete_flag",
    "admin_delete_challenge",
}


async def cleanup_test_asset(admin, file_hash, run_id):
    """Check admin inventory and an uncached URL, rather than trusting stale downloads."""

    async def present_in_inventory():
        for skip in range(0, 10000, 500):
            response = await admin.get("/api/admin/Files", params={"count": 500, "skip": skip})
            if response.status_code != 200:
                raise RuntimeError("Cannot verify administrator file inventory")
            items = response.json()["data"]
            if any(item["hash"] == file_hash for item in items):
                return True
            if len(items) < 500:
                return False
        raise RuntimeError("File inventory pagination limit reached")

    if await present_in_inventory():
        deleted = await admin.delete(f"/api/assets/{file_hash}")
        if deleted.status_code not in (200, 204, 404):
            raise RuntimeError(f"Asset cleanup failed: HTTP {deleted.status_code}")
    assert not await present_in_inventory(), "Test attachment remains in file inventory"
    # GZCTF serves identical content for arbitrary filenames at the same hash.
    fresh_path = f"/assets/{file_hash}/cleanup-{run_id}-{secrets.token_hex(6)}.txt"
    response = await admin.get(fresh_path, headers={"Cache-Control": "no-cache"})
    assert response.status_code == 404, "Test attachment still exists in origin storage"
    return {
        "attachmentAbsent": True,
        "attachmentInventoryAbsent": True,
        "attachmentFreshPathHttp": response.status_code,
    }


async def run():
    values = dotenv_values(ROOT / ".env")
    cookie = (values.get("GZCTF_ADMIN_COOKIE") or "").strip()
    if not cookie:
        raise RuntimeError("GZCTF_ADMIN_COOKIE is missing from .env")
    if "=" not in cookie:
        cookie = "GZCTF_Token=" + cookie
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    title = "MCP smoke DELETE " + run_id
    challenge_title = "MCP temporary " + run_id
    work = ROOT / ".local-test" / ("remote-" + run_id)
    work.mkdir(parents=True)
    attachment = work / "smoke.txt"
    attachment.write_text("Administrator upload test, no solving or submissions.\n" + run_id)
    file_hash = hashlib.sha256(attachment.read_bytes()).hexdigest()
    asset_path = f"/assets/{file_hash}/{attachment.name}"
    report = {
        "origin": ORIGIN,
        "runId": run_id,
        "startedAt": datetime.now(UTC).isoformat(),
        "scope": "administrator authoring only",
        "answerSubmissions": 0,
        "checks": [],
        "cleanup": {},
        "completed": False,
    }
    local_report = work / "report.json"
    game_id = None
    challenge_id = None
    uploaded = False

    def save():
        local_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def passed(name):
        report["checks"].append({"name": name, "passed": True})
        save()
        print("PASS " + name, flush=True)

    async with httpx.AsyncClient(
        base_url=ORIGIN, headers={"Cookie": cookie}, follow_redirects=False, timeout=40
    ) as admin:

        async def http(method, path, **kwargs):
            response = await admin.request(method, path, **kwargs)
            if not response.is_success:
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
            return response.json() if response.content else None

        async def find_games():
            matches = []
            for skip in range(0, 10000, 50):
                result = await http("GET", "/api/edit/Games", params={"count": 50, "skip": skip})
                items = result["data"]
                matches.extend(item for item in items if item["title"] == title)
                if len(items) < 50:
                    return matches
            raise RuntimeError("Game pagination limit reached during resource lookup")

        env = {k: v for k, v in os.environ.items() if not k.startswith("GZCTF_")}
        env.update(
            GZCTF_BASE_URL=ORIGIN,
            GZCTF_ADMIN_COOKIE=cookie,
            GZCTF_WORKSPACE=str(work),
            GZCTF_TIMEOUT="40",
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "gzctf_mcp"], env=env, cwd=str(ROOT)
        )
        try:
            async with (
                stdio_client(params) as (reader, writer),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()

                async def call(name, **arguments):
                    if name not in ALLOWED_TOOLS:
                        raise RuntimeError("Tool is outside the administrator-only test scope")
                    result = await session.call_tool(name, arguments)
                    if result.isError:
                        # Do not embed request arguments, credentials, or server response bodies.
                        raise RuntimeError(f"MCP {name} returned a tool error")
                    data = result.structuredContent or json.loads(result.content[0].text)
                    return data.get("data") if set(data) == {"data"} else data

                await call("check_session", role="admin")
                passed("administrator_authentication")
                now = datetime.now(UTC)
                game = await call(
                    "admin_create_game",
                    game={
                        "title": title,
                        "hidden": True,
                        "start": (now + timedelta(days=1)).isoformat(),
                        "end": (now + timedelta(days=2)).isoformat(),
                    },
                )
                game_id = game["id"]
                report["gameId"] = game_id
                save()
                game = await call("admin_get_game", game_id=game_id)
                assert game["hidden"] is True and game["title"] == title
                passed("isolated_hidden_future_game_created")
                flag = "flag{" + secrets.token_hex(16) + "}"
                manifest = {
                    "challenge": {
                        "title": challenge_title,
                        "type": "StaticAttachment",
                        "category": "Misc",
                    },
                    "configuration": {
                        "content": "Temporary administrator integration test; will be deleted.",
                        "originalScore": 123,
                        "hints": ["Temporary test only"],
                    },
                    "flags": [{"flag": flag}],
                    "publish": False,
                }
                before = await call("admin_list_challenges", game_id=game_id)
                await call("admin_deploy_challenge", game_id=game_id, manifest=manifest)
                assert before == await call("admin_list_challenges", game_id=game_id)
                passed("dry_run_no_remote_mutation")
                # Record the unique hash before upload, so timeout cleanup can still locate it.
                uploaded = True
                files = await call("admin_upload_file", path=attachment.name)
                assert len(files) == 1 and files[0]["hash"] == file_hash
                manifest["attachment"] = {"attachmentType": "Local", "fileHash": file_hash}
                passed("attachment_uploaded_sha256_verified")
                deployed = await call(
                    "admin_deploy_challenge", game_id=game_id, manifest=manifest, dry_run=False
                )
                challenge_id = deployed.get("challengeId")
                report["challengeId"] = challenge_id
                save()
                assert deployed.get("completed"), "Deployment did not complete"
                detail = await call(
                    "admin_get_challenge", game_id=game_id, challenge_id=challenge_id
                )
                assert detail["title"] == challenge_title and detail["isEnabled"] is False
                assert detail["originalScore"] == 123 and detail["flags"][0]["flag"] == flag
                assert detail["attachment"]["url"].split("/")[2] == file_hash
                passed("challenge_flags_attachment_configuration_readback")
                response = await admin.get(asset_path)
                assert response.status_code == 200 and response.content == attachment.read_bytes()
                passed("attachment_download_content_verified")
                resumed = await call(
                    "admin_deploy_challenge",
                    game_id=game_id,
                    challenge_id=challenge_id,
                    manifest=manifest,
                    dry_run=False,
                )
                assert resumed.get("completed")
                detail = await call(
                    "admin_get_challenge", game_id=game_id, challenge_id=challenge_id
                )
                assert len(detail["flags"]) == 1
                passed("resume_preserves_single_flag")
                await call(
                    "admin_add_flags",
                    game_id=game_id,
                    challenge_id=challenge_id,
                    flags=[{"flag": "flag{temporary_extra_" + run_id + "}"}],
                )
                detail = await call(
                    "admin_get_challenge", game_id=game_id, challenge_id=challenge_id
                )
                extra = next(item for item in detail["flags"] if item["flag"] != flag)
                await call(
                    "admin_delete_flag",
                    game_id=game_id,
                    challenge_id=challenge_id,
                    flag_id=extra["id"],
                )
                passed("add_and_delete_test_flag_without_submission")
                for enabled in [True, False]:
                    await call(
                        "admin_update_challenge",
                        game_id=game_id,
                        challenge_id=challenge_id,
                        configuration={"isEnabled": enabled, "originalScore": 234},
                    )
                    detail = await call(
                        "admin_get_challenge", game_id=game_id, challenge_id=challenge_id
                    )
                    assert detail["isEnabled"] is enabled and detail["originalScore"] == 234
                passed("publish_disable_and_score_update_in_hidden_game")
                await call("admin_delete_challenge", game_id=game_id, challenge_id=challenge_id)
                report["cleanup"]["challengeDeleteViaMcp"] = True
        except BaseException as error:
            report["failureType"] = type(error).__name__
            save()
            raise
        finally:
            # Lookup exact unique names to recover IDs after uncertain write responses.
            try:
                if game_id is None:
                    matches = await find_games()
                    assert len(matches) <= 1, "Ambiguous test game identity"
                    if matches:
                        game_id = matches[0]["id"]
                        report["gameId"] = game_id
                if game_id is not None:
                    check = await admin.get(f"/api/edit/Games/{game_id}")
                    if check.status_code != 404:
                        assert check.status_code == 200 and check.json()["title"] == title
                        challenges = await http("GET", f"/api/edit/Games/{game_id}/Challenges")
                        for item in challenges:
                            if item["title"] == challenge_title:
                                challenge_id = item["id"]
                                await http(
                                    "DELETE", f"/api/edit/Games/{game_id}/Challenges/{challenge_id}"
                                )
                        if challenge_id is not None:
                            check_challenge = await admin.get(
                                f"/api/edit/Games/{game_id}/Challenges/{challenge_id}"
                            )
                            assert check_challenge.status_code == 404, "Test challenge still exists"
                            report["cleanup"]["challengeAbsent"] = True
                        remaining = await http("GET", f"/api/edit/Games/{game_id}/Challenges")
                        assert not remaining, (
                            "Unexpected challenge in test game; refusing game deletion"
                        )
                        await http("DELETE", f"/api/edit/Games/{game_id}")
                    check = await admin.get(f"/api/edit/Games/{game_id}")
                    assert check.status_code == 404, "Test game still exists"
                    report["cleanup"]["gameAbsent"] = True
                if uploaded:
                    report["cleanup"].update(await cleanup_test_asset(admin, file_hash, run_id))
            except BaseException as error:
                report["cleanupErrorType"] = type(error).__name__
                save()
                raise
            save()
        report["completed"] = True
        report["finishedAt"] = datetime.now(UTC).isoformat()
        save()
        records = ROOT / "docs" / "records"
        records.mkdir(exist_ok=True)
        record_path = records / ("remote-admin-" + run_id + ".json")
        record_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(
            f"REMOTE ADMIN SMOKE PASSED: {len(report['checks'])} checks; "
            f"cleanup verified; no answer submissions. Report: {record_path.relative_to(ROOT)}",
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Execute the authorized temporary authoring test"
    )
    if not parser.parse_args().execute:
        parser.error("Pass --execute to create and clean up temporary test resources")
    asyncio.run(run())
