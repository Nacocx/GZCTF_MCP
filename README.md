# GZCTF MCP

让 AI 通过 MCP 管理 GZCTF 题目和参与比赛：**73 个工具**，支持清单上题、附件与 Flag、容器、提交及异步判题。Python 实现，默认 stdio，可接入支持本地 MCP 的客户端。

基于本地 [GZCTF](https://github.com/GZTimeWalker/GZCTF) commit `cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296` 的控制器和请求模型开发；参考目录 `GZCTF/` 已被 `.gitignore` 忽略。MCP 使用[官方 Python SDK 的受维护 v1 分支](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)，约束 `<2`，避免 SDK 大版本不兼容。

v0.3 补齐附件安全恢复、API 加密、环境账密登录、分组权限与审核、比赛/队伍/赛务管理、批量持久化部署和 ZIP/XLSX/TAR 导入导出。详见 [使用说明](docs/gap-remediation-usage.md)、[完整工具清单](docs/tools-v0.3.md) 和 [本地验收](docs/gap-remediation-acceptance.md)。

2026-11-17 修复附件引用消费、部署与清理恢复、并发比赛更新及流式 Cookie 续期；公开附件默认匿名下载。新绑定使用 `fileHash` 时须有当前会话中未消费的上传引用，推荐清单使用 `attachmentPath`。见 [修复说明](docs/api-fixes-20261117.md)。

2026-11-17 本地 Docker 真实验收：21 组检查通过，涵盖加密判题、实际题目容器、文件引用及故障恢复；独立测试平台监听 `127.0.0.1:18082`。访问、管理员配置、复跑和停止方法见 [本次验收记录](docs/docker-mcp-20261117.md)。

## 使用 uvx（推荐）

v0.3.1 支持通过 uvx 直接安装并启动 stdio MCP。已安装 [uv](https://docs.astral.sh/uv/guides/tools/) 后，无需先激活 conda 或手动安装本项目依赖：

```bash
uvx --python 3.12 --from /Users/nax/Code/GZCTF_MCP gzctf-mcp \
  --transport stdio --env-file /Users/nax/Code/GZCTF_MCP/.env
```

MCP 客户端直接采用 [examples/mcp-client.json](examples/mcp-client.json)，修改其中的 uvx、项目和 `.env` 绝对路径；其中 uvx 路径是本机实测的 `/opt/homebrew/bin/uvx`，其它机器请运行 `command -v uvx` 获取。`.env` 中显式指定 `GZCTF_WORKSPACE` 为用户文件所在目录。首次启动会解析/下载依赖，可能自动下载 Python，日志写 stderr；stdout 留给 MCP 协议。

包尚未发布到 PyPI，因此当前需要 `--from` 指定本地源码目录或 wheel，不能把裸 `uvx gzctf-mcp` 当作已验证的安装方式。完整分发与验收说明见 [uvx / stdio 接入](docs/uvx-stdio.md)。

## conda 开发安装

```bash
cd /Users/nax/Code/GZCTF_MCP
conda env create --prefix ./.conda --file environment.yml
conda activate ./.conda
# 如果环境已创建：
python -m pip install -e '.[dev]'
cp .env.example .env
chmod 600 .env
```

编辑本地 `.env` 的站点地址、工作区与 Cookie。环境中仅安装 Python 依赖，无需 Node。

## 身份配置

当前源码的 `EditController` 和附件上传接口使用 **RequireAdmin**，不会接受 API Token；参赛接口使用 **RequireUser**，还会读取当前用户、队伍和报名状态。请分别设置：

- `GZCTF_ADMIN_COOKIE`：已登录管理员账号的完整 Cookie 请求头值。
- `GZCTF_PLAYER_COOKIE`：已登录参赛账号的完整 Cookie 请求头值。

可按用途只配其中一种。用户自行正常登录站点，从已认证请求中取得 Cookie；如 Cookie 被拆分为多段，应保留所有段及 `;` 分隔。不要把 Cookie 粘贴到 AI 对话或提交到仓库。服务只在进程内持有会话，不保存登录状态，不实现绕过验证码的登录。过期后更新 `.env` 并重启 MCP 进程。

`GZCTF_BASE_URL` 必须是站点 origin（例如 `https://ctf.example.org`），不接受子路径、查询或 URL 内嵌凭据。上传文件必须在 `GZCTF_WORKSPACE` 内，默认限制 100 MiB；Writeup 另有限制 PDF / 20 MiB。`.env` **不会自动查找加载**，请显式传入绝对路径：

```bash
GZCTF_ENV_FILE="$PWD/.env" python -m gzctf_mcp
# 同样可运行：GZCTF_ENV_FILE="$PWD/.env" gzctf-mcp
```

进程等待 MCP 客户端通过 stdin/stdout 通信，启动后没有交互菜单是正常现象。默认不会启动 HTTP 服务。

## 接入 MCP 客户端

参见 [examples/mcp-client.json](examples/mcp-client.json)，将 `mcpServers.gzctf` 合并到客户端的 MCP 配置中，并替换为自己的绝对路径。推荐 uvx 配置；保留的 conda 入口见 [examples/mcp-client-conda.json](examples/mcp-client-conda.json)。两种方式均直接使用 stdio，不启动 shell。

接入后先调用 `connection_info` 查看非敏感配置，再调用 `check_session(role="admin")` 或 `check_session(role="player")` 验证远端身份。

## 自动上题

提供可直接预演的 [静态附件示例](examples/static-attachment.json) 与 [动态容器示例](examples/dynamic-container.json)。示例 Flag 仅用于演示；容器镜像是占位地址，必须替换成平台可拉取的真实镜像。动态 Flag 模板最终由 GZCTF 校验，容器需按上游约定读取 `GZCTF_FLAG`。

可向 AI 发送：

> 使用 GZCTF MCP 检查管理员身份，列出比赛。在 game_id=1 中先预演 examples/static-attachment.json，检查配置后执行上题，保持题目禁用。

实际工具调用：

```json
{
  "game_id": 1,
  "path": "examples/static-attachment.json",
  "dry_run": true
}
```

调用 `admin_deploy_manifest_file`；确认计划后同参数设置 `dry_run=false`。也可将 JSON 直接传给 `admin_deploy_challenge` 的 `manifest` 参数。所有附件路径相对于工作区，不相对于清单文件。

执行顺序为创建禁用题目、配置题面/分数/容器、上传绑定附件、添加 Flag，最后仅在 `publish=true` 时发布。预演只做本地校验，不会检查远端权限、镜像可用性、Flag 模板生成质量或服务端资源。单个清单对应一道题；多题可使用 `admin_deploy_batch`，提供预演、持久化进度和显式恢复。

失败会返回 `completed=false`、`stage`、`challengeId` 和恢复说明；**不会回滚或删除已有题目**。先用 `admin_get_challenge` 检查，再带同一 `challenge_id` 恢复。恢复仅允许名称和类型匹配的禁用题目，查询现有 Flag，避免重复追加；如已有 Flag 的附件不同则停止。创建请求超时时可能已经创建成功，应先列题目找 ID；发布超时也可能已经发布，应先检查状态。不要在多客户端中并发部署同一道题，流程不提供跨进程锁或远端事务。

`DynamicAttachment` 使用每个 Flag 自己的 `attachmentType/fileHash/remoteUrl`，不能绑定公共附件。可以直接在每个 Flag 中写 `attachmentType:"Local"` 和 `attachmentPath` 自动上传，也可预先上传后填写 hash；需指定统一 `configuration.fileName`。`DynamicContainer` 使用 `flagTemplate`，不手动加 Flag。

底层工具也可单独调用：`admin_create_challenge` 创建题壳，`admin_update_challenge` 更新字段，`admin_add_flags` 配 Flag，`admin_set_attachment` 绑定附件。题型创建后不可更改。`isEnabled=false` 会停止该题已有容器，删除工具为永久删除。

## 自动答题

> 使用参赛身份查看 game_id=1 的队伍与题目；必要时启动容器、下载附件，分析题目并提交得到的 Flag，再查询判题结果。

典型顺序：`check_session` → `list_teams` / `join_check` / `join_game` → `list_challenges` → `get_challenge` → `download_attachment` / `container_action` → AI 分析 → `submit_flag` → `submission_status`。

服务提供平台操作能力；解题推理和执行脚本由 AI 及其已有工具完成，不内置解题模型、容器镜像构建或镜像推送。参赛账号仍需先在平台注册，可用 `save_team` 创建队伍；`join_game` 支持分组 ID/唯一名称并读回审核状态，时间与权限由 GZCTF 执行。

提交结果中的 `submissionId` **只是提交编号**；`FlagSubmitted` 表示排队中，只有 `Accepted` 才代表通过。判题查询由客户端适度间隔调用，不自动重提 Flag；429 返回等待提示，其他写请求失败也不自动重试。

附件下载仅支持题面返回的同站 `/assets/<sha256>/<name>` 路径，写到工作区 `downloads/`，校验 SHA256、不覆盖现有文件。外站附件链接由用户另行取得，服务不会携带 Cookie 请求外站。题面和附件按不可信数据处理。

## 文档与验证

- [开发规格](docs/spec.md)
- [工具与接口映射](docs/tools.md)
- [验收记录](docs/acceptance.md)
- [更新日志](docs/CHANGELOG.md)

```bash
python -m pytest -q
ruff check src tests
```

验证范围包括 httpx 模拟接口契约、上题失败恢复、文件边界、身份隔离及真实子进程 MCP stdio 握手。已通过本地 Docker GZCTF 1.9.0 的 14 项真实链路检查，详见下方复跑方式与验收记录。其他部署和未覆盖场景仍需单独验证。

## Docker 真实测试

本地已运行 GZCTF `1.9.0.0` + PostgreSQL，实际通过 14 项检查（上题、报名、错/对 Flag 异步判题、静态/动态附件、动态 Flag 容器、Writeup、恢复与删除）。站点地址为 `http://127.0.0.1:18080`。

复跑命令：

```bash
conda activate ./.conda
python scripts/local_setup.py
docker compose --env-file .local-test/compose.env -f deploy/local/compose.yaml up -d --wait
docker build -f deploy/local/Dockerfile.challenge -t gzctf-mcp-fixture:local deploy/local
python scripts/live_acceptance.py
```

脚本创建独立测试账号、队伍和比赛，通过真实 MCP 子进程调用工具。每次运行新增一组测试数据，保留平台数据供检查。账号密码在 `.local-test/compose.env`，最近一次账号 Cookie 会话配置在 `.local-test/mcp.env`，均被忽略；不会覆盖用户 `.env`。测试时关闭验证码、API 密码加密和通用限流，不影响生产平台设置。容器操作自身冷却仍保留。

Compose 为本地测试挂载 Docker socket；平台端口仅绑定本机，PostgreSQL 不映射宿主端口。测试镜像返回注入的测试 Flag，仅用于验证分发与判题。GZCTF 官方镜像版本与参考源码 commit 不同，不能将这次测试声称为参考 commit 完整构建验收。容器续期、StaticContainer、验证码、API 加密提交等覆盖边界见验收记录。

已停止测试题目容器；停止站点并保留数据：

```bash
docker compose --env-file .local-test/compose.env -f deploy/local/compose.yaml down
```

非敏感测试报告：[Docker 真实记录](docs/records/docker-live-2026-10-21.json)。完整规划：[Docker 测试规格](docs/docker-test-spec.md)。

## 远端管理员专项测试

已按授权对用户站点执行仅上题测试，9 项真实检查通过，临时题目、隐藏测试比赛及源附件均已删除，答案提交次数为 0。结果见 [远端验收记录](docs/remote-admin-test-spec.md)。

`scripts/remote_admin_smoke.py --execute` 是该指定站点的专项脚本，使用本地 `.env` 的管理员 Cookie，目标固定为本次授权网址；它接受完整 Cookie 头或单独的 GZCTF_Token 值。它不修改 `.env`，只在 MCP 子进程中设置本站点地址。不要将这个专项脚本当作任意站点的通用测试命令。

## PlatformProxy / WebSocketReflectorX

从 0.2.0 起，MCP 可以调用原版 **wsrx CLI 0.6.2**，将平台提供的容器 UUID 转为本机 TCP 地址，不需要打开桌面 App，也不需要在 GZCTF 服务器上运行 Agent。

先显式安装官方 CLI（固定版本、SHA256 校验）：

```bash
python scripts/install_wsrx.py
```

源码 checkout 中会自动发现 `.tools/wsrx/0.6.2/wsrx`（Windows 为 wsrx.exe）；也可在 PATH 安装，或在 `.env` 指定 `GZCTF_WSRX_BINARY=/absolute/path/to/wsrx`。Python wheel 不包含 wsrx 二进制，单独安装 wheel 时需设置 PATH 或该环境变量。现有 `GZCTF_ENV_FILE` 加载方式不变。

新增工具：

| 工具 | 用途 |
| --- | --- |
| `platform_config(role)` | 查询 portMapping、容器默认寿命和续期窗口 |
| `proxy_open(game_id, challenge_id, role, local_port=0)` | 给已启动的实例开通本地隧道；端口 0 自动选择，同实例复用 |
| `proxy_list()` | 查看本 MCP 进程管理的隧道和监听状态 |
| `proxy_close(proxy_id)` | 关闭本地隧道；远端题目容器继续运行 |

管理员测试实例：先调用 `admin_test_container(action="start")`，再调用：

```json
{
  "game_id": 1,
  "challenge_id": 2,
  "role": "admin",
  "local_port": 0
}
```

参赛实例则先调用 `container_action(action="start")`，使用 `role="player"`。proxy_open 返回 `proxyId`、`localAddress`（例如 127.0.0.1:45123）、`localHost`、`localPort` 和 `expiresAt`。AI 或本地工具随后通过该地址使用 HTTP、nc 或相应题目协议。

服务从当前题目读取真实实例 UUID，构造同站 `/api/proxy/{uuid}` 或管理员测试用 `/api/proxy/noinst/{uuid}`，HTTPS 自动使用 WSS。上游 GZCTF 按 UUID 验证代理访问；不会将 Cookie 放进子进程参数、URL 或环境。UUID/代理 URL 是实例连接凭据，不在普通隧道列表及 httpx 信息日志中输出。

隧道只绑定 `127.0.0.1`，默认最多 8 个，可用 `GZCTF_MAX_TUNNELS` 在 1–32 内调整。`state=listening` 只表示本地监听就绪；wsrx 在 TCP 客户端接入时才连接远端，仍需实际请求确认题目可达。容器刚启动时，题目服务可能尚未监听，应按题目协议等待/检查，不能因此重复创建容器或提交答案。

停止对应容器、通过 MCP 禁用/删除题目或退出 MCP，会关闭相应隧道。另有父进程存活管道，MCP 被强制终止时也能触发子进程回收；macOS 上已实测强制终止。其他程序直接停止容器时，本地监听可能继续存在，应显式 proxy_close。Default 端口映射返回直接地址，不创建隧道。

### 本地真实代理验收

使用独立 Compose 项目与 18081 端口，保持原 18080 夹具不变：

```bash
python scripts/local_setup.py
docker compose -p gzctf-mcp-proxy --env-file .local-test/compose.env -f deploy/local/compose.yaml -f deploy/local/compose.proxy.yaml up -d --wait
docker build -f deploy/local/Dockerfile.challenge -t gzctf-mcp-fixture:local deploy/local
python scripts/live_proxy_acceptance.py
# 停止此专用代理夹具，保留数据：
docker compose -p gzctf-mcp-proxy --env-file .local-test/compose.env -f deploy/local/compose.yaml -f deploy/local/compose.proxy.yaml down
```

8 项真实检查已通过：管理员与选手隧道实际 HTTP 收发、连接复用、显式关闭、双身份独立隧道、容器停止自动清理、MCP 退出清理；没有提交答案。详情见 [验收记录](docs/wsrx-acceptance.md)。已实测 macOS arm64 的 ws 模式及 WSS URL 构造，Windows/Linux 二进制和真实 WSS/TLS 服务尚未实测。

### 第三方许可

WebSocketReflectorX 使用 MIT 许可证。本项目保留了完整的 [MIT 原文及版权声明](licenses/WebSocketReflectorX-MIT.txt)，并将它和 [第三方声明](THIRD_PARTY_NOTICES.md) 同时打包到 wheel/sdist 中。安装器保留哈希校验后的原始上游 CLI 归档。

这项许可允许相应使用和整合；分发副本或实质性部分时要保留版权与许可文本，分发二进制也应核对其传递依赖的声明。上游 MIT 不自动决定本项目自身许可；本次没有代替用户选择主项目许可证。

## v0.3 本地加密与缺口验收

```bash
docker compose -p gzctf-mcp-encrypted --env-file .local-test/compose.env \
  -f deploy/local/compose.yaml -f deploy/local/compose.encrypted.yaml up -d --wait
.conda/bin/python scripts/live_gap_acceptance.py
```

脚本只访问 `127.0.0.1:18082`，用本地管理员 API 启用加密并等待公钥发布，再经真实 MCP stdio 测试 12 组流程。不提交 Flag、不操作用户远端；finally 删除测试比赛和队伍。保留脱敏报告到 `.local-test/gap-report.json`。验证码、Windows/Linux 真机等边界见本次验收说明。

## 许可证与来源

本项目原创适配代码采用 [MIT License](LICENSE)，Copyright (c) 2026 Nacocx。本项目是非官方 GZCTF MCP 客户端，不表示获得 GZCTF 官方背书。

GZCTF 与 WebSocketReflectorX 的代码、名称及其他第三方内容遵循各自条款，主项目 MIT 不替代它们的许可证。wsrx 独立 CLI 的 MIT 原文已保留，未随 Python 包捆绑其可执行程序。接口及加密兼容实现参考来源见 [第三方声明](THIRD_PARTY_NOTICES.md) 和 [源码来源核对](docs/source-origin-review.md)。
