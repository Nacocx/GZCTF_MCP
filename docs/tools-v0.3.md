# 工具清单 v0.3

自动从当前 MCP 注册表生成：73 个工具。字段含义与工作流见 [使用说明](gap-remediation-usage.md)。`*` 表示必填。

| 工具 | 参数 | 行为 |
| --- | --- | --- |
| `connection_info` | 无 | Show non-secret configuration and identity availability; does not test the remote server. |
| `check_session` | `role*` | Check the configured account. Admin also verifies access to the edit API. |
| `auth_requirements` | 无 | Read public configuration and CAPTCHA policy; credentials stay in environment. |
| `auth_pow_challenge` | 无 | Get the platform-issued PoW challenge, without bypassing its validation. |
| `auth_login` | `role*`, `challenge` | Log in once using environment credentials and optional CAPTCHA response. Never retries. |
| `auth_logout` | `role*` | Invalidate the chosen session and clear its in-memory Cookie. |
| `list_games` | `count`, `skip` | List visible competitions using the player session. |
| `get_game` | `game_id*` | Read game details and participation requirements. |
| `list_teams` | 无 | List teams associated with the configured player account. |
| `join_check` | `game_id*` | Read available teams/divisions and registration conditions before joining. |
| `join_game` | `game_id*`, `team_id*`, `division_id`, `invite_code`, `division_name` | Register an existing team. Approval may still be required by the organizer. |
| `list_challenges` | `game_id*` | Read participant challenge list and current team information (requires participation). |
| `get_challenge` | `game_id*`, `challenge_id*` | Read participant-facing challenge content, attachment and current container details. |
| `scoreboard` | `game_id*` | Read the competition scoreboard. |
| `notices` | `game_id*`, `count`, `skip` | Read competition announcements. |
| `submit_flag` | `game_id*`, `challenge_id*`, `flag*` | Submit one candidate flag once. Query submission_status; an ID is not an Accepted verdict. |
| `submission_status` | `game_id*`, `challenge_id*`, `submission_id*` | Query asynchronous verdict. FlagSubmitted is pending; only Accepted means solved. |
| `container_action` | `game_id*`, `challenge_id*`, `action*` | Start, extend, or stop the team's challenge container. Stop destroys its runtime state. |
| `download_attachment` | `asset_path*`, `filename*`, `role` | Download a same-site asset anonymously; select a role only for an authenticated proxy. |
| `submit_writeup` | `game_id*`, `path*` | Upload a local writeup file from GZCTF_WORKSPACE as the participating team. |
| `admin_list_games` | `count`, `skip` | List competitions including hidden ones with the organizer session. |
| `admin_create_game` | `game*` | Create a competition with explicit timezone-aware dates; hidden by default. |
| `admin_get_game` | `game_id*` | Read organizer game settings. |
| `admin_list_challenges` | `game_id*` | List all organizer challenges, including disabled ones. |
| `admin_get_challenge` | `game_id*`, `challenge_id*` | Read organizer configuration and flags. Author-only; do not share with contestants. |
| `admin_create_challenge` | `game_id*`, `challenge*` | Create a disabled challenge shell; type is fixed at creation. Then configure/attach flags. |
| `admin_update_challenge` | `game_id*`, `challenge_id*`, `configuration*` | Update specified fields only. isEnabled publishes/disables; disabling stops all containers. |
| `admin_upload_file` | `path*` | Upload a workspace file; grants one attachment reference in this MCP session. |
| `admin_set_attachment` | `game_id*`, `challenge_id*`, `attachment*` | Replace/remove common attachment. DynamicAttachment uses admin_add_flags instead. |
| `admin_add_flags` | `game_id*`, `challenge_id*`, `flags*` | Append flags. Each Local attachment consumes one upload from this MCP session. |
| `admin_delete_flag` | `game_id*`, `challenge_id*`, `flag_id*` | Delete a particular flag by its ID. |
| `admin_delete_challenge` | `game_id*`, `challenge_id*` | Permanently delete a challenge. Prefer isEnabled=false when only hiding it. |
| `admin_test_container` | `game_id*`, `challenge_id*`, `action*` | Start/destroy organizer test container; read its state with admin_get_challenge. |
| `admin_deploy_challenge` | `game_id*`, `manifest*`, `dry_run`, `challenge_id` | Validate/preview an authoring manifest; dry_run=false creates/configures/uploads/publishes. |
| `admin_deploy_manifest_file` | `game_id*`, `path*`, `dry_run`, `challenge_id` | Read a JSON manifest inside workspace and run the same deploy workflow. |
| `platform_config` | `role` | Read platform portMapping and container lifetime/renewal settings with the chosen session. |
| `proxy_open` | `game_id*`, `challenge_id*`, `role`, `local_port` | Connect an existing container via managed wsrx on 127.0.0.1 (port 0 auto-selects). |
| `proxy_list` | 无 | List only tunnels owned by this MCP process, without disclosing upstream capability URLs. |
| `proxy_close` | `proxy_id*` | Close this MCP process's local tunnel; does not stop the remote challenge container. |
| `admin_list_divisions` | `game_id*` | Read division settings including permissions and per-challenge overrides. |
| `admin_save_division` | `game_id*`, `division*`, `division_id` | Create/update division. Named permission list is ORed; [] denies all, All includes review. |
| `admin_delete_division` | `game_id*`, `division_id*` | Delete a division and its permissions; inspect participation assignments first. |
| `admin_participations` | `game_id*` | List registration IDs, assigned divisions and approval states. |
| `admin_review_participation` | `participation_id*`, `status*`, `division_id` | Review registration, optionally assign a division. Uses participation ID, not team ID. |
| `admin_update_game` | `game_id*`, `patch*` | Read full settings, merge explicit patch, validate, PUT. Blood bonuses use per mille. |
| `admin_delete_game` | `game_id*` | Permanently delete an entire competition and close owned tunnels for it. |
| `admin_game_poster` | `game_id*`, `path*` | Upload a competition poster from workspace (at most 3 MiB). |
| `admin_notices` | `game_id*` | Read editable competition announcements. |
| `admin_save_notice` | `game_id*`, `content*`, `notice_id` | Create/update a normal announcement; cannot edit system notices. |
| `admin_delete_notice` | `game_id*`, `notice_id*` | Delete a normal competition announcement. |
| `admin_flush_scoreboard` | `game_id*` | Invalidate competition scoreboard cache. |
| `admin_files` | `count`, `skip` | Inspect uploaded file hashes and references before cleanup. |
| `admin_delete_file` | `file_hash*`, `dry_run` | Preview/delete one file reference. Shared blobs may remain; inspect admin_files afterward. |
| `get_team` | `team_id*` | Read team details and membership. |
| `save_team` | `team*`, `team_id` | Create/update a team. Explicit name prevents upstream defaults erasing it. |
| `team_invite` | `team_id*` | Read team invitation code (sensitive; share only with intended members). |
| `team_rotate_invite` | `team_id*` | Rotate the team invitation code, invalidating the old one. |
| `team_accept_invite` | `code*` | Join a team using its invitation code. |
| `team_action` | `team_id*`, `action*`, `user_id` | Leave/delete a team, kick member or transfer captaincy; kick/transfer need user UUID. |
| `team_avatar` | `team_id*`, `path*` | Upload a team avatar from workspace. |
| `leave_game` | `game_id*` | Withdraw current membership while Pending/Rejected; upstream forbids withdrawal after approval. |
| `writeup_status` | `game_id*` | Read current team's writeup submission state. |
| `admin_events` | `game_id*`, `count`, `skip`, `hide_container` | Read paginated competition events with organizer access. |
| `admin_submissions` | `game_id*`, `count`, `skip`, `result` | Read paginated submissions; optional result is upstream AnswerResult enum. |
| `admin_instances` | 无 | Read active challenge container instances. |
| `admin_stop_instance` | `instance_id*` | Destroy a specific challenge instance by UUID. |
| `admin_import_game` | `path*` | Import an official game ZIP from workspace. Creates a competition; never retries. |
| `admin_export_game` | `game_id*`, `filename*` | Export an official ZIP to workspace/downloads; contains author-only material. |
| `admin_export_records` | `game_id*`, `kind*`, `filename*` | Stream scoreboard/submissions XLSX or all writeups TAR to downloads; never overwrites. |
| `admin_deploy_batch` | `game_id*`, `plan_file*`, `state_name*`, `dry_run` | Preview/run a JSON batch plan. Persist IDs atomically; resume with identical inputs. |
| `admin_batch_reconcile` | `state_name*`, `key*`, `challenge_id*`, `uploaded_hashes*`, `reference_slot` | After manual upstream inspection, bind an uncertain batch item to its existing ID. |
| `admin_batch_status` | `state_name*` | Read secret-free local deployment ledger. |
| `admin_cleanup_batch` | `state_name*`, `dry_run` | Preview/delete challenges recorded by this batch. Does not delete shared blobs blindly. |
