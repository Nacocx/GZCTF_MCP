"""Record reproducible textual source-overlap evidence, not a license verdict.

Only compares project code/fixtures against tracked, non-restricted GZCTF source.
Does not read .env, local acceptance outputs, or restricted component bodies.
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".cs", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml"}
RESTRICTED = [
    "src/GZCTF/Services/Container/Manager/",
    "src/GZCTF/ClientApp/src/hooks/useConfig.ts",
    "src/GZCTF/ClientApp/src/components/Copyright.tsx",
]


def git(directory, *arguments):
    return subprocess.check_output(["git", "-C", str(directory), *arguments]).decode()


def restricted(path):
    return any(path.startswith(rule) if rule.endswith("/") else path == rule for rule in RESTRICTED)


def normalized_lines(text):
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        # Keep identifiers and punctuation. Ignore only whitespace and line comments.
        line = line.strip()
        if line.startswith(("#", "//", "/*", "*", "<!--")):
            continue
        normalized = re.sub(r"\s+", "", line)
        if len(normalized) >= 12:
            result.append((number, normalized))
    return result


def windows(text):
    lines = normalized_lines(text)
    for offset in range(max(0, len(lines) - 2)):
        group = lines[offset : offset + 3]
        if sum(len(value) for _, value in group) >= 90:
            yield tuple(value for _, value in group), (group[0][0], group[-1][0])


def audit(upstream):
    tracked = git(upstream, "ls-files", "-z").split("\0")
    bodies, excluded = {}, []
    exact, triples = defaultdict(list), defaultdict(list)
    for name in filter(None, tracked):
        path = upstream / name
        if restricted(name):
            excluded.append(name)
            continue
        if (
            path.suffix not in SOURCE_SUFFIXES
            or not path.is_file()
            or path.stat().st_size > 2_000_000
        ):
            continue
        data = path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        bodies[name] = text
        exact[hashlib.sha256(data).hexdigest()].append(name)
        for key, position in windows(text):
            triples[key].append({"path": name, "lines": list(position)})
    inventory = []
    for root in ("src", "scripts", "tests", "deploy", "examples", "licenses"):
        for path in sorted((ROOT / root).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            item = {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": digest,
                "exactUpstreamFiles": exact.get(digest, []),
                "matchingBlocks": [],
                "longStringMatches": [],
            }
            if path.suffix in SOURCE_SUFFIXES:
                text = data.decode("utf-8-sig")
                for key, position in windows(text):
                    if key in triples:
                        item["matchingBlocks"].append(
                            {"localLines": list(position), "upstream": triples[key]}
                        )
                if path.suffix == ".py":
                    # Long literals are candidates only, often MIME types/URLs/test data.
                    strings = {
                        node.value
                        for node in ast.walk(ast.parse(text))
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and len(node.value) >= 40
                    }
                    for value in sorted(strings):
                        matches = [name for name, body in bodies.items() if value in body]
                        if matches:
                            item["longStringMatches"].append(
                                {
                                    "sha256": hashlib.sha256(value.encode()).hexdigest(),
                                    "characters": len(value),
                                    "upstream": matches,
                                }
                            )
            inventory.append(item)
    return {
        "date": "2026-10-23",
        "packageVersion": "0.3.1",
        "upstreamCommit": git(upstream, "rev-parse", "HEAD").strip(),
        "upstreamDirty": bool(git(upstream, "status", "--porcelain")),
        "method": {
            "minComparableLineCharacters": 12,
            "consecutiveRetainedLines": 3,
            "minBlockCharacters": 90,
            "minPythonStringCharacters": 40,
            "warning": "No overlap does not exclude cross-language adaptation; manual review required",
        },
        "upstreamComparedFiles": len(bodies),
        "restrictedPathsNotRead": sorted(excluded),
        "files": inventory,
        "totals": {
            "reviewedFiles": len(inventory),
            "exactMatchingFiles": sum(bool(x["exactUpstreamFiles"]) for x in inventory),
            "filesWithMatchingBlocks": sum(bool(x["matchingBlocks"]) for x in inventory),
            "filesWithLongStringMatches": sum(bool(x["longStringMatches"]) for x in inventory),
        },
        "licenseFiles": {
            name: hashlib.sha256((upstream / name).read_bytes()).hexdigest()
            for name in (
                "LICENSE.txt",
                "LICENSE_ADDENDUM.txt",
                "NOTICE",
                "PROPRIETARY_COMPONENTS.md",
                "TRADEMARKS.md",
                "license/LicenseRef-GZCTF-Restricted.txt",
            )
        },
    }


def check_artifact(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            files = {
                name: archive.read(name) for name in archive.namelist() if not name.endswith("/")
            }
    else:
        with tarfile.open(path) as archive:
            files = {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            }
    bad = []
    for name in files:
        parts = Path(name).parts
        if (
            any(
                part in {"GZCTF", ".conda", ".local-test", ".tools", ".mcp-state"} for part in parts
            )
            or Path(name).name == ".env"
            or Path(name).suffix.lower() in {".cs", ".tsx", ".dll", ".exe", ".so", ".dylib"}
        ):
            bad.append(name)
    source_status = []
    for source in sorted((ROOT / "src/gzctf_mcp").glob("*.py")):
        suffix = "gzctf_mcp/" + source.name
        matches = [name for name in files if name.endswith(suffix)]
        source_status.append(
            {
                "path": suffix,
                "included": len(matches) == 1,
                "matchesWorkingTree": len(matches) == 1
                and files[matches[0]] == source.read_bytes(),
            }
        )
    return {
        "name": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "files": len(files),
        "forbiddenEntries": bad,
        "sourceFiles": source_status,
        "wsrxLicenseIncluded": any(name.endswith("WebSocketReflectorX-MIT.txt") for name in files),
        "wsrxBinaryIncluded": any(Path(name).name in {"wsrx", "wsrx.exe"} for name in files),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT / "GZCTF")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/records/source-origin-2026-10-23.json"
    )
    parser.add_argument("--artifact", action="append", type=Path, default=[])
    args = parser.parse_args()
    result = audit(args.upstream.resolve(strict=True))
    result["artifacts"] = [check_artifact(path) for path in args.artifact]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["totals"]))
    for item in result["files"]:
        if item["exactUpstreamFiles"] or item["matchingBlocks"] or item["longStringMatches"]:
            print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
