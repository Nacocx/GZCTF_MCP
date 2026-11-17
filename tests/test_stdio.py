import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_handshake_and_tools(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GZCTF_")}
    env["GZCTF_WORKSPACE"] = str(tmp_path)
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gzctf_mcp"],
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with (
        stdio_client(server) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "GZCTF MCP"
        tools = (await session.list_tools()).tools
        assert len(tools) == 73
        assert all(tool.annotations for tool in tools)
        result = await session.call_tool("connection_info", {})
        assert not result.isError
        assert result.structuredContent["playerConfigured"] is False
        result = await session.call_tool(
            "submit_flag", {"game_id": 1, "challenge_id": 2, "flag": "flag{test}"}
        )
        assert result.isError
        assert "GZCTF_PLAYER_COOKIE" in result.content[0].text
        result = await session.call_tool("get_challenge", {"game_id": -1, "challenge_id": 2})
        assert result.isError
        resources = await session.list_resources()
        assert str(resources.resources[0].uri) == "gzctf://workflow"
