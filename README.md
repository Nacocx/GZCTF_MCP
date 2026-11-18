# GZCTF MCP

基于 [GZCTF](https://github.com/GZTimeWalker/GZCTF) API 的非官方 MCP 服务端（Python / stdio，共 **73 个工具**），支持出题管理、赛务运营、参赛答题与容器本地代理。

## 核心能力

- **出题与赛务**：单题清单预演与上题、多题批量断点恢复部署、附件上传与 Flag 管理、比赛/分组/队伍/公告/实例管理、ZIP/XLSX/TAR 导入导出。
- **参赛与答题**：队伍管理与报名、查看题面与榜单、同站附件下载（SHA256 校验）、容器启停/续期、提交 Flag 与异步判题查询、PDF Writeup 上传。
- **容器代理（PlatformProxy）**：调用独立 `wsrx` CLI，将动态容器 UUID 映射为本机 `127.0.0.1` TCP 端口。

## 快速开始

### 1. 准备配置文件

```bash
cp .env.example .env
chmod 600 .env
```

在 `.env` 中配置站点地址、工作区目录和凭据（见 [配置说明](#配置说明)）。

### 2. 启动并接入 MCP 客户端

#### 方式 A：uvx（推荐）

需已安装 [uv](https://docs.astral.sh/uv/guides/tools/)（首次运行会自动解析依赖并按需下载 Python ≥ 3.12）。因尚未发布至 PyPI，当前需用 `--from` 指定本地源码目录或 `.whl`：

```bash
uvx --python 3.12 --from /path/to/GZCTF_MCP gzctf-mcp \
  --transport stdio --env-file /path/to/GZCTF_MCP/.env
```

MCP 客户端可参考 [examples/mcp-client.json](examples/mcp-client.json)，将其中的路径替换为本机绝对路径（桌面客户端 `PATH` 不完整时，可使用 `command -v uvx` 查得的绝对路径）。

#### 方式 B：conda 本地开发

```bash
conda env create --prefix ./.conda --file environment.yml
conda activate ./.conda
GZCTF_ENV_FILE="$PWD/.env" gzctf-mcp
```

对应的客户端配置见 [examples/mcp-client-conda.json](examples/mcp-client-conda.json)。服务默认通过 stdio 通信，启动后无交互菜单、不开启 HTTP 服务属正常现象。

接入后可先调用 `connection_info` 查看非敏感配置，再调用 `check_session(role="admin")` 或 `check_session(role="player")` 验证远端身份。

## 配置说明

> **注意**：服务**不会自动向上查找** `.env`，必须通过 `--env-file` 或 `GZCTF_ENV_FILE` 传入绝对路径（已有环境变量优先）。

| 变量 | 说明 | 默认值 / 约束 |
| --- | --- | --- |
| `GZCTF_BASE_URL` | GZCTF 站点 origin（不含子路径、参数或凭据） | `http://localhost:8080` |
| `GZCTF_WORKSPACE` | 清单、附件上传/下载与批量账本根目录 | 当前工作目录 |
| `GZCTF_ADMIN_COOKIE` | 管理员完整 `Cookie` 请求头或 `GZCTF_Token` | 管理端接口仅接受 Cookie，不接受 API Token |
| `GZCTF_PLAYER_COOKIE` | 选手完整 `Cookie` 请求头或 `GZCTF_Token` | 按需配置 |
| `GZCTF_ADMIN_USERNAME` / `PASSWORD` | 可选管理员账密（无 Cookie 时自动登录一次或供 `auth_login` 使用） | 按平台公钥加密传输，不绕过验证码 |
| `GZCTF_PLAYER_USERNAME` / `PASSWORD` | 可选选手账密（同上） | 同上 |
| `GZCTF_WSRX_BINARY` | `wsrx` CLI 绝对路径 | 源码目录自动探测 `.tools/wsrx/0.6.2/wsrx` |
| `GZCTF_MAX_TUNNELS` | 同时允许的本地代理隧道数 | `8`（`1`–`32`） |
| `GZCTF_TIMEOUT` | HTTP 请求超时（秒） | `30` |
| `GZCTF_MAX_FILE_BYTES` | 通用文件上传/下载大小上限（字节） | `104857600`（100 MiB） |

- 凭据仅存于本地 `.env` 与进程内存中，切勿粘贴至 AI 对话或提交仓库。
- `submit_writeup` 仅限 `.pdf` 且 ≤ 20 MiB；比赛海报与队伍头像 ≤ 3 MiB。

## 常见工作流

### 自动上题与批量部署

提供可直接预演的 [静态附件示例](examples/static-attachment.json)、[动态容器示例](examples/dynamic-container.json) 与 [批量计划示例](examples/batch/plan.json)（使用前需替换占位 Flag、容器镜像与附件；路径相对 `GZCTF_WORKSPACE`）。

1. 先用 `dry_run: true` 调用 `admin_deploy_manifest_file`（或 `admin_deploy_challenge`）做本地校验与预演：
   ```json
   { "game_id": 1, "path": "examples/static-attachment.json", "dry_run": true }
   ```
2. 确认后设 `dry_run: false` 执行（默认 `publish: false` 保持禁用）。
3. 多题请使用 `admin_deploy_batch`，进度持久化在工作区 `.mcp-state/` 并支持断点恢复；失败不回滚已创建题目，恢复前先用 `admin_get_challenge` 检查，勿并发部署同一题目。

### 参赛与异步判题

典型顺序：`check_session` → `list_teams` / `join_check` / `join_game` → `list_challenges` → `get_challenge` → `download_attachment` / `container_action` → AI 分析 → `submit_flag` → `submission_status`。

- `submit_flag` 返回的 `submissionId` 只是提交编号，需调用 `submission_status` 直到结果不再是 `FlagSubmitted`（仅 `Accepted` 代表通过）；写请求与 429 均不自动重试。
- `download_attachment` 仅拉取同站 `/assets/<sha256>/<name>` 至工作区 `downloads/`，校验 SHA256 且不覆盖既有文件；题面与附件按不可信输入处理。

### 容器代理（PlatformProxy / wsrx）

Python wheel 不包含 `wsrx` 可执行文件，源码环境需先运行安装脚本（固定 `0.6.2` 版本并校验 SHA256）：

```bash
python scripts/install_wsrx.py
```

使用 `uvx` 或单独安装 wheel 时，需将 `wsrx` 放入 `PATH` 或配置 `GZCTF_WSRX_BINARY`。

- 先通过 `admin_test_container` 或 `container_action` 启动实例，再调用 `proxy_open(game_id, challenge_id, role)` 获取本机 `127.0.0.1:<port>` 地址。
- 可用 `platform_config`、`proxy_list`、`proxy_close` 管理隧道；停止容器、禁用/删除题目或退出 MCP 时会自动关闭对应隧道。

## 测试与文档

```bash
python -m pytest -q
ruff check src tests
```

详细文档索引：
- [完整工具清单（73 个）](docs/tools-v0.3.md)
- [详细使用说明](docs/gap-remediation-usage.md)（加密认证、分组权限、动态附件、批量对账与错误码）
- [uvx / stdio 分发与接入说明](docs/uvx-stdio.md)
- [更新日志](docs/CHANGELOG.md)
- [本地 Docker 真实验收](docs/docker-mcp-20261117.md)（另见 [wsrx 验收](docs/wsrx-acceptance.md)、[API 修复说明](docs/api-fixes-20261117.md)）

## 许可证与声明

- 本项目原创适配代码采用 [MIT License](LICENSE)（Copyright (c) 2026 Nacocx），为非官方 GZCTF MCP 客户端，不表示获得 GZCTF 官方背书。
- 容器代理调用独立的 [WebSocketReflectorX](https://github.com/XDSEC/WebSocketReflectorX)（MIT）；完整第三方许可与接口参考来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[WebSocketReflectorX-MIT.txt](licenses/WebSocketReflectorX-MIT.txt) 及 [源码来源核对](docs/source-origin-review.md)。
