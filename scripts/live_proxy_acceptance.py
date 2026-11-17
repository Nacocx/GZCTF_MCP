"""Real MCP -> upstream wsrx CLI -> local GZCTF PlatformProxy -> Docker HTTP fixture.

Local only (18081); does not submit any flag or contact the user's deployed site.
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
ORIGIN = "http://127.0.0.1:18081"


async def assert_port_closed(port):
    for _ in range(40):
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.1)
    raise RuntimeError("Managed local listener is still alive")


async def assert_fixture_http(local_address):
    # The platform may return a running container before its Python HTTP server
    # has bound its port. Retry only this read-only fixture GET, never a submission.
    async with httpx.AsyncClient(trust_env=False, timeout=5) as connection:
        for attempt in range(40):
            try:
                response = await connection.get("http://" + local_address)
            except httpx.RequestError:
                if attempt == 39:
                    raise RuntimeError("Fixture HTTP service did not become reachable") from None
                await asyncio.sleep(0.2)
                continue
            assert response.status_code == 200 and response.text.startswith("flag{")
            return


async def run():
    config = dotenv_values(ROOT / ".local-test/compose.env")
    identifier = datetime.now(UTC).strftime("%H%M%S") + secrets.token_hex(3)
    work = ROOT / ".local-test" / ("proxy-" + identifier)
    work.mkdir(parents=True)
    binary = Path(os.environ.get("GZCTF_WSRX_BINARY", ROOT / ".tools/wsrx/0.6.2/wsrx")).resolve()
    report = {
        "origin": ORIGIN,
        "startedAt": datetime.now(UTC).isoformat(),
        "wsrxVersion": "0.6.2",
        "platformVersion": "1.9.0.0",
        "portMapping": "PlatformProxy",
        "transport": "real MCP stdio -> upstream wsrx CLI -> GZCTF WebSocket -> Docker HTTP",
        "checks": [],
        "answerSubmissions": 0,
        "completed": False,
        "cleanup": {},
    }
    game_id = None
    challenge_id = None
    player_running = False
    admin_running = False
    player_started = 0

    def record(name):
        report["checks"].append({"name": name, "passed": True})
        (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("PASS " + name, flush=True)

    async with (
        httpx.AsyncClient(base_url=ORIGIN, trust_env=False, timeout=40) as admin,
        httpx.AsyncClient(base_url=ORIGIN, trust_env=False, timeout=40) as player,
    ):

        async def api(client, method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            if response.status_code >= 300:
                raise RuntimeError(f"{method} local fixture: HTTP {response.status_code}")
            return response.json() if response.content else None

        try:
            await api(
                admin,
                "POST",
                "/api/account/LogIn",
                json={"userName": "Admin", "password": config["ADMIN_PASSWORD"]},
            )
            await api(
                player,
                "POST",
                "/api/account/Register",
                json={
                    "userName": "mcp" + identifier,
                    "email": identifier + "@example.invalid",
                    "password": config["PLAYER_PASSWORD"],
                },
            )
            team = await api(player, "POST", "/api/team", json={"name": "Proxy " + identifier})

            def cookie(client):
                return "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)

            env = {k: v for k, v in os.environ.items() if not k.startswith("GZCTF_")}
            env.update(
                GZCTF_BASE_URL=ORIGIN,
                GZCTF_WORKSPACE=str(work),
                GZCTF_ADMIN_COOKIE=cookie(admin),
                GZCTF_PLAYER_COOKIE=cookie(player),
                GZCTF_WSRX_BINARY=str(binary),
                NO_PROXY="localhost,127.0.0.1",
                no_proxy="localhost,127.0.0.1",
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
                    if name == "submit_flag":
                        raise RuntimeError("Answer submissions are outside this test scope")
                    result = await session.call_tool(name, arguments)
                    if result.isError:
                        raise RuntimeError(f"{name} returned a tool error")
                    data = result.structuredContent
                    return data.get("data") if set(data) == {"data"} else data

                assert (await call("platform_config", role="admin"))[
                    "portMapping"
                ] == "PlatformProxy"
                record("platform_proxy_configuration_detected")
                now = datetime.now(UTC)
                game = await call(
                    "admin_create_game",
                    game={
                        "title": "Proxy MCP " + identifier,
                        "hidden": False,
                        "start": (now - timedelta(minutes=2)).isoformat(),
                        "end": (now + timedelta(hours=1)).isoformat(),
                        "acceptWithoutReview": True,
                    },
                )
                game_id = game["id"]
                deployed = await call(
                    "admin_deploy_challenge",
                    game_id=game_id,
                    dry_run=False,
                    manifest={
                        "challenge": {
                            "title": "Proxy fixture " + identifier,
                            "category": "Web",
                            "type": "DynamicContainer",
                        },
                        "configuration": {
                            "containerImage": "gzctf-mcp-fixture:local",
                            "exposePort": 8000,
                            "memoryLimit": 64,
                            "cpuCount": 1,
                            "storageLimit": 0,
                            "networkMode": "Open",
                            "flagTemplate": "flag{[GUID]}",
                        },
                        "publish": True,
                    },
                )
                assert deployed["completed"]
                challenge_id = deployed["challengeId"]
                report.update(gameId=game_id, challengeId=challenge_id)
                await call(
                    "admin_test_container",
                    game_id=game_id,
                    challenge_id=challenge_id,
                    action="start",
                )
                admin_running = True
                first = await call(
                    "proxy_open", game_id=game_id, challenge_id=challenge_id, role="admin"
                )
                await assert_fixture_http(first["localAddress"])
                record("admin_test_instance_http_via_wsrx_websocket")
                again = await call(
                    "proxy_open", game_id=game_id, challenge_id=challenge_id, role="admin"
                )
                assert again["reused"] and again["proxyId"] == first["proxyId"]
                record("same_instance_proxy_reused")
                await call("proxy_close", proxy_id=first["proxyId"])
                await assert_port_closed(first["localPort"])
                assert (
                    await call("admin_get_challenge", game_id=game_id, challenge_id=challenge_id)
                )["testContainer"] is not None
                record("explicit_proxy_close_releases_port_and_keeps_container")
                admin_proxy = await call(
                    "proxy_open", game_id=game_id, challenge_id=challenge_id, role="admin"
                )
                await call("join_game", game_id=game_id, team_id=team["id"])
                await call(
                    "container_action", game_id=game_id, challenge_id=challenge_id, action="start"
                )
                player_running = True
                player_started = asyncio.get_running_loop().time()
                player_proxy = await call(
                    "proxy_open", game_id=game_id, challenge_id=challenge_id, role="player"
                )
                await assert_fixture_http(player_proxy["localAddress"])
                record("player_instance_http_via_wsrx_websocket_without_answer_submission")
                listing = await call("proxy_list")
                assert len(listing["proxies"]) == 2
                assert all(
                    "remote" not in tunnel and "instance" not in tunnel
                    for tunnel in listing["proxies"]
                )
                record("independent_admin_player_tunnels_listed")
                await asyncio.sleep(
                    max(0, 11 - (asyncio.get_running_loop().time() - player_started))
                )
                await call(
                    "container_action", game_id=game_id, challenge_id=challenge_id, action="stop"
                )
                player_running = False
                await assert_port_closed(player_proxy["localPort"])
                assert len((await call("proxy_list"))["proxies"]) == 1
                record("container_stop_automatically_closes_player_proxy")
            await assert_port_closed(admin_proxy["localPort"])
            record("mcp_exit_automatically_closes_remaining_proxy")
        finally:
            if challenge_id is not None:
                if player_running:
                    await asyncio.sleep(
                        max(0, 11 - (asyncio.get_running_loop().time() - player_started))
                    )
                    await api(player, "DELETE", f"/api/game/{game_id}/Container/{challenge_id}")
                if admin_running:
                    await api(
                        admin,
                        "DELETE",
                        f"/api/edit/Games/{game_id}/Challenges/{challenge_id}/Container",
                    )
            if game_id is not None:
                await api(admin, "DELETE", f"/api/edit/Games/{game_id}")
                check = await admin.get(f"/api/edit/Games/{game_id}")
                assert check.status_code == 404
                report["cleanup"]["testGameAbsent"] = True
            (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    report["completed"] = True
    report["finishedAt"] = datetime.now(UTC).isoformat()
    report["wsrxBinarySha256"] = __import__("hashlib").sha256(binary.read_bytes()).hexdigest()
    report_path = ROOT / "docs/records/wsrx-live-2026-10-21.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"LIVE PLATFORM PROXY PASSED: {len(report['checks'])} checks; no answer submissions.",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(run())
