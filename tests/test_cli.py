import subprocess
import sys


def test_cli_help_version_and_transport_validation():
    for args, expected in [(["--help"], "--transport"), (["--version"], "gzctf-mcp 0.3.1")]:
        result = subprocess.run(
            [sys.executable, "-m", "gzctf_mcp", *args], capture_output=True, text=True, check=True
        )
        assert expected in result.stdout and not result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "gzctf_mcp", "--transport", "http"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and not result.stdout


def test_cli_missing_env_file_is_stderr_error(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "gzctf_mcp", "--env-file", str(tmp_path / "absent")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and not result.stdout
    assert "existing file" in result.stderr
