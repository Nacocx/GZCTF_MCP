"""Exercise real Docker-hosted GZCTF via a real MCP stdio subprocess.

Only targets the dedicated local fixture at 127.0.0.1:18080. No mocks.
Run local_setup.py and Docker Compose before this script.
"""

import asyncio
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
LOCAL = ROOT / ".local-test"
ORIGIN = "http://127.0.0.1:18080"
REPORT = LOCAL / "report.json"


def pdf_bytes():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << >> >>",
    ]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += b"xref\n0 4\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    result += f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return result


async def run():
    config = dotenv_values(LOCAL / "compose.env")
    workspace = LOCAL / "workspace"
    workspace.mkdir(exist_ok=True)
    run_id = datetime.now(UTC).strftime("%H%M%S") + secrets.token_hex(3)
    report = {
        "origin": ORIGIN,
        "runId": run_id,
        "startedAt": datetime.now(UTC).isoformat(),
        "checks": [],
        "completed": False,
    }

    def record(name, **values):
        report["checks"].append({"name": name, "passed": True, **values})
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"PASS {name}", flush=True)

    def require(response, label):
        if not response.is_success:
            # Fixture responses are never used to print account credentials or cookies.
            raise RuntimeError(f"{label}: HTTP {response.status_code}")
        return response.json() if response.content else None

    async with (
        httpx.AsyncClient(base_url=ORIGIN, trust_env=False, timeout=40) as admin,
        httpx.AsyncClient(base_url=ORIGIN, trust_env=False, timeout=40) as player,
    ):
        require(
            await admin.post(
                "/api/account/LogIn",
                json={"userName": "Admin", "password": config["ADMIN_PASSWORD"]},
            ),
            "admin login",
        )
        require(
            await player.post(
                "/api/account/Register",
                json={
                    "userName": "mcp" + run_id,
                    "email": f"mcp{run_id}@example.invalid",
                    "password": config["PLAYER_PASSWORD"],
                },
            ),
            "register test player",
        )
        require(
            await player.post(
                "/api/account/LogIn",
                json={"userName": "mcp" + run_id, "password": config["PLAYER_PASSWORD"]},
            ),
            "player login",
        )
        team = require(
            await player.post(
                "/api/team", json={"name": "MCP " + run_id, "bio": "Local MCP integration test"}
            ),
            "create team",
        )
        team_id = team["id"]
        record("bootstrap_accounts_and_team", teamId=team_id)
        cookie = lambda client: "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
        env_file = LOCAL / "mcp.env"
        env_file.write_text(
            f"GZCTF_BASE_URL={ORIGIN}\nGZCTF_WORKSPACE={workspace}\n"
            f"GZCTF_ADMIN_COOKIE={cookie(admin)}\n"
            f"GZCTF_PLAYER_COOKIE={cookie(player)}\nGZCTF_TIMEOUT=60\n"
        )
        env_file.chmod(0o600)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GZCTF_")}
        env.update(
            GZCTF_ENV_FILE=str(env_file),
            NO_PROXY="127.0.0.1,localhost",
            no_proxy="127.0.0.1,localhost",
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "gzctf_mcp"], env=env, cwd=str(ROOT)
        )
        async with (
            stdio_client(params) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()

            async def call(name, **arguments):
                result = await session.call_tool(name, arguments)
                if result.isError:
                    text = " ".join(getattr(content, "text", "") for content in result.content)
                    raise RuntimeError(f"{name}: {text}")
                data = result.structuredContent
                if data is None:
                    data = json.loads(result.content[0].text)
                return data.get("data") if set(data) == {"data"} else data

            async def verdict(challenge_id, flag, expected):
                submission = await call(
                    "submit_flag", game_id=game_id, challenge_id=challenge_id, flag=flag
                )
                for _ in range(40):
                    result = await call(
                        "submission_status",
                        game_id=game_id,
                        challenge_id=challenge_id,
                        submission_id=submission["submissionId"],
                    )
                    if not result["pending"]:
                        assert result["status"] == expected, result
                        return result["submissionId"]
                    await asyncio.sleep(0.5)
                raise RuntimeError("Judgement did not finish within 20 seconds")

            for role in ["admin", "player"]:
                await call("check_session", role=role)
            record("mcp_authentication_and_identity")
            now = datetime.now(UTC)
            game = await call(
                "admin_create_game",
                game={
                    "title": "MCP Live " + run_id,
                    "start": (now - timedelta(minutes=5)).isoformat(),
                    "end": (now + timedelta(hours=3)).isoformat(),
                    "hidden": False,
                    "acceptWithoutReview": True,
                    "writeupRequired": True,
                    "writeupDeadline": (now + timedelta(days=1)).isoformat(),
                },
            )
            game_id = game["id"]
            report["gameId"] = game_id
            record("create_game", gameId=game_id)
            before = await call("admin_list_challenges", game_id=game_id)
            flag = "flag{" + secrets.token_hex(16) + "}"
            attachment = workspace / f"attachment-{run_id}.txt"
            attachment.write_text("Local real attachment\n" + flag + "\n")
            manifest = {
                "challenge": {"title": "MCP Static " + run_id, "category": "Misc"},
                "configuration": {
                    "content": "Read the provided test attachment.",
                    "originalScore": 100,
                },
                "attachmentPath": attachment.name,
                "flags": [{"flag": flag}],
                "publish": True,
            }
            manifest_path = workspace / f"manifest-{run_id}.json"
            manifest_path.write_text(json.dumps(manifest))
            await call("admin_deploy_manifest_file", game_id=game_id, path=manifest_path.name)
            assert before == await call("admin_list_challenges", game_id=game_id)
            record("dry_run_has_no_remote_mutation")
            deployed = await call(
                "admin_deploy_manifest_file",
                game_id=game_id,
                path=manifest_path.name,
                dry_run=False,
            )
            assert deployed.get("completed"), deployed
            static_id = deployed["challengeId"]
            record("deploy_static_attachment_and_publish", challengeId=static_id)
            await call("list_games")
            await call("get_game", game_id=game_id)
            await call("list_teams")
            await call("join_check", game_id=game_id)
            await call("join_game", game_id=game_id, team_id=team_id)
            await call("list_challenges", game_id=game_id)
            detail = await call("get_challenge", game_id=game_id, challenge_id=static_id)
            record("join_and_read_participant_challenges")
            download = await call(
                "download_attachment",
                asset_path=detail["context"]["url"],
                filename=f"download-{run_id}.txt",
            )
            assert Path(download["path"]).read_bytes() == attachment.read_bytes()
            record("download_attachment_and_verify_content", sha256=download["sha256"])
            wrong_id = await verdict(static_id, "flag{incorrect}", "WrongAnswer")
            accepted_id = await verdict(static_id, flag, "Accepted")
            record(
                "real_async_judgement_wrong_and_correct",
                wrongSubmissionId=wrong_id,
                acceptedSubmissionId=accepted_id,
            )
            await call("scoreboard", game_id=game_id)
            await call("notices", game_id=game_id)
            record("scoreboard_and_notices")
            dynamic_flag = "flag{" + secrets.token_hex(16) + "}"
            dynamic_file = workspace / f"dynamic-{run_id}.txt"
            dynamic_file.write_text(dynamic_flag)
            uploaded = await call("admin_upload_file", path=dynamic_file.name)
            deployed = await call(
                "admin_deploy_challenge",
                game_id=game_id,
                dry_run=False,
                manifest={
                    "challenge": {
                        "title": "MCP Dynamic Attachment " + run_id,
                        "type": "DynamicAttachment",
                    },
                    "configuration": {"fileName": "dynamic.txt"},
                    "flags": [
                        {
                            "flag": dynamic_flag,
                            "attachmentType": "Local",
                            "fileHash": uploaded[0]["hash"],
                        }
                    ],
                    "publish": True,
                },
            )
            assert deployed.get("completed"), deployed
            dynamic_id = deployed["challengeId"]
            detail = await call("get_challenge", game_id=game_id, challenge_id=dynamic_id)
            result = await call(
                "download_attachment",
                asset_path=detail["context"]["url"],
                filename=f"dynamic-download-{run_id}.txt",
            )
            assert Path(result["path"]).read_text() == dynamic_flag
            await verdict(dynamic_id, dynamic_flag, "Accepted")
            record("dynamic_attachment_distribution_and_judgement", challengeId=dynamic_id)
            deployed = await call(
                "admin_deploy_challenge",
                game_id=game_id,
                dry_run=False,
                manifest={
                    "challenge": {
                        "title": "MCP Container " + run_id,
                        "category": "Web",
                        "type": "DynamicContainer",
                    },
                    "configuration": {
                        "containerImage": "gzctf-mcp-fixture:local",
                        "exposePort": 8000,
                        "memoryLimit": 64,
                        "storageLimit": 0,
                        "cpuCount": 1,
                        "networkMode": "Open",
                        "flagTemplate": "flag{[GUID]}",
                    },
                    "publish": True,
                },
            )
            assert deployed.get("completed"), deployed
            container_id = deployed["challengeId"]
            report["containerChallengeId"] = container_id
            for tool in ["admin_test_container", "container_action"]:
                started = await call(
                    tool, game_id=game_id, challenge_id=container_id, action="start"
                )
                entry = started["entry"]
                async with httpx.AsyncClient(trust_env=False, timeout=5) as challenge_http:
                    for attempt in range(30):
                        try:
                            response = await challenge_http.get(
                                entry if entry.startswith("http") else "http://" + entry
                            )
                            response.raise_for_status()
                            injected_flag = response.text
                            assert injected_flag.startswith("flag{"), "Flag injection missing"
                            break
                        except httpx.RequestError:
                            if attempt == 29:
                                raise
                            await asyncio.sleep(0.5)
                if tool == "container_action":
                    await verdict(container_id, injected_flag, "Accepted")
                # Upstream throttles consecutive operations on the same instance.
                await asyncio.sleep(11)
                await call(tool, game_id=game_id, challenge_id=container_id, action="stop")
                record(tool + "_start_flag_injection_and_stop", challengeId=container_id)
            wp = workspace / f"writeup-{run_id}.pdf"
            wp.write_bytes(pdf_bytes())
            await call("submit_writeup", game_id=game_id, path=wp.name)
            writeup = require(await player.get(f"/api/game/{game_id}/Writeup"), "read back writeup")
            assert writeup, "Writeup not persisted"
            report["writeupFields"] = sorted(writeup.keys())
            record("writeup_pdf_upload_and_readback")
            # Check authoring update/resume and actual delete APIs on a disposable disabled challenge.
            draft = await call(
                "admin_deploy_challenge",
                game_id=game_id,
                dry_run=False,
                manifest={
                    "challenge": {"title": "MCP Resume " + run_id},
                    "flags": [{"flag": "flag{draft}"}],
                },
            )
            assert draft.get("completed"), draft
            draft_id = draft["challengeId"]
            resumed = await call(
                "admin_deploy_challenge",
                game_id=game_id,
                challenge_id=draft_id,
                dry_run=False,
                manifest={
                    "challenge": {"title": "MCP Resume " + run_id},
                    "configuration": {"content": "Updated"},
                    "flags": [{"flag": "flag{draft}"}],
                },
            )
            assert resumed.get("completed"), resumed
            detail = await call("admin_get_challenge", game_id=game_id, challenge_id=draft_id)
            assert len(detail["flags"]) == 1 and detail["content"] == "Updated"
            await call(
                "admin_delete_flag",
                game_id=game_id,
                challenge_id=draft_id,
                flag_id=detail["flags"][0]["id"],
            )
            await call("admin_delete_challenge", game_id=game_id, challenge_id=draft_id)
            record("resume_no_duplicate_flags_and_delete_draft")
            report["completed"] = True
            report["finishedAt"] = datetime.now(UTC).isoformat()
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(
                f"LIVE ACCEPTANCE PASSED: {len(report['checks'])} checks, game {game_id}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(run())
