"""Real MCP/GZCTF checks on the dedicated loopback Docker fixture.

The relay forwards to real GZCTF and can discard one selected response after the
server has processed it. It never fabricates API data. No external target option.
"""

import asyncio
import hashlib
import json
import os
import secrets
import sys
from contextlib import asynccontextmanager
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
IMAGE = "gzctf-mcp-fixture:verify-20261117"


class Relay:
    def __init__(self, upstream):
        self.upstream = upstream
        self.drop = None
        self.discarded = 0

    async def handle(self, reader, writer):
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
            lines = header.decode("latin1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            if not target.startswith("/") or target.startswith("//"):
                return
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.lower(): v.strip() for k, v in headers.items()}
            length = int(headers.get("content-length", "0"))
            if not 0 <= length <= 128 * 1024 * 1024 or "transfer-encoding" in headers:
                return
            body = await reader.readexactly(length)
            for name in ("host", "connection", "content-length", "accept-encoding"):
                headers.pop(name, None)
            response = await self.upstream.request(method, target, headers=headers, content=body)
            if self.drop and method == self.drop[0] and target.startswith(self.drop[1]):
                self.drop = None
                self.discarded += 1
                return
            outgoing = [
                (k, v)
                for k, v in response.headers.multi_items()
                if k.lower()
                not in {"content-encoding", "content-length", "transfer-encoding", "connection"}
            ]
            outgoing += [("Content-Length", str(len(response.content))), ("Connection", "close")]
            status = f"HTTP/1.1 {response.status_code} {response.reason_phrase}\r\n"
            writer.write(
                (status + "".join(f"{k}: {v}\r\n" for k, v in outgoing) + "\r\n").encode("latin1")
            )
            writer.write(response.content)
            await writer.drain()
        except (httpx.RequestError, asyncio.IncompleteReadError, OSError, ValueError, TimeoutError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()


async def run():
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    config = dotenv_values(ROOT / ".local-test/compose.env")
    run_id = datetime.now(UTC).strftime("%H%M%S") + secrets.token_hex(3)
    workspace = ROOT / ".local-test" / ("fixes-" + run_id)
    workspace.mkdir(mode=0o700)
    report_path = ROOT / ".local-test/api-fixes-live-20261117.json"
    report = {
        "origin": ORIGIN,
        "runId": run_id,
        "startedAt": datetime.now(UTC).isoformat(),
        "completed": False,
        "checks": [],
        "cleanup": [],
        "flagSubmissions": 0,
        "faultInjection": "Discard selected real HTTP responses after upstream completion",
    }

    def persist():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def passed(name, **details):
        report["checks"].append({"name": name, "passed": True, **details})
        persist()
        print("PASS " + name, flush=True)

    persist()
    username = "fix" + run_id
    bootstrap = Client(
        Settings(
            base_url=ORIGIN,
            workspace=workspace,
            admin_username="Admin",
            admin_password=config["ADMIN_PASSWORD"],
        )
    )
    try:
        await bootstrap.request(
            "public",
            "POST",
            "/api/account/Register",
            json={
                "userName": username,
                "email": username + "@example.invalid",
                "password": await bootstrap.encrypt(config["PLAYER_PASSWORD"]),
            },
        )
    finally:
        await bootstrap.close()

    async with httpx.AsyncClient(base_url=ORIGIN, trust_env=False, timeout=60) as upstream:
        relay = Relay(upstream)
        listener = await asyncio.start_server(relay.handle, "127.0.0.1", 0)
        proxy_origin = f"http://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GZCTF_")}
        env.update(
            GZCTF_BASE_URL=proxy_origin,
            GZCTF_WORKSPACE=str(workspace),
            GZCTF_ADMIN_USERNAME="Admin",
            GZCTF_ADMIN_PASSWORD=config["ADMIN_PASSWORD"],
            GZCTF_PLAYER_USERNAME=username,
            GZCTF_PLAYER_PASSWORD=config["PLAYER_PASSWORD"],
            GZCTF_TIMEOUT="60",
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "gzctf_mcp"], env=env, cwd=str(ROOT)
        )

        @asynccontextmanager
        async def connected():
            with (workspace / "mcp.stderr.log").open("a") as log:
                async with (
                    stdio_client(params, errlog=log) as (reader, writer),
                    ClientSession(reader, writer) as session,
                ):
                    await session.initialize()

                    async def call(name, **arguments):
                        result = await session.call_tool(name, arguments)
                        if result.isError:
                            raise RuntimeError(name + ": " + result.content[0].text)
                        return result.structuredContent or json.loads(result.content[0].text)

                    yield session, call

        game_id = team_id = None
        try:
            async with connected() as (session, call):
                assert len((await session.list_tools()).tools) == 73
                assert (await call("auth_requirements"))["config"]["apiPublicKey"]
                for role in ("admin", "player"):
                    await call("auth_login", role=role)
                    await call("check_session", role=role)
                passed("stdio_73_tools_encrypted_login")
                now = datetime.now(UTC)
                game = (
                    await call(
                        "admin_create_game",
                        game={
                            "title": "fixes " + run_id,
                            "start": (now - timedelta(hours=1)).isoformat(),
                            "end": (now + timedelta(days=1)).isoformat(),
                            "hidden": False,
                            "acceptWithoutReview": True,
                        },
                    )
                )["data"]
                game_id = game["id"]
                team_id = (await call("save_team", team={"name": "fix " + run_id}))["data"]["id"]
                payload = ("shared " + run_id).encode()
                digest = hashlib.sha256(payload).hexdigest()
                (workspace / "shared.bin").write_bytes(payload)
                answer = "flag{" + secrets.token_hex(16) + "}"

                def manifest(title, **extra):
                    return {
                        "challenge": {"title": title},
                        "flags": [{"flag": answer}],
                        "attachment": {"attachmentType": "Local", "fileHash": digest},
                        **extra,
                    }

                async def deploy_manifest(spec, **extra):
                    result = await call(
                        "admin_deploy_challenge",
                        game_id=game_id,
                        manifest=spec,
                        dry_run=False,
                        **extra,
                    )
                    assert result["completed"], "Deployment did not complete: " + result.get(
                        "error", "unknown"
                    )
                    return result["challengeId"]

                await call("admin_upload_file", path="shared.bin")
                first = await deploy_manifest(manifest("shared first"))
                rejected = await call(
                    "admin_deploy_challenge",
                    game_id=game_id,
                    manifest=manifest("unsafe reuse"),
                    dry_run=False,
                )
                assert not rejected["completed"] and rejected["challengeId"] is None
                await call("admin_upload_file", path="shared.bin")
                second = await deploy_manifest(manifest("shared second"))
                before = (await call("admin_files", count=100))["data"]
                await deploy_manifest(manifest("shared second"), challenge_id=second)
                assert before == (await call("admin_files", count=100))["data"]
                await call("admin_delete_challenge", game_id=game_id, challenge_id=first)
                downloaded = await call(
                    "download_attachment",
                    asset_path=f"/assets/{digest}/fresh-{run_id}",
                    filename="shared-check.bin",
                )
                assert Path(downloaded["path"]).read_bytes() == payload
                passed("shared_hash_reference_guard_resume_and_surviving_download")

                relay.drop = ("GET", f"/assets/{digest}/verify-")
                lost_manifest = {
                    "challenge": {"title": "readback loss"},
                    "attachmentPath": "shared.bin",
                }
                lost = await call(
                    "admin_deploy_challenge", game_id=game_id, manifest=lost_manifest, dry_run=False
                )
                assert (
                    not lost["completed"] and lost["stage"] == "attachment" and lost["challengeId"]
                )
                await deploy_manifest(lost_manifest, challenge_id=lost["challengeId"])
                passed("real_attachment_readback_response_loss_keeps_recovery_id")

                await asyncio.gather(
                    call(
                        "admin_update_game", game_id=game_id, patch={"title": "updated " + run_id}
                    ),
                    call(
                        "admin_update_game", game_id=game_id, patch={"summary": "concurrent change"}
                    ),
                )
                current = (await call("admin_get_game", game_id=game_id))["data"]
                assert (
                    current["title"] == "updated " + run_id
                    and current["summary"] == "concurrent change"
                )
                passed("concurrent_game_updates_preserve_both_fields")
                await call(
                    "admin_update_challenge",
                    game_id=game_id,
                    challenge_id=second,
                    configuration={"isEnabled": True},
                )
                assert (await call("join_game", game_id=game_id, team_id=team_id))["accepted"]

                async def verdict(cid, value, expected):
                    submission = await call(
                        "submit_flag", game_id=game_id, challenge_id=cid, flag=value
                    )
                    report["flagSubmissions"] += 1
                    for _ in range(40):
                        status = await call(
                            "submission_status",
                            game_id=game_id,
                            challenge_id=cid,
                            submission_id=submission["submissionId"],
                        )
                        if not status["pending"]:
                            assert status["status"] == expected
                            return
                        await asyncio.sleep(0.5)
                    raise RuntimeError("Judgement did not finish")

                await verdict(second, "flag{known-incorrect-local-fixture}", "WrongAnswer")
                await verdict(second, answer, "Accepted")
                await call("scoreboard", game_id=game_id)
                passed("encrypted_flag_submission_wrong_and_accepted_verdicts")

                cid = await deploy_manifest(
                    {
                        "challenge": {"title": "container fixture", "type": "DynamicContainer"},
                        "configuration": {
                            "containerImage": IMAGE,
                            "exposePort": 8000,
                            "memoryLimit": 64,
                            "cpuCount": 1,
                            "networkMode": "Open",
                            "flagTemplate": "flag{[GUID]}",
                        },
                        "publish": True,
                    }
                )
                for tool in ("admin_test_container", "container_action"):
                    container = (
                        await call(tool, game_id=game_id, challenge_id=cid, action="start")
                    )["data"]
                    entry = container["entry"]
                    # The local fixture's PublicEntry is fixed to the host loopback.
                    assert entry.startswith("127.0.0.1:")
                    async with httpx.AsyncClient(trust_env=False, timeout=5) as http:
                        for attempt in range(30):
                            try:
                                response = await http.get("http://" + entry)
                                response.raise_for_status()
                                assert response.text.startswith("flag{")
                                if tool == "container_action":
                                    await verdict(cid, response.text, "Accepted")
                                break
                            except httpx.RequestError:
                                if attempt == 29:
                                    raise
                                await asyncio.sleep(0.5)
                    await asyncio.sleep(11)  # GZCTF instance-operation cooldown.
                    await call(tool, game_id=game_id, challenge_id=cid, action="stop")
                    passed(tool + "_real_container_connect_inject_stop")

                cleanup_plan = {
                    "items": [
                        {"key": str(i), "manifest": {"challenge": {"title": f"cleanup-{i}"}}}
                        for i in range(2)
                    ]
                }
                (workspace / "cleanup.json").write_text(json.dumps(cleanup_plan))
                cleanup_args = {
                    "game_id": game_id,
                    "plan_file": "cleanup.json",
                    "state_name": "cleanup",
                }
                batch = await call("admin_deploy_batch", **cleanup_args, dry_run=False)
                assert batch["completed"]
                cleanup_id = batch["items"]["0"]["challengeId"]
                relay.drop = ("DELETE", f"/api/edit/Games/{game_id}/Challenges/{cleanup_id}")
                try:
                    await call("admin_cleanup_batch", state_name="cleanup", dry_run=False)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Expected lost delete response")
                assert (await call("admin_batch_status", state_name="cleanup"))["items"]["0"][
                    "stage"
                ] == "deleting"
                assert (await call("admin_cleanup_batch", state_name="cleanup", dry_run=False))[
                    "completed"
                ]
                passed("real_delete_response_loss_recovers_and_continues_batch")

                restart_plan = {
                    "items": [
                        {
                            "key": "dynamic",
                            "manifest": {
                                "challenge": {
                                    "title": "restart dynamic",
                                    "type": "DynamicAttachment",
                                },
                                "configuration": {"fileName": "shared.bin"},
                                "flags": [
                                    {
                                        "flag": "flag{restart-" + str(i) + "}",
                                        "attachmentType": "Local",
                                        "attachmentPath": "shared.bin",
                                    }
                                    for i in range(2)
                                ],
                            },
                        }
                    ]
                }
                (workspace / "restart.json").write_text(json.dumps(restart_plan))
                restart_args = {
                    "game_id": game_id,
                    "plan_file": "restart.json",
                    "state_name": "restart",
                }
                # Drop only the append response, after GZCTF actually stores both flags.
                shell = (
                    await call(
                        "admin_create_challenge",
                        game_id=game_id,
                        challenge={"title": "restart dynamic", "type": "DynamicAttachment"},
                    )
                )["data"]
                restart_plan["items"][0]["challengeId"] = shell["id"]
                (workspace / "restart.json").write_text(json.dumps(restart_plan))
                relay.drop = ("POST", f"/api/edit/Games/{game_id}/Challenges/{shell['id']}/Flags")
                assert not (await call("admin_deploy_batch", **restart_args, dry_run=False))[
                    "completed"
                ]
                file_inventory = (await call("admin_files", count=100))["data"]

            async with connected() as (_, call):
                resumed = await call("admin_deploy_batch", **restart_args, dry_run=False)
                assert resumed["completed"]
                assert (await call("admin_files", count=100))["data"] == file_inventory
                refs = (await call("admin_batch_status", state_name="restart"))["items"]["dynamic"][
                    "uploadReferences"
                ]
                assert len(refs) == 2 and all(v["state"] == "bound" for v in refs.values())
                passed("real_stdio_restart_preserves_dynamic_upload_references")
                await call("admin_cleanup_batch", state_name="restart", dry_run=False)
                report["completed"] = True
        except Exception as error:
            report["failureType"] = type(error).__name__
            raise
        finally:
            async with connected() as (_, call):
                for tool, args in [
                    ("admin_delete_game", {"game_id": game_id}),
                    ("team_action", {"team_id": team_id, "action": "delete"}),
                ]:
                    if any(v is None for v in args.values()):
                        continue
                    try:
                        await call(tool, **args)
                        report["cleanup"].append({"tool": tool, "deleted": True})
                    except RuntimeError:
                        report["cleanup"].append({"tool": tool, "deleted": False})
            report["discardedResponses"] = relay.discarded
            report["finishedAt"] = datetime.now(UTC).isoformat()
            persist()
            listener.close()
            await listener.wait_closed()
        assert report["cleanup"] and all(item["deleted"] for item in report["cleanup"])
    print("LIVE API FIXES ACCEPTANCE PASSED", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
