# 工具与上游接口映射

版本：0.3.0，2026-10-21。73 个 MCP 工具，1 个资源 `gzctf://workflow`。完整参数和新增工具见 [当前工具清单](tools-v0.3.md) 与 [v0.3 使用说明](gap-remediation-usage.md)；下面保留核心接口映射。
工具参数以 MCP 的 `tools/list` JSON Schema 为准：外层参数用 snake_case；嵌套模型在 Schema 中显示 camelCase，Python 内部也接受 snake_case。字段、枚举与边界见 `src/gzctf_mcp/models.py`。

| MCP 工具 | 身份 | HTTP / 功能 |
| --- | --- | --- |
| `connection_info` | 无 | 本地非敏感配置，不发送网络请求 |
| `check_session` | 指定角色 | GET `/api/account/Profile`；admin 另查编辑比赛列表 |
| `list_games` | player | GET `/api/game?count=&skip=` |
| `get_game` | player | GET `/api/game/{game_id}` |
| `list_teams` | player | GET `/api/team` |
| `join_check` | player | GET `/api/game/{game_id}/Check` |
| `join_game` | player | POST `/api/game/{game_id}`，teamId / divisionId / inviteCode |
| `list_challenges` | player | GET `/api/game/{game_id}/Details`，包含当前队伍上下文 |
| `get_challenge` | player | GET `/api/game/{game_id}/Challenges/{challenge_id}` |
| `scoreboard` | player | GET `/api/game/{game_id}/Scoreboard` |
| `notices` | player | GET `/api/game/{game_id}/Notices` |
| `submit_flag` | player | POST `/api/game/{game_id}/Challenges/{challenge_id}`，body 为 `{flag}` |
| `submission_status` | player | GET `/api/game/{game_id}/Challenges/{challenge_id}/Status/{submission_id}` |
| `container_action` | player | POST `/api/game/{game_id}/Container/{challenge_id}` 启动；POST `…/Extend` 续期；DELETE 原路径停止 |
| `download_attachment` | player | GET `/assets/{sha256}/{name}`，限同站与工作区，流式写入、校验内容哈希 |
| `submit_writeup` | player | POST `/api/game/{game_id}/Writeup`，multipart 字段 `file`、`application/pdf` |
| `admin_list_games` | admin | GET `/api/edit/Games?count=&skip=` |
| `admin_create_game` | admin | POST `/api/edit/Games`，明确带时区 start/end，默认 hidden=true，可在创建时显式设 false |
| `admin_get_game` | admin | GET `/api/edit/Games/{game_id}` |
| `admin_list_challenges` | admin | GET `/api/edit/Games/{game_id}/Challenges` |
| `admin_get_challenge` | admin | GET `/api/edit/Games/{game_id}/Challenges/{challenge_id}`，包含作者 Flag |
| `admin_create_challenge` | admin | POST `/api/edit/Games/{game_id}/Challenges`，title / category / type |
| `admin_update_challenge` | admin | PUT `/api/edit/Games/{game_id}/Challenges/{challenge_id}`，仅发送显式指定字段 |
| `admin_upload_file` | admin | POST `/api/assets`，multipart 字段 `files`，返回 LocalFile 列表 |
| `admin_set_attachment` | admin | POST `/api/edit/Games/{game_id}/Challenges/{challenge_id}/Attachment` |
| `admin_add_flags` | admin | POST `/api/edit/Games/{game_id}/Challenges/{challenge_id}/Flags`，数组而非单对象 |
| `admin_delete_flag` | admin | DELETE `/api/edit/Games/{game_id}/Challenges/{challenge_id}/Flags/{flag_id}` |
| `admin_delete_challenge` | admin | DELETE `/api/edit/Games/{game_id}/Challenges/{challenge_id}` |
| `admin_test_container` | admin | POST / DELETE `/api/edit/Games/{game_id}/Challenges/{challenge_id}/Container` |
| `admin_deploy_challenge` | admin | 内存清单，默认 dry_run=true；按阶段调用上述接口 |
| `admin_deploy_manifest_file` | admin | 从工作区 JSON 文件读取清单并执行相同工作流 |

## PlatformProxy 新增工具

| MCP 工具 | 身份 | 功能 |
| --- | --- | --- |
| `platform_config` | 指定角色 | GET /api/config，查询 portMapping/defaultLifetime/extensionDuration/renewalWindow |
| `proxy_open` | 指定角色 | 查询已认证实例 → 同站代理预检 → 启动受管 wsrx connect，仅监听 127.0.0.1；Default 返回直接地址 |
| `proxy_list` | 本地 | 列出本进程受管监听，不返回上游 UUID 或代理 URL |
| `proxy_close` | 本地 | 关闭本进程指定隧道，远端容器继续运行 |

角色对应：admin 查询题目的 testContainer；player 查询 context.instanceEntry。端口范围 0–65535，默认 0 自动选择。上游代理分别为 `/api/proxy/noinst/{uuid}` 与 `/api/proxy/{uuid}`，WS/WSS 根据站点 origin 推导。不会让 AI 任意指定远端 URL。

仅在用户通过本 MCP 停止容器、禁用/删除题目时自动关闭对应隧道；退出也会关闭。外部变更容器状态后需显式关闭。返回的监听状态不承诺应用服务已就绪。

## 返回和错误

底层查询/写操作一般返回 `{data: <原站响应>}`，空响应为 `{data: null}`。答题与部署使用专门返回结构，均提供 MCP structuredContent 与文本 JSON。

判题结果保留上游 `FlagSubmitted / Accepted / WrongAnswer / CheatDetected / NotFound` 字符串。当前源码可能将 CheatDetected 对选手映射成 WrongAnswer。状态工具同时返回 pending / accepted，未知状态不认定通过。

HTTP、网络、文件错误转为 MCP tool error；清单部署的已知失败返回 `completed=false` 和阶段以保留恢复信息，调用方必须检查该字段。原站错误只保留脱敏限长的业务 title/status 及下一步建议，不回显任意文本；400 应核查清单和当前比赛状态，401 刷新 Cookie，403 核查权限/报名审核，404 核查 ID 和可见性，429 按提示等待。

## 源码依据

上游参考目录均在 `GZCTF/src/GZCTF/`：

- `Controllers/EditController.cs`：上题、题目配置、附件、Flag、测试容器。
- `Controllers/GameController.cs`：报名、题面、容器、提交与异步状态。
- `Controllers/AssetsController.cs`：上传参数 `files`、静态附件访问。
- `Controllers/AccountController.cs` / `Controllers/TeamController.cs`：身份与队伍。
- `Middlewares/PrivilegeAuthentication.cs`：RequireAdmin / RequireUser；allowToken 默认为 false。
- `Models/Request/Edit/` / `Models/Request/Game/`：字段与约束。
- `Models/Data/Attachment.cs`：公开附件只有 type / url，LocalFile 与 RemoteUrl 不序列化，恢复比较使用公开 url。
- `Repositories/BlobRepository.cs`：附件采用内容 SHA256。
- `Utils/Enums.cs` / `Models/Limits.cs`：枚举与 Flag 长度（127）、模板长度（120）。

`ExerciseController` 仍是 TODO，因此不暴露虚构的练习题 API；比赛的 practiceMode 可支持结束后练习，具体资格由原站决定。
