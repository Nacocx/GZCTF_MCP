"""Generate local-only Docker fixture secrets without printing them."""

from pathlib import Path
from secrets import token_urlsafe

root = Path(__file__).resolve().parents[1]
folder = root / ".local-test"
folder.mkdir(mode=0o700, exist_ok=True)
path = folder / "compose.env"
if not path.exists():
    values = {
        name: "Mcp1-" + token_urlsafe(24)
        for name in ("DB_PASSWORD", "XOR_KEY", "ADMIN_PASSWORD", "PLAYER_PASSWORD")
    }
    with path.open("x") as file:
        file.write("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)
print("Local fixture configuration is ready (.local-test/compose.env).")
