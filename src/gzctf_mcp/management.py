"""Typed platform administration and participant workflows, aligned with upstream controllers."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from .client import GZCTFError
from .models import DivisionConfig, GameCreate, GamePatch, Id, TeamConfig

Page = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def wire_value(value):
    # GZCTF serializes DateTimeOffset as Unix milliseconds, dropping sub-ms precision.
    if isinstance(value, datetime):
        return value.replace(microsecond=value.microsecond // 1000 * 1000)
    return value


async def join(api, game_id, team_id, division_id=None, invite_code=None, division_name=None):
    game = await api.request("player", "GET", f"/api/game/{game_id}")
    divisions = game.get("divisions") or []
    if division_name is not None:
        matches = [d for d in divisions if d["name"] == division_name]
        if len(matches) != 1:
            raise GZCTFError("Division name must identify exactly one division; inspect get_game")
        if division_id is not None and division_id != matches[0]["id"]:
            raise GZCTFError("Division name and ID disagree")
        division_id = matches[0]["id"]
    if divisions and division_id is None:
        raise GZCTFError("Choose an explicit division ID or name before registration")
    if division_id is not None and division_id not in [d["id"] for d in divisions]:
        raise GZCTFError("Division does not belong to this game")
    check = await api.request("player", "GET", f"/api/game/{game_id}/Check")
    available = check.get("joinableDivisions")
    if available is not None and division_id is not None and division_id not in available:
        raise GZCTFError("Chosen division is not joinable; inspect registration status")
    await api.request(
        "player",
        "POST",
        f"/api/game/{game_id}",
        json={"teamId": team_id, "divisionId": division_id, "inviteCode": invite_code},
    )
    final = await api.request("player", "GET", f"/api/game/{game_id}")
    return {
        "status": final.get("status"),
        "accepted": final.get("status") == "Accepted",
        "division": final.get("division"),
        "data": final,
    }


def register_management(tool, api, proxies):
    @tool(read=True)
    async def admin_list_divisions(game_id: Id) -> dict[str, Any]:
        """Read division settings including permissions and per-challenge overrides."""
        return {"data": await api.request("admin", "GET", f"/api/edit/Games/{game_id}/Divisions")}

    @tool(destructive=True)
    async def admin_save_division(
        game_id: Id, division: DivisionConfig, division_id: Id | None = None
    ) -> dict[str, Any]:
        """Create/update division. Named permission list is ORed; [] denies all, All includes review.

        challengeConfigs replaces the complete override list; omit to preserve on update.
        Empty inviteCode clears it; null/omitted preserves it on update.
        """
        path = f"/api/edit/Games/{game_id}/Divisions"
        if division_id:
            path += f"/{division_id}"
        return {
            "data": await api.request(
                "admin", "PUT" if division_id else "POST", path, json=division.payload()
            )
        }

    @tool(destructive=True)
    async def admin_delete_division(game_id: Id, division_id: Id) -> dict[str, Any]:
        """Delete a division and its permissions; inspect participation assignments first."""
        return {
            "data": await api.request(
                "admin", "DELETE", f"/api/edit/Games/{game_id}/Divisions/{division_id}"
            )
        }

    @tool(read=True)
    async def admin_participations(game_id: Id) -> dict[str, Any]:
        """List registration IDs, assigned divisions and approval states."""
        return {"data": await api.request("admin", "GET", f"/api/game/{game_id}/Participations")}

    @tool(destructive=True)
    async def admin_review_participation(
        participation_id: Id,
        status: Literal["Pending", "Accepted", "Rejected", "Suspended"],
        division_id: Id | None = None,
    ) -> dict[str, Any]:
        """Review registration, optionally assign a division. Uses participation ID, not team ID."""
        body = {"status": status}
        if division_id is not None:
            body["divisionId"] = division_id
        return {
            "data": await api.request(
                "admin", "PUT", f"/api/admin/Participation/{participation_id}", json=body
            )
        }

    @tool(destructive=True)
    async def admin_update_game(game_id: Id, patch: GamePatch) -> dict[str, Any]:
        """Read full settings, merge explicit patch, validate, PUT. Blood bonuses use per mille."""
        path = f"/api/edit/Games/{game_id}"
        async with api.game_locks[game_id]:
            current = await api.request("admin", "GET", path)
            updates = patch.payload()
            current.update(updates)
            # Validate merged dates/limits without erasing unpatched server fields.
            fields = {f.alias or name: name for name, f in GameCreate.model_fields.items()}
            expected = GameCreate.model_validate({k: v for k, v in current.items() if k in fields})
            await api.request("admin", "PUT", path, json=current)
            final = await api.request("admin", "GET", path)
            observed = GameCreate.model_validate({k: v for k, v in final.items() if k in fields})
            if any(
                wire_value(getattr(expected, fields[k])) != wire_value(getattr(observed, fields[k]))
                for k in updates
            ):
                raise GZCTFError(
                    "Game update readback differs from patch; another editor or server rule "
                    "may have changed it. Inspect admin_get_game before retrying."
                )
            return {"data": final}

    @tool(destructive=True)
    async def admin_delete_game(game_id: Id) -> dict[str, Any]:
        """Permanently delete an entire competition and close owned tunnels for it."""
        data = await api.request("admin", "DELETE", f"/api/edit/Games/{game_id}")
        for item in proxies.list():
            if item["gameId"] == game_id:
                await proxies.close_one(item["proxyId"])
        return {"data": data}

    @tool(destructive=True)
    async def admin_game_poster(game_id: Id, path: str) -> dict[str, Any]:
        """Upload a competition poster from workspace (at most 3 MiB)."""
        return {
            "data": await api.multipart(
                "admin", "PUT", f"/api/edit/Games/{game_id}/Poster", path, max_bytes=3 * 1024 * 1024
            )
        }

    @tool(read=True)
    async def admin_notices(game_id: Id) -> dict[str, Any]:
        """Read editable competition announcements."""
        return {"data": await api.request("admin", "GET", f"/api/edit/Games/{game_id}/Notices")}

    @tool(destructive=True)
    async def admin_save_notice(
        game_id: Id, content: str, notice_id: Id | None = None
    ) -> dict[str, Any]:
        """Create/update a normal announcement; cannot edit system notices."""
        path = f"/api/edit/Games/{game_id}/Notices"
        return {
            "data": await api.request(
                "admin",
                "PUT" if notice_id else "POST",
                path + (f"/{notice_id}" if notice_id else ""),
                json={"content": content},
            )
        }

    @tool(destructive=True)
    async def admin_delete_notice(game_id: Id, notice_id: Id) -> dict[str, Any]:
        """Delete a normal competition announcement."""
        return {
            "data": await api.request(
                "admin", "DELETE", f"/api/edit/Games/{game_id}/Notices/{notice_id}"
            )
        }

    @tool()
    async def admin_flush_scoreboard(game_id: Id) -> dict[str, Any]:
        """Invalidate competition scoreboard cache."""
        return {
            "data": await api.request(
                "admin", "POST", f"/api/edit/Games/{game_id}/Scoreboard/Flush"
            )
        }

    @tool(read=True)
    async def admin_files(
        count: Annotated[int, Field(ge=1, le=500)] = 50, skip: Offset = 0
    ) -> dict[str, Any]:
        """Inspect uploaded file hashes and references before cleanup."""
        return {
            "data": await api.request(
                "admin", "GET", "/api/admin/Files", params={"count": count, "skip": skip}
            )
        }

    @tool(destructive=True)
    async def admin_delete_file(file_hash: Hash, dry_run: bool = True) -> dict[str, Any]:
        """Preview/delete one file reference. Shared blobs may remain; inspect admin_files afterward."""
        if dry_run:
            return {
                "dryRun": True,
                "hash": file_hash,
                "effect": "decrement reference or remove blob",
            }
        # A failed/uncertain deletion must not leave a reusable local upload credit.
        api.upload_references.pop(file_hash, None)
        return {
            "data": await api.request("admin", "DELETE", f"/api/assets/{file_hash}"),
            "storageDeletionConfirmed": False,
            "nextTool": "admin_files",
        }

    @tool(read=True)
    async def get_team(team_id: Id) -> dict[str, Any]:
        """Read team details and membership."""
        return {"data": await api.request("player", "GET", f"/api/team/{team_id}")}

    @tool(destructive=True)
    async def save_team(team: TeamConfig, team_id: Id | None = None) -> dict[str, Any]:
        """Create/update a team. Explicit name prevents upstream defaults erasing it."""
        body = team.payload()
        if team_id and "bio" not in body:
            current = await api.request("player", "GET", f"/api/team/{team_id}")
            body["bio"] = current.get("bio")
        return {
            "data": await api.request(
                "player",
                "PUT" if team_id else "POST",
                f"/api/team/{team_id}" if team_id else "/api/team",
                json=body,
            )
        }

    @tool(read=True)
    async def team_invite(team_id: Id) -> dict[str, Any]:
        """Read team invitation code (sensitive; share only with intended members)."""
        return {"data": await api.request("player", "GET", f"/api/team/{team_id}/Invite")}

    @tool(destructive=True)
    async def team_rotate_invite(team_id: Id) -> dict[str, Any]:
        """Rotate the team invitation code, invalidating the old one."""
        return {"data": await api.request("player", "PUT", f"/api/team/{team_id}/Invite")}

    @tool()
    async def team_accept_invite(code: str) -> dict[str, Any]:
        """Join a team using its invitation code."""
        return {"data": await api.request("player", "POST", "/api/team/Accept", json=code)}

    @tool(destructive=True)
    async def team_action(
        team_id: Id,
        action: Literal["leave", "delete", "kick", "transfer"],
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Leave/delete a team, kick member or transfer captaincy; kick/transfer need user UUID."""
        path = f"/api/team/{team_id}"
        if action in ("kick", "transfer") and user_id is None:
            raise GZCTFError("user_id is required for kick/transfer")
        method, body = "POST", {}
        if action == "leave":
            path += "/Leave"
        elif action == "delete":
            method = "DELETE"
        elif action == "kick":
            path += f"/Kick/{user_id}"
        else:
            method, path = "PUT", path + "/Transfer"
            body = {"json": {"newCaptainId": str(user_id)}}
        return {"data": await api.request("player", method, path, **body)}

    @tool(destructive=True)
    async def team_avatar(team_id: Id, path: str) -> dict[str, Any]:
        """Upload a team avatar from workspace."""
        return {
            "data": await api.multipart(
                "player", "PUT", f"/api/team/{team_id}/Avatar", path, max_bytes=3 * 1024 * 1024
            )
        }

    @tool(destructive=True)
    async def leave_game(game_id: Id) -> dict[str, Any]:
        """Withdraw current membership while Pending/Rejected; upstream forbids withdrawal after approval."""
        return {"data": await api.request("player", "DELETE", f"/api/game/{game_id}")}

    @tool(read=True)
    async def writeup_status(game_id: Id) -> dict[str, Any]:
        """Read current team's writeup submission state."""
        return {"data": await api.request("player", "GET", f"/api/game/{game_id}/Writeup")}

    @tool(read=True)
    async def admin_events(
        game_id: Id, count: Page = 50, skip: Offset = 0, hide_container: bool = False
    ) -> dict[str, Any]:
        """Read paginated competition events with organizer access."""
        return {
            "data": await api.request(
                "admin",
                "GET",
                f"/api/game/{game_id}/Events",
                params={"count": count, "skip": skip, "hideContainer": hide_container},
            )
        }

    @tool(read=True)
    async def admin_submissions(
        game_id: Id,
        count: Page = 50,
        skip: Offset = 0,
        result: Literal["FlagSubmitted", "Accepted", "WrongAnswer", "CheatDetected", "NotFound"]
        | None = None,
    ) -> dict[str, Any]:
        """Read paginated submissions; optional result is upstream AnswerResult enum."""
        params = {"count": count, "skip": skip}
        if result is not None:
            params["type"] = result
        return {
            "data": await api.request(
                "admin", "GET", f"/api/game/{game_id}/Submissions", params=params
            )
        }

    @tool(read=True)
    async def admin_instances() -> dict[str, Any]:
        """Read active challenge container instances."""
        return {"data": await api.request("admin", "GET", "/api/admin/Instances")}

    @tool(destructive=True)
    async def admin_stop_instance(instance_id: UUID) -> dict[str, Any]:
        """Destroy a specific challenge instance by UUID."""
        data = await api.request("admin", "DELETE", f"/api/admin/Instances/{instance_id}")
        await proxies.close_instance(instance_id)
        return {"data": data}

    @tool(destructive=True)
    async def admin_import_game(path: str) -> dict[str, Any]:
        """Import an official game ZIP from workspace. Creates a competition; never retries."""
        import zipfile

        file = api.local_file(path)
        if file.suffix.lower() != ".zip" or not zipfile.is_zipfile(file):
            raise GZCTFError("Expected an official game ZIP archive")
        return {"data": await api.multipart("admin", "POST", "/api/edit/Games/Import", path)}

    @tool()
    async def admin_export_game(game_id: Id, filename: str) -> dict[str, Any]:
        """Export an official ZIP to workspace/downloads; contains author-only material."""
        return await api.export_binary(
            "admin", "POST", f"/api/edit/Games/{game_id}/Export", filename
        )

    @tool()
    async def admin_export_records(
        game_id: Id, kind: Literal["scoreboard", "submissions", "writeups"], filename: str
    ) -> dict[str, Any]:
        """Stream scoreboard/submissions XLSX or all writeups TAR to downloads; never overwrites."""
        path = {
            "scoreboard": f"/api/game/{game_id}/ScoreboardSheet",
            "submissions": f"/api/game/{game_id}/SubmissionSheet",
            "writeups": f"/api/admin/Writeups/{game_id}/All",
        }[kind]
        return await api.export_binary("admin", "GET", path, filename)
