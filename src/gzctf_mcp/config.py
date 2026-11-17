import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def default_wsrx_binary():
    source_root = Path(__file__).resolve().parents[2]
    name = "wsrx.exe" if os.name == "nt" else "wsrx"
    local = source_root / ".tools" / "wsrx" / "0.6.2" / name
    if (source_root / "pyproject.toml").is_file() and local.is_file():
        return str(local)
    return "wsrx"


@dataclass
class Settings:
    base_url: str = "http://localhost:8080"
    workspace: Path = field(default_factory=Path.cwd)
    admin_cookie: str = field(default="", repr=False)
    player_cookie: str = field(default="", repr=False)
    admin_username: str = field(default="", repr=False)
    admin_password: str = field(default="", repr=False)
    player_username: str = field(default="", repr=False)
    player_password: str = field(default="", repr=False)
    wsrx_binary: str = field(default_factory=default_wsrx_binary)
    max_tunnels: int = 8
    timeout: float = 30
    max_file_bytes: int = 100 * 1024 * 1024

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError(
                "GZCTF_BASE_URL must be an HTTP(S) origin, without path or credentials"
            )
        if self.timeout <= 0 or self.max_file_bytes <= 0:
            raise ValueError("Timeout and file size limit must be positive")
        if not 1 <= self.max_tunnels <= 32:
            raise ValueError("GZCTF_MAX_TUNNELS must be between 1 and 32")
        self.base_url = self.base_url.rstrip("/")
        self.workspace = self.workspace.expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("GZCTF_WORKSPACE must be a directory")

    @classmethod
    def from_env(cls):
        # Explicit path prevents accidental discovery of a parent project's secrets.
        if path := os.getenv("GZCTF_ENV_FILE"):
            load_dotenv(path, override=False)
        return cls(
            base_url=os.getenv("GZCTF_BASE_URL", "http://localhost:8080"),
            workspace=Path(os.getenv("GZCTF_WORKSPACE", ".")),
            admin_cookie=os.getenv("GZCTF_ADMIN_COOKIE", ""),
            player_cookie=os.getenv("GZCTF_PLAYER_COOKIE", ""),
            admin_username=os.getenv("GZCTF_ADMIN_USERNAME", ""),
            admin_password=os.getenv("GZCTF_ADMIN_PASSWORD", ""),
            player_username=os.getenv("GZCTF_PLAYER_USERNAME", ""),
            player_password=os.getenv("GZCTF_PLAYER_PASSWORD", ""),
            wsrx_binary=os.getenv("GZCTF_WSRX_BINARY") or default_wsrx_binary(),
            max_tunnels=int(os.getenv("GZCTF_MAX_TUNNELS", "8")),
            timeout=float(os.getenv("GZCTF_TIMEOUT", "30")),
            max_file_bytes=int(os.getenv("GZCTF_MAX_FILE_BYTES", str(100 * 1024 * 1024))),
        )
