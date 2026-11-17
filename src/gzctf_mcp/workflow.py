import hashlib
import uuid

from .client import Client, GZCTFError
from .models import ChallengeManifest


def challenge_path(game_id: int, challenge_id: int | None = None):
    path = f"/api/edit/Games/{game_id}/Challenges"
    return f"{path}/{challenge_id}" if challenge_id is not None else path


def same_attachment(current, desired):
    current = current or {}
    kind = current.get("type", "None")
    url = current.get("url") or ""
    return kind == desired.attachment_type and (
        kind == "None"
        or kind == "Remote"
        and url == desired.remote_url
        or kind == "Local"
        and url.startswith(f"/assets/{desired.file_hash}/")
    )


async def verify_local_attachment(client, attachment):
    if not attachment or attachment.get("type") != "Local":
        return
    url = attachment.get("url") or ""
    import re

    if not re.fullmatch(r"/assets/[0-9a-f]{64}/[^/?#]+", url):
        raise GZCTFError("Invalid local attachment URL in readback")
    # A fresh name avoids a cache hit for a blob that upstream may have removed.
    probe = url.rsplit("/", 1)[0] + "/verify-" + uuid.uuid4().hex
    async with client.stream(
        "admin", "GET", probe, headers={"Cache-Control": "no-cache"}
    ) as response:
        digest = hashlib.sha256()
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > client.settings.max_file_bytes:
                raise GZCTFError("Attachment verification exceeds file size limit")
            digest.update(chunk)
        if digest.hexdigest() != url.split("/")[2]:
            raise GZCTFError("Attachment readback SHA256 mismatch")


async def prepare_reference(client, challenge_id, digest, local_path, slot, references, record):
    previous = references.get(slot)
    if previous:
        if previous != {"hash": digest, "state": "uploaded"}:
            raise GZCTFError(
                "Attachment reference already reserved or changed. Inspect remote attachment "
                "and reconcile this exact upload slot before binding again."
            )
        return
    if local_path:
        record("uploading", challenge_id, digest, slot)
        uploaded = await client.upload(local_path)
        if not uploaded or uploaded[0].get("hash") != digest:
            raise GZCTFError("Upload SHA256 differs from local file")
    client.take_upload_reference(digest)
    record("uploaded", challenge_id, digest, slot)


async def set_attachment(
    client, game_id, challenge_id, desired, local_path=None, checkpoint=None, references=None
):
    async with client.attachment_locks[(game_id, challenge_id)]:
        return await _set_attachment(
            client, game_id, challenge_id, desired, local_path, checkpoint, references
        )


async def _set_attachment(
    client, game_id, challenge_id, desired, local_path=None, checkpoint=None, references=None
):
    references = references if references is not None else {}

    def record(event, identifier, digest, slot):
        references[slot] = {"hash": digest, "state": event}
        if checkpoint:
            checkpoint(event, identifier, digest, slot)

    path = challenge_path(game_id, challenge_id)
    current = await client.request("admin", "GET", path)
    if not same_attachment(current.get("attachment"), desired):
        if desired.attachment_type == "Local":
            await prepare_reference(
                client,
                challenge_id,
                desired.file_hash,
                local_path,
                "attachment",
                references,
                record,
            )
            record("binding", challenge_id, desired.file_hash, "attachment")
        await client.request("admin", "POST", path + "/Attachment", json=desired.payload())
        current = await client.request("admin", "GET", path)
        if not same_attachment(current.get("attachment"), desired):
            raise GZCTFError("Attachment configuration readback differs from request")
    if desired.attachment_type == "Local" and "attachment" in references:
        record("bound", challenge_id, desired.file_hash, "attachment")
    await verify_local_attachment(client, current.get("attachment"))
    return {"verified": True}


async def deploy(
    client: Client,
    game_id: int,
    manifest: ChallengeManifest,
    dry_run: bool = True,
    challenge_id: int | None = None,
    checkpoint=None,
    references=None,
):
    references = references if references is not None else {}
    # All local validation precedes any remote mutation.
    if manifest.attachment_path:
        client.local_file(manifest.attachment_path)
    for flag in manifest.flags:
        if flag.attachment_path:
            client.local_file(flag.attachment_path)
    result = {
        "dryRun": dry_run,
        "gameId": game_id,
        "challengeId": challenge_id,
        "stage": "validated",
        "publish": manifest.publish,
        "steps": ["create_or_inspect", "configure", "attachment", "flags", "publish"],
        "flagCount": len(manifest.flags),
        "resources": {
            "challengeId": challenge_id,
            "createdChallenge": False,
            "uploadedHashes": [],
            "uploadReferences": references,
        },
    }
    if dry_run:
        return result

    def record(event, identifier, digest=None, slot=None):
        result["resources"]["challengeId"] = identifier
        if event == "created":
            result["resources"]["createdChallenge"] = True
        if event == "uploaded" and digest:
            result["resources"]["uploadedHashes"].append(digest)
        if slot:
            references[slot] = {"hash": digest, "state": event}
        if checkpoint:
            checkpoint(event, identifier, digest, slot)

    stage = "inspect" if challenge_id else "create"
    try:
        if challenge_id is None:
            raw_hashes = [
                f.file_hash
                for f in manifest.flags
                if f.attachment_type == "Local" and not f.attachment_path
            ]
            if manifest.attachment and manifest.attachment.attachment_type == "Local":
                raw_hashes.append(manifest.attachment.file_hash)
            client.check_upload_references(raw_hashes)
        if challenge_id is not None:
            current = await client.request("admin", "GET", challenge_path(game_id, challenge_id))
            if (
                current["type"] != manifest.challenge.type
                or current["title"] != manifest.challenge.title
            ):
                raise GZCTFError(
                    "Existing challenge title/type differs from manifest; refusing to resume"
                )
            if current["isEnabled"]:
                raise GZCTFError(
                    "Resume requires a disabled challenge; explicitly disable it first"
                )
        else:
            current = await client.request(
                "admin",
                "POST",
                challenge_path(game_id),
                json=manifest.challenge.model_dump(by_alias=True),
            )
            challenge_id = current["id"]
            result["challengeId"] = challenge_id
            record("created", challenge_id)
        path = challenge_path(game_id, challenge_id)
        stage = "configure"
        await client.request("admin", "PUT", path, json=manifest.configuration.payload())
        stage = "attachment"
        if manifest.attachment_path:
            from .models import Attachment

            digest = hashlib.sha256(
                client.local_file(manifest.attachment_path).read_bytes()
            ).hexdigest()
            await set_attachment(
                client,
                game_id,
                challenge_id,
                Attachment(attachment_type="Local", file_hash=digest),
                manifest.attachment_path,
                record,
                references,
            )
        elif manifest.attachment:
            await set_attachment(
                client,
                game_id,
                challenge_id,
                manifest.attachment,
                checkpoint=record,
                references=references,
            )
        stage = "flags"
        # Read back after a possible previous partial attempt; never blindly append duplicate flags.
        current = await client.request("admin", "GET", path)
        existing = {flag["flag"]: flag for flag in current.get("flags", [])}
        missing = []
        missing_slots = []
        for index, flag in enumerate(manifest.flags):
            slot = f"flag:{index}"
            local_path = flag.attachment_path
            if flag.attachment_path:
                digest = hashlib.sha256(
                    client.local_file(flag.attachment_path).read_bytes()
                ).hexdigest()
                flag = flag.model_copy(update={"file_hash": digest, "attachment_path": None})
            if flag.flag not in existing:
                if flag.attachment_type == "Local":
                    await prepare_reference(
                        client, challenge_id, flag.file_hash, local_path, slot, references, record
                    )
                    missing_slots.append((slot, flag.file_hash))
                missing.append(flag.wire())
            else:
                attachment = existing[flag.flag].get("attachment") or {}
                local_url = attachment.get("url") or ""
                local_hash = local_url.split("/")[2] if local_url.startswith("/assets/") else None
                if (
                    attachment.get("type", "None") != flag.attachment_type
                    or (flag.attachment_type == "Local" and local_hash != flag.file_hash)
                    or (
                        flag.attachment_type == "Remote"
                        and attachment.get("url") != flag.remote_url
                    )
                ):
                    raise GZCTFError(
                        "Existing flag attachment differs; inspect and correct it before resuming"
                    )
                if slot in references:
                    record("bound", challenge_id, flag.file_hash, slot)
        if missing:
            for slot, digest in missing_slots:
                record("binding", challenge_id, digest, slot)
            await client.request("admin", "POST", path + "/Flags", json=missing)
            for slot, digest in missing_slots:
                record("bound", challenge_id, digest, slot)
        if any(f.attachment_type == "Local" for f in manifest.flags):
            final = await client.request("admin", "GET", path)
            for item in final.get("flags", []):
                if item.get("flag") in {f.flag for f in manifest.flags}:
                    await verify_local_attachment(client, item.get("attachment"))
        stage = "publish"
        if manifest.publish:
            await client.request("admin", "PUT", path, json={"isEnabled": True})
        result.update(stage="complete", challengeId=challenge_id, completed=True)
        return result
    except (GZCTFError, OSError, KeyError, TypeError, ValueError) as error:
        result.update(
            stage=stage,
            error=str(error)
            if isinstance(error, GZCTFError)
            else "Local file or upstream response is invalid; inspect remote state",
            completed=False,
            recovery="Inspect remote state. Resume using challenge_id only after checking "
            "the disabled challenge. If create timed out, find its ID in the "
            "admin list; do not blindly create again.",
        )
        return result
