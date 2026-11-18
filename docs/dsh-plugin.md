# DeepSeek Harness 插件（dsh）

服务版本 0.3.1，bundle 1.0.0，2026-11-19。插件目录：[dsh-plugin](../dsh-plugin/)，说明见 [dsh-plugin/README.md](../dsh-plugin/README.md)。

本仓库的 MCP 服务保持独立进程（Python / stdio），dsh 侧只增加一个 bundle：它插入一条
`@deepseek-ai/dsh-mcp-client` 配置行，由 dsh 拉起 `dsh-plugin/bin/launch.sh`，并把 73 个工具注册为
`mcp__gzctf__<tool>`。因此不需要把任何工具逻辑改写成 JS，Python 侧升级后重载插件或重启 dsh 即可生效。

## 结构

```text
dsh-plugin/
├── package.json        # bundle 清单：dsh.bundle.patch、locale 与 icon 导出
├── cordis.patch.yml    # 插入 mcp-client 行（serverName: gzctf、stdio、启动 launcher）
├── bin/launch.sh       # 定位仓库、校验 .env、挑选 Python，启动 MCP 服务
├── locale/{en,zh}.json # bundle 卡片的标题 / 说明 / 详情文档路径
├── docs/               # DETAIL.md、DETAIL.zh.md 与同一张配图 preview.svg
└── icon.svg            # 36×36 原创图标（旗标）
```

bundle 卡片的标题与图标来自本目录；卡片下的插件行由上游 `@deepseek-ai/dsh-mcp-client` 提供，
标题显示为 `MCP client`、图标为面板默认图形，这是预期的。

## 安装

1. 准备服务端环境（任选其一）：
   - 仓库自带的 conda 环境：`conda env create --prefix ./.conda --file environment.yml`，再 `pip install -e .`；
   - 全局 `pip install -e .`；
   - 安装 `uv`（首次启动由 `uvx` 解析依赖）。
2. 准备 `.env`：`cp .env.example .env && chmod 600 .env`，填写 `GZCTF_BASE_URL` 与 Cookie。
3. 安装 bundle：dsh「插件」页 → **Add plugin** → 粘贴 `dsh-plugin/` 的**绝对路径**；用内置能力时等价于
   `plugin_manager` 的 `install_bundle` + 该目录绝对路径。
4. 验证：调用 `mcp__gzctf__connection_info`（非敏感配置），再调用
   `mcp__gzctf__check_session(role="admin" 或 "player")`。工具通常直接出现在当前会话；未出现时新开会话或重启。

安装会把本目录以 `link:` 方式链接进 profile，**移动仓库后必须从新路径重新安装**。默认启动器路径按
`/Users/nax/Code/GZCTF_MCP` 写入；换位置时改 `dsh-plugin/cordis.patch.yml` 的默认路径，或在启动 dsh 前设置
`GZCTF_MCP_HOME`（Finder/launchd 启动的 dsh 可能不继承 shell 环境变量，此时改文件更可靠）。

## 启动链路

```text
dsh (mcp-client, stdio)
  └─ /bin/sh -c "dir=${GZCTF_MCP_HOME:-/Users/nax/Code/GZCTF_MCP}; exec $dir/dsh-plugin/bin/launch.sh"
       └─ <python> -m gzctf_mcp --transport stdio --env-file <仓库>/.env
```

- patch 里的命令先检查启动器是否存在，缺失时输出 `launcher not found … set GZCTF_MCP_HOME` 并退出 1，避免只看到
  `/bin/sh: … No such file or directory`。
- 启动器用脚本自身位置推导仓库根目录，`cd` 到仓库根后 exec，因此相对路径的 `GZCTF_WORKSPACE` / `GZCTF_ENV_FILE`
  都相对仓库解析。
- Python 选择顺序：`GZCTF_MCP_PYTHON` → `<仓库>/.conda/bin/python` → `PATH` 的 `python3` →
  `uvx --python 3.12 --from <仓库> gzctf-mcp`。候选项必须能 `import gzctf_mcp, mcp`；显式指定的解释器失败时报错而不回退。
  前三种用 `exec` 替换为服务进程，`uvx` 分支保留 uvx 作为父进程且要求 uvx 在 dsh 进程的 `PATH` 中。
- `failOnStartupError: true`：启动失败会让插件激活失败并保留错误，而不是注册空工具集。

## 配置

| 变量 | 作用 |
| --- | --- |
| `GZCTF_ENV_FILE` | `.env` 路径；默认 `<仓库>/.env`，缺失时启动器直接报错；相对路径按仓库根解析 |
| `GZCTF_MCP_HOME` | 仓库根目录；patch 用它拼出启动器路径。默认 `/Users/nax/Code/GZCTF_MCP` |
| `GZCTF_MCP_PYTHON` | 指定 Python 解释器 |

这三个变量由 **dsh 进程的环境**提供，写进 `.env` 不生效。

插件行的其他配置：`toolCallTimeoutMs: 180000`（批量部署、导入导出可能超过默认 60 s）、
`failOnStartupError: true`。需要改动时在 profile 的 `cordis.patch.yml` 里按 `id` 覆盖；`config` 是整体替换而非深合并，
需重写全部字段：

```yaml
- id: gzctf-mcp
  config:
    serverName: gzctf
    transport: stdio
    command: /bin/sh
    args:
      - -c
      - exec "/srv/GZCTF_MCP/dsh-plugin/bin/launch.sh"
    toolCallTimeoutMs: 180000
    failOnStartupError: true
```

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 插件行 `failed` | 启动失败：先修 `.env` / Python 环境，再重启 dsh（或停用该 bundle 后重新启用）。行只显示阶段，详细错误在 Host 日志 |
| 日志提示 `launcher not found at …` | `GZCTF_MCP_HOME` 或 patch 默认路径不对 |
| 日志提示 `missing env file …` | 缺 `.env`，或 `GZCTF_ENV_FILE` 指向了不存在的文件 |
| 日志提示 `no Python with gzctf-mcp and mcp installed` | 创建 `.conda` 并 `pip install -e .`、全局安装，或安装 uv；也可用 `GZCTF_MCP_PYTHON` 指定 |
| 首次启动很慢 | 走到 `uvx` 分支时会下载 Python 与依赖；先手动跑一次 `uvx --from . gzctf-mcp --version` 预热 |
| 工具调用超时 | 长任务先用 `admin_batch_status` / `submission_status` 对账；需更长预算时覆盖 `toolCallTimeoutMs` |
| `proxy_*` 报错 | 缺少 `wsrx`：源码环境运行 `python scripts/install_wsrx.py`；uvx/全局安装时设置 `GZCTF_WSRX_BINARY` |
| 仓库移动后启动失败 | bundle 是 `link:`，需按新路径重新安装；同时更新 patch 默认路径或设置 `GZCTF_MCP_HOME` |
| 连续失败 10 次后工具消失 | 重连预算耗尽，重载配置或重启 dsh |

## 验证记录

- `install_bundle` 返回 `application: applied`，profile 的 `dsh.profile.bundles` 与 `link:` 依赖都指向本目录。
- 同一会话内实际调用 `mcp__gzctf__connection_info` 成功（返回 baseUrl、workspace、Cookie 就绪、wsrx 路径），
  说明 stdio 链路与凭据加载可用；`tools/list` 返回 73 个工具。
- 启动器故障路径已验证：缺 `.env`、错误的 `GZCTF_MCP_PYTHON`、错误的 `GZCTF_MCP_HOME` 都给出明确 stderr 并退出 1。
- 未验证：Plugin Manager 卡片/行的渲染效果与图标显示（当前环境无浏览器控制），以及 dsh 由 GUI 启动时的环境变量继承。

## 限制

- 73 个工具的名称、说明与 schema 会进入每次模型请求，token 成本固定；不用时停用该 bundle 或行。
- 插件不改变服务端行为：Cookie 仍在 `.env`，写操作与 429 仍不自动重试，题面与附件仍按不可信输入处理。
- 仅 POSIX：patch 通过 `/bin/sh` 启动脚本，Windows 不支持。
