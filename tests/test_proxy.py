import asyncio
import json
import logging
import os
import sys
from uuid import UUID

import httpx
import pytest
import pytest_asyncio

from gzctf_mcp.client import Client, GZCTFError
from gzctf_mcp.config import Settings
from gzctf_mcp.proxy import ProxyManager
from gzctf_mcp.server import create_server


@pytest.fixture
def fake_cli(tmp_path):
    if os.name == "nt":
        pytest.skip(
            "Executable-script process fixture is POSIX only; run live acceptance with Windows CLI"
        )
    path = tmp_path / "wsrx"
    path.write_text(
        f"#!{sys.executable}\n"
        + """
import asyncio, json, os, sys
if '--version' in sys.argv:
    print('credentials-leaked' if os.getenv('GZCTF_ADMIN_COOKIE') else 'wsrx 0.6.2')
    raise SystemExit()
async def main():
    host = sys.argv[sys.argv.index('--host') + 1]
    port = int(sys.argv[sys.argv.index('--port') + 1])
    async def echo(r, w):
        try:
            while data := await r.read(1000):
                w.write(data)
                await w.drain()
        finally:
            w.close()
            await w.wait_closed()
    server = await asyncio.start_server(echo, host, port)
    address = server.sockets[0].getsockname()
    print(json.dumps({'fields': {'message': 'Hi, I am not RX, RX is here -> %s:%s' % address}}), flush=True)
    async with server:
        await server.serve_forever()
asyncio.run(main())
"""
    )
    path.chmod(0o755)
    return str(path)


@pytest_asyncio.fixture
async def proxy_harness(tmp_path):
    clients = []
    managers = []

    def make(binary="missing-gzctf-wsrx", mode="PlatformProxy", entry_override=None, maximum=8):
        settings = Settings(
            base_url="https://ctf.test",
            workspace=tmp_path,
            admin_cookie="admin=secret",
            player_cookie="player=secret",
            wsrx_binary=binary,
            max_tunnels=maximum,
        )
        requests = []

        def handler(request):
            requests.append(request)
            path = request.url.path
            if path == "/api/config":
                return httpx.Response(200, json={"portMapping": mode})
            if path.startswith("/api/proxy/"):
                return httpx.Response(204)
            if path.endswith("/Container") or "/Container/" in path:
                return httpx.Response(200)
            if request.method in ("PUT", "DELETE"):
                return httpx.Response(200)
            cid = int(path.split("/")[-1])
            entry = entry_override if entry_override is not None else str(UUID(int=cid))
            if "/edit/" in path:
                return httpx.Response(200, json={"testContainer": {"entry": entry}})
            return httpx.Response(200, json={"context": {"instanceEntry": entry}})

        api = Client(settings, transport=httpx.MockTransport(handler))
        manager = ProxyManager(api)
        clients.append(api)
        managers.append(manager)
        return manager, requests, api

    yield make
    for manager in managers:
        await manager.close()
    for client in clients:
        await client.close()


async def test_direct_mode_needs_no_cli(proxy_harness):
    manager, requests, _ = proxy_harness(mode="Default", entry_override="127.0.0.1:1337")
    result = await manager.open(1, 2, "player", 0)
    assert result["mode"] == "direct" and result["entry"] == "127.0.0.1:1337"
    assert manager.list() == []
    assert not any("/api/proxy/" in str(r.url) for r in requests)


async def test_missing_cli_has_install_instructions(proxy_harness):
    manager, _, _ = proxy_harness()
    with pytest.raises(GZCTFError, match="install_wsrx.py"):
        await manager.open(1, 2, "admin", 0)
    assert manager.list() == []


@pytest.mark.parametrize(
    ("mode", "entry", "message"),
    [
        ("PlatformProxy", "127.0.0.1:1234", "valid container UUID"),
        ("PlatformProxy", "", "No running container"),
        ("unknown", "anything", "Unknown platform"),
    ],
)
async def test_invalid_entry_or_mode_is_rejected(proxy_harness, mode, entry, message):
    manager, _, _ = proxy_harness(mode=mode, entry_override=entry)
    with pytest.raises(GZCTFError, match=message):
        await manager.open(1, 2, "player", 0)


async def test_real_process_reuse_port_and_environment_isolation(
    proxy_harness, fake_cli, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="httpx")
    monkeypatch.setenv("GZCTF_ADMIN_COOKIE", "must-not-inherit")
    manager, requests, _ = proxy_harness(binary=fake_cli)
    first, repeated = await asyncio.gather(
        manager.open(1, 2, "player", 0), manager.open(1, 2, "player", 0)
    )
    assert first["proxyId"] == repeated["proxyId"]
    assert repeated["reused"] and len(manager.list()) == 1
    assert first["localHost"] == "127.0.0.1"
    assert "secret" not in json.dumps(first) and str(UUID(int=2)) not in json.dumps(manager.list())
    reader, writer = await asyncio.open_connection(first["localHost"], first["localPort"])
    writer.write(b"round-trip")
    await writer.drain()
    assert await reader.readexactly(10) == b"round-trip"
    writer.close()
    await writer.wait_closed()
    assert requests[-1].url.path == "/api/proxy/" + str(UUID(int=2))
    assert str(UUID(int=2)) not in caplog.text
    await manager.close_one(first["proxyId"])
    assert manager.list() == []
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", first["localPort"])


async def test_admin_route_and_maximum(proxy_harness, fake_cli, monkeypatch):
    invocations = []
    original = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        invocations.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    manager, requests, _ = proxy_harness(binary=fake_cli, maximum=1)
    first = await manager.open(1, 2, "admin", 0)
    assert requests[-1].url.path == "/api/proxy/noinst/" + str(UUID(int=2))
    assert requests[-1].headers["cookie"] == "admin=secret"
    connection_args = next(args for args in invocations if "connect" in args)
    remote = connection_args[connection_args.index("connect") + 1]
    assert remote == "wss://ctf.test/api/proxy/noinst/" + str(UUID(int=2))
    assert "secret" not in json.dumps(invocations)
    with pytest.raises(GZCTFError, match="MAX_TUNNELS"):
        await manager.open(1, 3, "player", 0)
    await manager.close()
    assert manager.list() == []
    assert first["localPort"] > 0


async def test_port_collision_does_not_replace_existing_listener(proxy_harness, fake_cli):
    manager, _, _ = proxy_harness(binary=fake_cli)
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(GZCTFError, match="did not start"):
            await manager.open(1, 2, "player", port)
        assert manager.list() == []
        assert server.is_serving()
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize(
    ("role", "tool_name", "extra"),
    [
        ("player", "container_action", {"action": "stop"}),
        ("admin", "admin_test_container", {"action": "stop"}),
        ("admin", "admin_update_challenge", {"configuration": {"isEnabled": False}}),
        ("admin", "admin_delete_challenge", {}),
    ],
)
async def test_mcp_container_stop_cleans_managed_proxy(
    proxy_harness, fake_cli, role, tool_name, extra
):
    _, _, api = proxy_harness(binary=fake_cli)
    server = create_server(api.settings, api)

    def unpack(result):
        return result[1] if isinstance(result, tuple) else json.loads(result[0].text)

    async with server._mcp_server.lifespan(server._mcp_server):
        opened = unpack(
            await server.call_tool("proxy_open", {"game_id": 1, "challenge_id": 2, "role": role})
        )
        assert opened["localPort"] > 0
        await server.call_tool(tool_name, {"game_id": 1, "challenge_id": 2, **extra})
        assert unpack(await server.call_tool("proxy_list", {})) == {"proxies": []}
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", opened["localPort"])


async def test_only_owned_proxy_ids_can_be_closed(proxy_harness):
    manager, _, _ = proxy_harness()
    with pytest.raises(GZCTFError, match="not managed"):
        await manager.close_one("not-an-owned-process")


def test_proxy_configuration_limits(tmp_path):
    with pytest.raises(ValueError, match="MAX_TUNNELS"):
        Settings(workspace=tmp_path, max_tunnels=0)
    with pytest.raises(ValueError, match="MAX_TUNNELS"):
        Settings(workspace=tmp_path, max_tunnels=33)


async def test_force_killed_parent_does_not_leave_cli_listener(tmp_path, fake_cli):
    state = tmp_path / "owned-port.json"
    program = """
import asyncio, json, sys
from pathlib import Path
from uuid import UUID
import httpx
from gzctf_mcp.client import Client
from gzctf_mcp.config import Settings
from gzctf_mcp.proxy import ProxyManager
async def main():
    def handler(request):
        if request.url.path == '/api/config':
            return httpx.Response(200, json={'portMapping':'PlatformProxy'})
        if request.url.path.startswith('/api/proxy/'):
            return httpx.Response(204)
        return httpx.Response(200, json={'context':{'instanceEntry': str(UUID(int=2))}})
    api=Client(Settings(base_url='https://ctf.test', workspace=Path(sys.argv[2]).parent,
                        player_cookie='test', wsrx_binary=sys.argv[1]), transport=httpx.MockTransport(handler))
    manager=ProxyManager(api)
    result=await manager.open(1,2,'player',0)
    Path(sys.argv[2]).write_text(json.dumps(result))
    await asyncio.Event().wait()
asyncio.run(main())
"""
    parent = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        program,
        fake_cli,
        str(state),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if state.exists():
                break
            await asyncio.sleep(0.05)
        assert state.exists(), "Parent did not create its test tunnel"
        port = json.loads(state.read_text())["localPort"]
        parent.kill()
        await parent.wait()
        for _ in range(60):
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
            except OSError:
                break
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.05)
        else:
            pytest.fail("CLI listener survived the force-killed MCP parent")
    finally:
        if parent.returncode is None:
            parent.kill()
            await parent.wait()
