"""Command entry point shared by uvx, console scripts and python -m."""

import argparse
import os
from pathlib import Path

from . import __version__


def main():
    parser = argparse.ArgumentParser(description="GZCTF MCP server (stdio)")
    parser.add_argument("--version", action="version", version=f"gzctf-mcp {__version__}")
    parser.add_argument(
        "--transport", choices=["stdio"], default="stdio", help="MCP transport (default: stdio)"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Explicit .env file; existing environment variables take precedence",
    )
    args = parser.parse_args()
    if args.env_file is not None:
        if not args.env_file.is_file():
            parser.error("--env-file must point to an existing file")
        os.environ["GZCTF_ENV_FILE"] = str(args.env_file.resolve())
    # Help/version do not load the server or read credentials.
    from .server import create_server

    create_server().run(transport=args.transport)
