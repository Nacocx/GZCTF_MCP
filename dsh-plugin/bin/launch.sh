#!/bin/sh
# Launcher for the GZCTF MCP server, spawned by @deepseek-ai/dsh-mcp-client.
#
# The client starts this script over stdio; on the two native-Python paths the
# script replaces itself with the server process so the harness owns exactly one
# child (the uvx fallback keeps uvx as the parent). It resolves the repo from
# its own path, loads .env, and picks the first usable Python:
#
#   1. $GZCTF_MCP_PYTHON (explicit, validated)
#   2. <repo>/.conda/bin/python       (conda env from environment.yml)
#   3. python3 on PATH with gzctf-mcp importable
#   4. uvx --from <repo> gzctf-mcp    (installs dependencies on first run)
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

fail() {
    printf 'gzctf-mcp: %s\n' "$*" >&2
    exit 1
}

# Run from the checkout so a relative GZCTF_WORKSPACE and a relative
# GZCTF_ENV_FILE both resolve against the repository, not the harness cwd.
cd "$root"
env_file=${GZCTF_ENV_FILE:-$root/.env}

usable() {
    "$1" -c 'import gzctf_mcp, mcp' >/dev/null 2>&1
}

[ -f "$env_file" ] || fail "missing env file $env_file (copy .env.example to .env and fill in the site URL and cookies)"

python=
if [ -n "${GZCTF_MCP_PYTHON:-}" ]; then
    usable "$GZCTF_MCP_PYTHON" || fail "GZCTF_MCP_PYTHON=$GZCTF_MCP_PYTHON cannot import gzctf_mcp and mcp"
    python=$GZCTF_MCP_PYTHON
elif [ -x "$root/.conda/bin/python" ] && usable "$root/.conda/bin/python"; then
    python=$root/.conda/bin/python
elif command -v python3 >/dev/null 2>&1 && usable "$(command -v python3)"; then
    python=$(command -v python3)
fi

if [ -n "$python" ]; then
    exec "$python" -m gzctf_mcp --transport stdio --env-file "$env_file"
fi

command -v uvx >/dev/null 2>&1 ||
    fail "no Python with gzctf-mcp and mcp installed, and uvx is unavailable; create .conda or set GZCTF_MCP_PYTHON"
exec uvx --python 3.12 --from "$root" gzctf-mcp --transport stdio --env-file "$env_file"
