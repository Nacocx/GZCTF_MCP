# GZCTF MCP · DeepSeek Harness 插件

把本仓库的 GZCTF MCP 服务（stdio）接入 DeepSeek Harness（下称 dsh）。插件本身不实现工具，只声明一条
`@deepseek-ai/dsh-mcp-client` 连接：dsh 启动后拉起本仓库的 `bin/launch.sh`，把 MCP 服务的 73 个工具
注册为 `mcp__gzctf__<tool>`，与内置工具一样可直接调用。仅支持 macOS/Linux（启动器用 `/bin/sh`）。

## 组成

| 文件 | 作用 |
| --- | --- |
| `package.json` | bundle 清单：`dsh.bundle.patch` 指向本目录的 patch，并导出 locale 与图标 |
| `cordis.patch.yml` | 插入一条 `mcp-client` 配置行：`serverName: gzctf`、stdio、启动 `bin/launch.sh` |
| `bin/launch.sh` | 启动器：定位仓库根目录、校验 `.env`、挑选可用的 Python，然后启动 MCP 服务 |
| `locale/*.json` | bundle 卡片显示的标题、说明与详情文档路径（中英双语） |
| `docs/` | 详情页的一句话说明与配图 |
| `icon.svg` | bundle 图标（36×36，原创） |

卡片下的插件行由 `@deepseek-ai/dsh-mcp-client` 提供，标题沿用上游的 `MCP client`，图标是面板默认图形；
bundle 的标题与图标只出现在 bundle 卡片上。

## 前置条件

- 已配置 `.env`（`GZCTF_BASE_URL`、Cookie 等），可参考 `.env.example`。
- 一个能 `import gzctf_mcp, mcp` 的 Python 环境：仓库自带的 `.conda`、`pip install -e .`，或 [uv](https://docs.astral.sh/uv/)。
- 仅 macOS/Linux。

先验证服务本身可用：

```bash
.conda/bin/python -m gzctf_mcp --version
```

## 安装

1. 在 dsh「插件」页点 **Add plugin**，在输入框粘贴本目录的**绝对路径**（例如
   `/Users/nax/Code/GZCTF_MCP/dsh-plugin`）；用内置管理能力等价于 `install_bundle` + 该路径。
2. 安装返回 applied 后，调用 `mcp__gzctf__connection_info` 查看非敏感配置，再调用
   `mcp__gzctf__check_session` 验证身份。工具通常直接出现在当前会话；没有出现时新开会话或重启 dsh。

bundle 以 `link:` 指向本目录，**移动仓库后必须从新路径重新安装**；`GZCTF_MCP_HOME` 只影响启动器路径，
修不好失效的链接。

默认启动器路径按 `/Users/nax/Code/GZCTF_MCP` 写入 patch。仓库换了位置时：改 `cordis.patch.yml` 的默认路径，
或在**启动 dsh 前**设置 `GZCTF_MCP_HOME`（从 Finder/launchd 启动的应用可能不继承 shell 导出的变量），
然后从新路径安装。

## 启动链路

```text
dsh (mcp-client, stdio)
  └─ /bin/sh -c "…→ exec dsh-plugin/bin/launch.sh"
       └─ <python> -m gzctf_mcp --transport stdio --env-file <仓库>/.env
```

启动器按顺序取第一个可用项（可用 = 能 `import gzctf_mcp, mcp`）：

1. `GZCTF_MCP_PYTHON`（显式指定，失败即报错，不静默回退）
2. `<仓库>/.conda/bin/python`
3. `PATH` 中的 `python3`
4. `uvx --python 3.12 --from <仓库> gzctf-mcp`

前三种用 `exec` 把启动器替换成服务进程；`uvx` 分支保留 uvx 作为父进程，并要求 uvx 在 dsh 进程的 `PATH` 中。

启动器会先 `cd` 到仓库根目录，因此相对路径的 `GZCTF_WORKSPACE` 与相对 `GZCTF_ENV_FILE` 都相对仓库根目录解析，
而不是 dsh 进程的工作目录。

## 配置

以下变量由 **dsh 进程的环境**提供（写进 `.env` 不生效）：

| 变量 | 说明 |
| --- | --- |
| `GZCTF_ENV_FILE` | `.env` 路径；默认 `<仓库>/.env`，文件不存在时启动器直接报错 |
| `GZCTF_MCP_HOME` | 仓库根目录；patch 用它拼出启动器路径 |
| `GZCTF_MCP_PYTHON` | 指定 Python 解释器，覆盖自动探测 |

站点地址与凭据仍在 `.env` 中（`GZCTF_BASE_URL`、`GZCTF_ADMIN_COOKIE`、`GZCTF_PLAYER_COOKIE` 等，见仓库 README）。
凭据不会进入插件配置或对话，只在 MCP 进程内存中。

## 停用与卸载

停用 bundle 卡片（`GZCTF MCP bridge`）或它下面的 `MCP client` 行都会移除全部 `mcp__gzctf__*` 工具；
卸载 bundle 会一并删除该行。行状态只显示阶段，失败原因在 Host 日志里。

## 限制

- 73 个工具的名称、说明与输入 schema 会进入每次请求，token 占用明显；不用时请停用。
- 单次工具调用超时 180 秒（`toolCallTimeoutMs`）；批量部署、导入导出仍可能更久，超时后先用
  `admin_batch_status` 对账再继续。
- `proxy_*` 需要本机 `wsrx`：源码环境可用 `scripts/install_wsrx.py`；uvx 或全局安装时请设置
  `GZCTF_WSRX_BINARY` 指向可执行文件，否则只有容器代理相关工具报错。
- 连接断开后按 500 ms 起、上限 30 s 退避重连；连续失败 10 次会注销全部工具并停止重连，直到重载配置或重启。
- 启动失败时（`failOnStartupError: true`）插件行显示 `failed`：修好 `.env` 或 Python 后重载/重启，必要时停用再启用。
- 题面与附件按不可信输入处理（MCP 服务自身的 instructions 已声明）。
