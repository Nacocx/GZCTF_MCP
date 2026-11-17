"""Exercise real uvx installs without contacting any GZCTF platform."""

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def check(source):
    executable = shutil.which("uvx")
    if not executable:
        raise RuntimeError("Install uv before running the uvx acceptance check")
    with tempfile.TemporaryDirectory(prefix="gzctf-uvx-") as temporary:
        workspace = Path(temporary)
        config = workspace / "test.env"
        # Deliberately fake origin and no credentials: no platform requests are needed.
        config.write_text(f"GZCTF_BASE_URL=https://ctf.invalid\nGZCTF_WORKSPACE={workspace}\n")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GZCTF_", "CONDA_"))
            and key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
        }
        parameters = StdioServerParameters(
            command=executable,
            args=[
                "--python",
                "3.12",
                "--refresh-package",
                "gzctf-mcp",
                "--from",
                str(source),
                "gzctf-mcp",
                "--transport",
                "stdio",
                "--env-file",
                str(config),
            ],
            cwd=str(workspace),
            env=env,
        )
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert len(tools) == 73
            result = await session.call_tool("connection_info", {})
            assert not result.isError
            info = result.structuredContent
            assert info["baseUrl"] == "https://ctf.invalid"
            assert info["workspace"] == str(workspace.resolve())
            assert not info["adminConfigured"] and not info["playerConfigured"]
            missing = await session.call_tool("list_teams", {})
            assert missing.isError and "GZCTF_PLAYER_COOKIE" in missing.content[0].text
            resources = (await session.list_resources()).resources
            assert str(resources[0].uri) == "gzctf://workflow"
        return {
            "source": str(source),
            "tools": len(tools),
            "passed": True,
            "transport": "stdio",
            "platformRequests": 0,
            "checks": [
                "initialize",
                "tools/list",
                "connection_info",
                "explicit_env_file",
                "workspace_outside_source",
                "missing_auth_isError",
                "resources/list",
            ],
        }


async def run(sources):
    report = {"checks": [], "completed": False}
    path = ROOT / ".local-test/uvx-report.json"
    path.parent.mkdir(exist_ok=True)
    for source in sources:
        result = await check(source.resolve(strict=True))
        report["checks"].append(result)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"PASS uvx stdio: {source} ({result['tools']} tools)", flush=True)
    report["completed"] = True
    path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, required=True)
    asyncio.run(run(parser.parse_args().source))
