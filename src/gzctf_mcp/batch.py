"""Sequential deployments with a durable, secret-free progress ledger.

The lock intentionally remains after a process crash: inspect upstream state before
removing it. An uncertain create/upload must be explicitly reconciled, never replayed.
"""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from typing import Any

from pydantic import Field

from .client import GZCTFError
from .models import ChallengeManifest, Id, Model
from .workflow import challenge_path, deploy


class BatchItem(Model):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    manifest: ChallengeManifest
    challenge_id: Id | None = None


class BatchPlan(Model):
    items: list[BatchItem] = Field(min_length=1, max_length=100)


def state_path(api, name):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise GZCTFError("State name must be a simple identifier")
    root = api.settings.workspace / ".mcp-state"
    root.mkdir(mode=0o700, exist_ok=True)
    if not root.resolve().is_relative_to(api.settings.workspace):
        raise GZCTFError("State directory must remain inside workspace")
    path = root / (name + ".json")
    if path.is_symlink():
        raise GZCTFError("State file cannot be a symlink")
    return path


def save(path, value):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(path):
    lock = path.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise GZCTFError(
            "Batch locked. If the process crashed, inspect remote state before removing .lock"
        ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def load_plan(api, file):
    raw = api.local_file(file).read_bytes()
    plan = BatchPlan.model_validate_json(raw)
    if len({i.key for i in plan.items}) != len(plan.items):
        raise GZCTFError("Batch keys must be unique")
    if len({i.manifest.challenge.title for i in plan.items}) != len(plan.items):
        raise GZCTFError("Batch titles must be unique")
    digest = hashlib.sha256(raw)
    for item in plan.items:
        paths = [item.manifest.attachment_path] + [f.attachment_path for f in item.manifest.flags]
        for path in filter(None, paths):
            digest.update(hashlib.sha256(api.local_file(path).read_bytes()).digest())
    return plan, digest.hexdigest()


async def batch_deploy(api, game_id, plan_file, name, dry_run=True):
    plan, fingerprint = load_plan(api, plan_file)
    path = state_path(api, name)
    identity = {
        "origin": api.settings.base_url,
        "gameId": game_id,
        "workspace": str(api.settings.workspace),
        "fingerprint": fingerprint,
    }
    if dry_run:
        return {
            "dryRun": True,
            **identity,
            "statePath": str(path),
            "items": [
                {
                    "key": i.key,
                    "challengeId": i.challenge_id,
                    "publish": i.manifest.publish,
                    "flagCount": len(i.manifest.flags),
                }
                for i in plan.items
            ],
        }
    with locked(path):
        if path.exists():
            state = json.loads(path.read_text())
            if state.get("identity") != identity:
                raise GZCTFError("Batch target/input fingerprint differs from saved state")
        else:
            state = {
                "identity": identity,
                "items": {
                    i.key: {"stage": "ready", "challengeId": i.challenge_id, "uploadedHashes": []}
                    for i in plan.items
                },
            }
            save(path, state)
        for item in plan.items:
            entry = state["items"][item.key]
            if entry["stage"] in ("deleting", "deleted"):
                raise GZCTFError("Cleaned batch cannot be deployed again; use a new state name")
            if entry["stage"] == "complete":
                continue
            if entry["stage"] in ("creating", "uploading"):
                return {
                    "completed": False,
                    "blockedKey": item.key,
                    "stage": entry["stage"],
                    "nextTool": "admin_batch_reconcile",
                    "statePath": str(path),
                }
            if entry["uploadedHashes"] and "uploadReferences" not in entry:
                raise GZCTFError(
                    "Legacy upload ledger has no attachment ownership. Inspect existing "
                    "attachments and use a new state name with local attachment paths."
                )
            references = entry.setdefault("uploadReferences", {})

            def checkpoint(stage, challenge_id, digest=None, slot=None, entry=entry):
                entry.update(stage=stage, challengeId=challenge_id)
                if digest and stage == "uploaded":
                    entry["uploadedHashes"].append(digest)
                if stage == "uploading":
                    entry["uncertainHash"] = digest
                    entry["uncertainSlot"] = slot
                else:
                    entry.pop("uncertainHash", None)
                    entry.pop("uncertainSlot", None)
                save(path, state)

            entry["stage"] = "configuring" if entry["challengeId"] else "creating"
            save(path, state)
            result = await deploy(
                api, game_id, item.manifest, False, entry["challengeId"], checkpoint, references
            )
            if result["completed"]:
                entry.update(stage="complete", challengeId=result["challengeId"])
            elif entry["stage"] not in ("creating", "uploading"):
                entry["stage"] = "incomplete"
            save(path, state)
            if not result["completed"]:
                return {
                    "completed": False,
                    "key": item.key,
                    "result": result,
                    "statePath": str(path),
                }
        return {"completed": True, "statePath": str(path), "items": state["items"]}


def register_batch(tool, api, proxies):
    @tool(destructive=True)
    async def admin_deploy_batch(
        game_id: Id, plan_file: str, state_name: str, dry_run: bool = True
    ) -> dict[str, Any]:
        """Preview/run a JSON batch plan. Persist IDs atomically; resume with identical inputs.

        Stops at first failure. Never retries uncertain creates/uploads; inspect remote state
        then use admin_batch_reconcile. State contains IDs and hashes, never Flag/Cookie.
        """
        return await batch_deploy(api, game_id, plan_file, state_name, dry_run)

    @tool(destructive=True)
    async def admin_batch_reconcile(
        state_name: str,
        key: str,
        challenge_id: Id,
        uploaded_hashes: list[str],
        reference_slot: str | None = None,
    ) -> dict[str, Any]:
        """After manual upstream inspection, bind an uncertain batch item to its existing ID.

        uploaded_hashes is [] for creation, or [hash] for one confirmed unused upload.
        For an uploading slot, [] explicitly confirms that the upload did not happen.
        reference_slot identifies attachment or flag:<index>; defaults to the uncertain slot.
        Inspect reference counts and attachment ownership, not just blob existence.
        """
        path = state_path(api, state_name)
        with locked(path):
            state = json.loads(path.read_text())
            if state["identity"]["origin"] != api.settings.base_url:
                raise GZCTFError("Saved origin differs from current target")
            if any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in uploaded_hashes):
                raise GZCTFError("Expected lowercase SHA256 hashes")
            current = await api.request(
                "admin", "GET", challenge_path(state["identity"]["gameId"], challenge_id)
            )
            if current.get("isEnabled"):
                raise GZCTFError("Inspect and disable the challenge before reconciliation")
            entry = state["items"][key]
            if entry["stage"] in ("complete", "deleting", "deleted"):
                raise GZCTFError("Only incomplete deployment items can be reconciled")
            if entry.get("challengeId") not in (None, challenge_id):
                raise GZCTFError("Cannot reassign an existing item's challenge ID")
            slot = reference_slot or entry.get("uncertainSlot")
            references = entry.setdefault("uploadReferences", {})
            if uploaded_hashes:
                if len(uploaded_hashes) != 1 or slot not in references:
                    raise GZCTFError("Confirm one previously recorded upload slot at a time")
                previous = references[slot]
                if previous["hash"] != uploaded_hashes[0] or previous["state"] == "bound":
                    raise GZCTFError("Upload must match an unbound recorded slot")
                references[slot] = {"hash": uploaded_hashes[0], "state": "uploaded"}
            elif slot:
                if slot not in references or references[slot]["state"] != "uploading":
                    raise GZCTFError("Only an unconfirmed upload can be marked as not applied")
                del references[slot]
            entry.update(challengeId=challenge_id, stage="incomplete")
            entry.pop("uncertainHash", None)
            entry.pop("uncertainSlot", None)
            save(path, state)
        return {"reconciled": True, "key": key, "challengeId": challenge_id}

    @tool(read=True)
    async def admin_batch_status(state_name: str) -> dict[str, Any]:
        """Read secret-free local deployment ledger."""
        path = state_path(api, state_name)
        state = json.loads(path.read_text())
        if state["identity"]["origin"] != api.settings.base_url:
            raise GZCTFError("Saved origin differs from current target")
        return state

    @tool(destructive=True)
    async def admin_cleanup_batch(state_name: str, dry_run: bool = True) -> dict[str, Any]:
        """Preview/delete challenges recorded by this batch. Does not delete shared blobs blindly."""
        path = state_path(api, state_name)
        with locked(path):
            state = json.loads(path.read_text())
            identity = state["identity"]
            if identity["origin"] != api.settings.base_url:
                raise GZCTFError("Saved origin differs from current target")
            ids = [e["challengeId"] for e in state["items"].values() if e.get("challengeId")]
            if dry_run:
                return {"dryRun": True, "gameId": identity["gameId"], "challengeIds": ids}
            # A missing challenge is only meaningful after proving access to its parent.
            await api.request("admin", "GET", f"/api/edit/Games/{identity['gameId']}")
            for entry in state["items"].values():
                if entry.get("challengeId") and entry["stage"] != "deleted":
                    if entry["stage"] == "deleting":
                        remaining = await api.request(
                            "admin", "GET", challenge_path(identity["gameId"])
                        )
                        if not isinstance(remaining, list) or any(
                            not isinstance(c, dict) or not isinstance(c.get("id"), int)
                            for c in remaining
                        ):
                            raise GZCTFError("Invalid challenge inventory; cleanup stopped")
                        if entry["challengeId"] not in [c["id"] for c in remaining]:
                            await proxies.close_for(identity["gameId"], entry["challengeId"])
                            entry["stage"] = "deleted"
                            save(path, state)
                            continue
                    entry["stage"] = "deleting"
                    save(path, state)
                    await api.request(
                        "admin", "DELETE", challenge_path(identity["gameId"], entry["challengeId"])
                    )
                    await proxies.close_for(identity["gameId"], entry["challengeId"])
                    entry["stage"] = "deleted"
                    save(path, state)
            return {"completed": True, "challengeIds": ids, "blobCleanup": "inspect admin_files"}
