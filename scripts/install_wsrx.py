"""Explicitly install upstream wsrx CLI 0.6.2 with pinned official asset SHA256."""

import argparse
import hashlib
import io
import platform
import tarfile
import zipfile
from pathlib import Path

import httpx

VERSION = "0.6.2"
ASSETS = {
    "macos-aarch64": ("zip", "3b356991557dcb65342ff037aeb5fa9edc743038d39c2b1f921aebd2a3648177"),
    "macos-x86_64": ("zip", "7e128dfcccc72e97c8b961de2ea9d22ac0542ab5939635773732493ad6f3d735"),
    "linux-gnu-x86_64": (
        "tar.gz",
        "af96d3c32a9878511f322444b34eb6f5c28a349d5f74018de628f8d68b5cf042",
    ),
    "linux-musl-x86_64": (
        "tar.gz",
        "b439d9c777a06bd82cdc4fd7a8358afe2f5cdaac59ffbc8308b9a16c1b3582ad",
    ),
    "windows-msvc-x86_64": (
        "zip",
        "e136de8c489316610aa3a9a628a7c5c236513bdcd8b16aa6a58f20db4a165479",
    ),
}
ROOT = Path(__file__).resolve().parents[1]


def detect_target():
    machine = platform.machine().lower()
    arch = (
        "aarch64"
        if machine in ("arm64", "aarch64")
        else "x86_64"
        if machine in ("x86_64", "amd64")
        else machine
    )
    if platform.system() == "Darwin":
        return "macos-" + arch
    if platform.system() == "Windows":
        return "windows-msvc-" + arch
    libc = "musl" if platform.libc_ver()[0] == "musl" else "gnu"
    return f"linux-{libc}-{arch}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=ASSETS, default=detect_target())
    parser.add_argument("--directory", type=Path, default=ROOT / ".tools" / "wsrx" / VERSION)
    args = parser.parse_args()
    if args.target not in ASSETS:
        parser.error(
            "No pinned CLI asset for this platform; use cargo install wsrx --version 0.6.2 --locked"
        )
    extension, expected = ASSETS[args.target]
    asset = f"wsrx-cli-{VERSION}-{args.target}.{extension}"
    url = f"https://github.com/XDSEC/WebSocketReflectorX/releases/download/{VERSION}/{asset}"
    response = httpx.get(url, follow_redirects=True, timeout=90)
    response.raise_for_status()
    data = response.content
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit("Upstream archive SHA256 mismatch; nothing installed")
    name = "wsrx.exe" if args.target.startswith("windows") else "wsrx"
    if extension == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            matches = [
                entry
                for entry in archive.infolist()
                if Path(entry.filename).name == name and not entry.is_dir()
            ]
            if len(matches) != 1:
                raise SystemExit("Expected one CLI executable in upstream archive")
            binary = archive.read(matches[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            matches = [
                entry
                for entry in archive.getmembers()
                if entry.isfile() and Path(entry.name).name == name
            ]
            if len(matches) != 1:
                raise SystemExit("Expected one CLI executable in upstream archive")
            binary = archive.extractfile(matches[0]).read()
    directory = args.directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Keep the exact, hash-verified upstream archive, including any bundled notices.
    archive_copy = directory / asset
    if not archive_copy.exists():
        with archive_copy.open("xb") as output:
            output.write(data)
    elif hashlib.sha256(archive_copy.read_bytes()).hexdigest() != expected:
        raise SystemExit("Existing upstream archive differs; select another --directory")
    destination = directory / name
    if destination.exists():
        if destination.read_bytes() != binary:
            raise SystemExit("Existing executable differs; select another --directory")
    else:
        with destination.open("xb") as output:
            output.write(binary)
        destination.chmod(0o755)
    (directory / "WebSocketReflectorX-MIT.txt").write_bytes(
        (ROOT / "licenses" / "WebSocketReflectorX-MIT.txt").read_bytes()
    )
    (directory / "THIRD_PARTY_NOTICES.md").write_bytes(
        (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()
    )
    print(f"Installed verified upstream CLI {VERSION} ({args.target})")
    print(f"GZCTF_WSRX_BINARY={destination}")


if __name__ == "__main__":
    main()
