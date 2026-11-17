"""Real MCP stdio checks against the isolated encrypted local Docker fixture only.

No flag submissions, no remote-site changes. Test games/teams are deleted in finally.
"""

import asyncio
import hashlib
import json
import os
import secrets
import struct
import sys
import tarfile
import zipfile
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gzctf_mcp.client import Client
from gzctf_mcp.config import Settings

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:18082"
REPORT = ROOT / ".local-test/gap-report.json"


async def run():
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    secrets_env = dotenv_values(ROOT / ".local-test/compose.env")
    workspace = ROOT / ".local-test/gap-workspace"
    workspace.mkdir(exist_ok=True)
    run_id = datetime.now(UTC).strftime("%H%M%S") + secrets.token_hex(3)
    username = "gap" + run_id
    report = {
        "origin": ORIGIN,
        "runId": run_id,
        "checks": [],
        "completed": False,
        "flagSubmissions": 0,
        "remoteMutations": False,
        "cleanup": [],
    }

    def persist():
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def passed(name):
        report["checks"].append({"name": name, "passed": True})
        persist()
        print("PASS " + name, flush=True)

    # Replace any earlier run's report before bootstrap can fail.
    persist()

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"\x00\x00\xff\x00\x00\xff\x00" * 2)) + chunk(b"IEND", b"")
    (workspace / "fixture.png").write_bytes(png)
    # Bootstrap a fixture-only account; registration is outside this MCP's auth scope.
    bootstrap = Client(
        Settings(
            base_url=ORIGIN,
            workspace=workspace,
            admin_username="Admin",
            admin_password=secrets_env["ADMIN_PASSWORD"],
        )
    )
    await bootstrap.login("admin")
    platform = await bootstrap.request("admin", "GET", "/api/admin/Config")
    platform["globalConfig"]["apiEncryption"] = True
    await bootstrap.request("admin", "PUT", "/api/admin/Config", json=platform)
    for _ in range(60):
        if (await bootstrap.request("public", "GET", "/api/config")).get("apiPublicKey"):
            break
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError("Fixture API encryption key was not published")
    encrypted = await bootstrap.encrypt(secrets_env["PLAYER_PASSWORD"])
    async with httpx.AsyncClient(base_url=ORIGIN, trust_env=False) as raw:
        response = await raw.post(
            "/api/account/Register",
            json={
                "userName": username,
                "email": username + "@example.invalid",
                "password": encrypted,
            },
        )
        if response.status_code != 200:
            bootstrap.check_response(response)
    await bootstrap.close()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GZCTF_")}
    env.update(
        GZCTF_BASE_URL=ORIGIN,
        GZCTF_WORKSPACE=str(workspace),
        GZCTF_ADMIN_USERNAME="Admin",
        GZCTF_ADMIN_PASSWORD=secrets_env["ADMIN_PASSWORD"],
        GZCTF_PLAYER_USERNAME=username,
        GZCTF_PLAYER_PASSWORD=secrets_env["PLAYER_PASSWORD"],
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "gzctf_mcp"], env=env, cwd=str(ROOT)
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()

        async def call(name, **args):
            result = await session.call_tool(name, args)
            if result.isError:
                # Sanitized tool errors only; never dump HTTP headers, env or manifests.
                raise RuntimeError(name + ": " + result.content[0].text)
            return result.structuredContent or json.loads(result.content[0].text)

        games, team_id = [], None
        try:
            config = await call("auth_requirements")
            assert config["config"]["apiPublicKey"]
            await call("auth_login", role="admin")
            await call("auth_login", role="player")
            await call("check_session", role="admin")
            passed("encrypted_login_and_session_roles")
            now = datetime.now(UTC)
            game = (
                await call(
                    "admin_create_game",
                    game={
                        "title": "MCP gap " + run_id,
                        "start": (now - timedelta(hours=1)).isoformat(),
                        "end": (now + timedelta(days=1)).isoformat(),
                        "hidden": False,
                        "inviteCode": "local-only-code",
                        "summary": "preserve me",
                    },
                )
            )["data"]
            gid = game["id"] if isinstance(game, dict) else game
            games.append(gid)
            team = (await call("save_team", team={"name": "gap " + run_id, "bio": "preserved"}))[
                "data"
            ]
            team_id = team["id"]
            await call("save_team", team_id=team_id, team={"name": "gap2 " + run_id})
            assert (await call("get_team", team_id=team_id))["data"]["bio"] == "preserved"
            await call("team_invite", team_id=team_id)
            await call("team_rotate_invite", team_id=team_id)
            await call("team_avatar", team_id=team_id, path="fixture.png")
            await call("admin_game_poster", game_id=gid, path="fixture.png")
            passed("team_create_update_invitation_poster_avatar")
            content = b"local acceptance attachment " + run_id.encode()
            (workspace / "attachment.txt").write_bytes(content)
            manifest = {
                "challenge": {"title": "resume " + run_id},
                "configuration": {
                    "hints": ["hint"],
                    "originalScore": 600,
                    "difficulty": 4.5,
                    "minScoreRate": 0.25,
                },
                "attachmentPath": "attachment.txt",
                "flags": [{"flag": "flag{fixture-only}"}],
            }
            result = await call(
                "admin_deploy_challenge", game_id=gid, manifest=manifest, dry_run=False
            )
            assert result["completed"], result
            cid = result["challengeId"]
            before = (await call("admin_files", count=100))["data"]
            result = await call(
                "admin_deploy_challenge",
                game_id=gid,
                challenge_id=cid,
                manifest=manifest,
                dry_run=False,
            )
            assert result["completed"], result
            after = (await call("admin_files", count=100))["data"]
            assert before == after, "Resume changed file inventory/reference count"
            challenge = (await call("admin_get_challenge", game_id=gid, challenge_id=cid))["data"]
            assert challenge["hints"] == ["hint"] and challenge["difficulty"] == 4.5
            assert challenge["originalScore"] == 600
            hash_manifest = dict(manifest)
            hash_manifest.pop("attachmentPath")
            hash_manifest["attachment"] = {
                "attachmentType": "Local",
                "fileHash": hashlib.sha256(content).hexdigest(),
            }
            by_hash = await call(
                "admin_deploy_challenge",
                game_id=gid,
                challenge_id=cid,
                manifest=hash_manifest,
                dry_run=False,
            )
            assert by_hash["completed"]
            passed("attachment_resume_content_and_reference_count")
            await call(
                "admin_update_challenge",
                game_id=gid,
                challenge_id=cid,
                configuration={"deadlineUtc": (now + timedelta(hours=8)).isoformat()},
            )
            assert (await call("admin_get_challenge", game_id=gid, challenge_id=cid))["data"][
                "deadlineUtc"
            ]
            await call(
                "admin_update_challenge",
                game_id=gid,
                challenge_id=cid,
                configuration={"clearDeadline": True},
            )
            assert (await call("admin_get_challenge", game_id=gid, challenge_id=cid))["data"][
                "deadlineUtc"
            ] is None
            passed("deadline_set_and_explicit_clear")
            player = (
                await call(
                    "admin_save_division",
                    game_id=gid,
                    division={
                        "name": "Player",
                        "defaultPermissions": [
                            "JoinGame",
                            "RequireReview",
                            "ViewChallenge",
                            "RankOverall",
                        ],
                        "challengeConfigs": [
                            {"challengeId": cid, "permissions": ["ViewChallenge"]}
                        ],
                    },
                )
            )["data"]
            extra = (
                await call(
                    "admin_save_division",
                    game_id=gid,
                    division={"name": "AdminTeam", "inviteCode": "division-code"},
                )
            )["data"]
            await call(
                "admin_save_division",
                game_id=gid,
                division_id=extra["id"],
                division={"name": "AdminTeam2", "inviteCode": ""},
            )
            divisions = (await call("admin_list_divisions", game_id=gid))["data"]
            assert len(divisions) == 2
            joined = await call(
                "join_game",
                game_id=gid,
                team_id=team_id,
                division_name="Player",
                invite_code="local-only-code",
            )
            assert joined["status"] == "Pending" and not joined["accepted"], joined
            parts = (await call("admin_participations", game_id=gid))["data"]
            assert len(parts) == 1
            await call(
                "admin_review_participation",
                participation_id=parts[0]["id"],
                status="Accepted",
                division_id=player["id"],
            )
            assert (await call("get_game", game_id=gid))["data"]["status"] == "Accepted"
            await call("writeup_status", game_id=gid)
            await call(
                "admin_update_game",
                game_id=gid,
                patch={
                    "writeupRequired": True,
                    "writeupDeadline": (now + timedelta(days=2)).isoformat(),
                },
            )
            from live_acceptance import pdf_bytes

            (workspace / "fixture.pdf").write_bytes(pdf_bytes())
            await call("submit_writeup", game_id=gid, path="fixture.pdf")
            assert (await call("writeup_status", game_id=gid))["data"]
            archive = await call(
                "admin_export_records",
                game_id=gid,
                kind="writeups",
                filename="writeups-" + run_id + ".tar",
            )
            with tarfile.open(archive["path"]) as exported_tar:
                assert any(m.name.endswith(".pdf") for m in exported_tar.getmembers())
            passed("writeup_status_upload_and_tar_export")
            passed("division_permissions_named_join_pending_review_accepted")
            await call(
                "admin_update_game",
                game_id=gid,
                patch={
                    "title": "updated " + run_id,
                    "bloodBonus": {"first": 100, "second": 50, "third": 20},
                },
            )
            updated = (await call("admin_get_game", game_id=gid))["data"]
            assert (
                updated["summary"] == "preserve me" and updated["inviteCode"] == "local-only-code"
            )
            assert updated["bloodBonus"] == (100 << 20) | (50 << 10) | 20
            notice = (await call("admin_save_notice", game_id=gid, content="test notice"))["data"]
            await call(
                "admin_save_notice", game_id=gid, notice_id=notice["id"], content="updated notice"
            )
            assert len((await call("admin_notices", game_id=gid))["data"]) == 1
            await call("admin_delete_notice", game_id=gid, notice_id=notice["id"])
            await call("admin_flush_scoreboard", game_id=gid)
            await call("admin_events", game_id=gid)
            await call("admin_submissions", game_id=gid)
            await call("admin_instances")
            passed("game_read_merge_write_notices_observability")
            (workspace / "flag-a.txt").write_bytes(b"fixture A " + run_id.encode())
            (workspace / "flag-b.txt").write_bytes(b"fixture B " + run_id.encode())
            plan = {
                "items": [
                    {
                        "key": "static",
                        "manifest": {
                            "challenge": {"title": "batch static " + run_id},
                            "flags": [{"flag": "flag{static-fixture}"}],
                        },
                    },
                    {
                        "key": "dynamic",
                        "manifest": {
                            "challenge": {
                                "title": "batch dynamic " + run_id,
                                "type": "DynamicAttachment",
                            },
                            "configuration": {"fileName": "fixture.txt"},
                            "flags": [
                                {
                                    "flag": "flag{A}",
                                    "attachmentType": "Local",
                                    "attachmentPath": "flag-a.txt",
                                },
                                {
                                    "flag": "flag{B}",
                                    "attachmentType": "Local",
                                    "attachmentPath": "flag-b.txt",
                                },
                            ],
                        },
                    },
                ]
            }
            plan_name = "batch-" + run_id + ".json"
            (workspace / plan_name).write_text(json.dumps(plan))
            batch_args = {"game_id": gid, "plan_file": plan_name, "state_name": "batch-" + run_id}
            assert (await call("admin_deploy_batch", **batch_args))["dryRun"]
            batch = await call("admin_deploy_batch", **batch_args, dry_run=False)
            assert batch["completed"], batch
            assert (await call("admin_deploy_batch", **batch_args, dry_run=False))["completed"]
            ledger = await call("admin_batch_status", state_name="batch-" + run_id)
            assert "flag{" not in json.dumps(ledger)
            # Per-challenge overrides must affect actual participant visibility.
            static_id = batch["items"]["static"]["challengeId"]
            for challenge_id in (cid, static_id):
                await call(
                    "admin_update_challenge",
                    game_id=gid,
                    challenge_id=challenge_id,
                    configuration={"isEnabled": True},
                )
            await call(
                "admin_save_division",
                game_id=gid,
                division_id=player["id"],
                division={
                    "name": "Player",
                    "challengeConfigs": [
                        {"challengeId": cid, "permissions": ["ViewChallenge"]},
                        {"challengeId": static_id, "permissions": []},
                    ],
                },
            )
            visible = (await call("list_challenges", game_id=gid))["data"]

            # The upstream participant response nests categories; inspect IDs in the JSON tree.
            def challenge_ids(value):
                if isinstance(value, dict):
                    if "title" in value and "id" in value:
                        yield value["id"]
                    for child in value.values():
                        yield from challenge_ids(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from challenge_ids(child)

            visible_ids = set(challenge_ids(visible))
            assert cid in visible_ids and static_id not in visible_ids
            passed("division_challenge_visibility_override")
            passed("batch_preview_dynamic_upload_resume_secret_free_ledger")
            exported = await call(
                "admin_export_game", game_id=gid, filename="game-" + run_id + ".zip"
            )
            output = Path(exported["path"])
            assert zipfile.is_zipfile(output)
            assert hashlib.sha256(output.read_bytes()).hexdigest() == exported["sha256"]
            imported = (await call("admin_import_game", path=str(output.relative_to(workspace))))[
                "data"
            ]
            imported_id = imported["id"] if isinstance(imported, dict) else imported
            games.append(imported_id)
            assert len((await call("admin_list_challenges", game_id=imported_id))["data"]) == 3
            for kind in ("scoreboard", "submissions"):
                sheet = await call(
                    "admin_export_records",
                    game_id=gid,
                    kind=kind,
                    filename=kind + "-" + run_id + ".xlsx",
                )
                assert zipfile.is_zipfile(sheet["path"])
            passed("official_game_zip_import_export_and_xlsx_records")
            # An unbound upload is owned only by this test; deletion is safe to verify.
            (workspace / "orphan.txt").write_bytes(b"owned orphan " + run_id.encode())
            orphan = (await call("admin_upload_file", path="orphan.txt"))["data"][0]
            assert (await call("admin_delete_file", file_hash=orphan["hash"]))["dryRun"]
            await call("admin_delete_file", file_hash=orphan["hash"], dry_run=False)
            try:
                await call(
                    "download_attachment",
                    asset_path="/assets/" + orphan["hash"] + "/fresh.txt",
                    filename="orphan-check.txt",
                )
            except RuntimeError as error:
                assert "HTTP 404" in str(error)
            else:
                raise AssertionError("Deleted orphan blob remains downloadable")
            passed("orphan_file_delete_fresh_readback")
            await call("admin_cleanup_batch", state_name="batch-" + run_id, dry_run=False)
            assert len((await call("admin_list_challenges", game_id=gid))["data"]) == 1
            await call("admin_delete_division", game_id=gid, division_id=extra["id"])
            # GZCTF forbids withdrawal after approval. Rejected participants may withdraw.
            try:
                await call("leave_game", game_id=gid)
            except RuntimeError as error:
                assert "after entrance approval" in str(error)
            else:
                raise AssertionError("Approved participant unexpectedly withdrew")
            await call(
                "admin_review_participation", participation_id=parts[0]["id"], status="Rejected"
            )
            await call("leave_game", game_id=gid)
            await call("auth_logout", role="player")
            passed("batch_cleanup_division_delete_withdraw_logout")
            report["completed"] = True
        finally:
            for gid in reversed(games):
                try:
                    await call("admin_delete_game", game_id=gid)
                    report["cleanup"].append({"gameId": gid, "deleted": True})
                except RuntimeError:
                    report["cleanup"].append({"gameId": gid, "deleted": False})
            if team_id:
                try:
                    await call("team_action", team_id=team_id, action="delete")
                    report["cleanup"].append({"teamId": team_id, "deleted": True})
                except RuntimeError:
                    report["cleanup"].append({"teamId": team_id, "deleted": False})
            persist()
    if not all(item["deleted"] for item in report["cleanup"]):
        raise RuntimeError("Fixture cleanup incomplete; inspect local report")
    print("Acceptance complete; no Flag submitted; fixture games/teams deleted.", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
