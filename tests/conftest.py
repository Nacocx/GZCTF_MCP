import httpx
import pytest
import pytest_asyncio

from gzctf_mcp.client import Client
from gzctf_mcp.config import Settings
from gzctf_mcp.server import create_server


@pytest.fixture
def settings(tmp_path):
    return Settings(
        base_url="https://ctf.test",
        workspace=tmp_path,
        admin_cookie="admin-session=secret-a",
        player_cookie="player-session=secret-p",
    )


@pytest_asyncio.fixture
async def harness(settings):
    clients = []

    def make(handler):
        client = Client(settings, transport=httpx.MockTransport(handler))
        clients.append(client)
        return create_server(settings, client), client

    yield make
    for client in clients:
        await client.close()
