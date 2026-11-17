# uvx / stdio 接入与验收

版本 0.3.1，2026-10-22。规格见 [uvx-stdio-spec.md](uvx-stdio-spec.md)。

## 启动

项目此前已经使用 stdio；本次补齐 uvx 安装入口、可选显式传输参数及配置，不改动 73 个平台工具。推荐客户端配置：[examples/mcp-client.json](../examples/mcp-client.json)。保留 conda 配置：[mcp-client-conda.json](../examples/mcp-client-conda.json)。

```json
{
  "mcpServers": {
    "gzctf": {
      "command": "/opt/homebrew/bin/uvx",
      "args": [
        "--python", "3.12",
        "--from", "/Users/nax/Code/GZCTF_MCP",
        "gzctf-mcp", "--transport", "stdio"
      ],
      "env": {
        "GZCTF_ENV_FILE": "/Users/nax/Code/GZCTF_MCP/.env"
      }
    }
  }
}
```

这些是本机路径，换机器需要替换。客户端宿主进程必须能执行 uvx；桌面客户端 PATH 不完整时使用绝对路径。uvx 会自行管理隔离环境和依赖缓存，无需激活开发 conda。首次安装可能下载 Python 和依赖，客户端应给足启动时间。开发和本地测试仍使用项目 conda。

也可直接运行：

```bash
uvx --python 3.12 --from /Users/nax/Code/GZCTF_MCP gzctf-mcp \
  --transport stdio --env-file /Users/nax/Code/GZCTF_MCP/.env
```

省略 `--transport` 仍默认 stdio。支持 `--help`、`--version`，不接受 HTTP 传输参数。进程等待 MCP stdin 是正常状态。安装日志、服务器日志和参数错误使用 stderr，stdout 只传 MCP JSON-RPC。

## 配置与分发

在 `.env` 中明确填写 `GZCTF_WORKSPACE` 的绝对路径、平台地址及角色凭据。客户端启动工作目录未必是源码目录；不会从 uvx 缓存或父目录自动发现 `.env`。`--env-file` 显式传参或 `GZCTF_ENV_FILE` 环境变量均可使用；已有环境变量优先于 `.env` 中的同名字段。`--env-file` 指向不存在文件时提前退出。

当前未发布 PyPI，也无已发布 Git 安装地址，故不承诺裸 `uvx gzctf-mcp`。可通过 `--from` 指定本地源码，或把 wheel 复制到另一台机器使用：

```bash
uvx --python 3.12 --from /absolute/path/gzctf_mcp-0.3.1-py3-none-any.whl \
  gzctf-mcp --transport stdio --env-file /absolute/path/gzctf.env
```

wheel 不包含用户 `.env`、参考源码、conda 环境或 wsrx 程序；包含独立适配代码及既有 MIT 第三方声明。PlatformProxy 功能仍需安装 WebSocketReflectorX CLI 并在用户配置中设置 `GZCTF_WSRX_BINARY` 为绝对路径，或使它处于 PATH；uvx 缓存安装不会自动找到源码中的 `.tools`。源码更新后可用 uvx 的 `--refresh-package gzctf-mcp` 刷新安装缓存。未来发布到 PyPI/Git 后才可使用相应的包名/固定版本/固定 commit 安装源。

本次依据并核对 [uv 官方工具说明](https://docs.astral.sh/uv/guides/tools/) 的 `--from`、隔离环境、Python 选择和工具参数转发语义。

## 验收

环境：macOS Apple Silicon，uv 0.12.21；uvx 自动选择/下载 Python 3.12.14。源码与 wheel 各通过一轮真实 uvx 隔离安装与 MCP 子进程通信。测试运行目录是临时工作区，不是源码目录；每轮覆盖：

- initialize 握手、73 工具发现；
- connection_info 工具调用，读回显式 `.env` 的假平台地址和工作区；
- 缺失认证返回 MCP isError，未发起平台 HTTP 请求；
- gzctf://workflow 资源发现。

可复现命令：

```bash
.conda/bin/python -m pip wheel . --no-deps --no-build-isolation -w .local-test/dist
.conda/bin/python scripts/uvx_acceptance.py \
  --source . --source .local-test/dist/gzctf_mcp-0.3.1-py3-none-any.whl
.conda/bin/python -m pytest tests/test_cli.py tests/test_stdio.py \
  tests/test_contract.py::test_examples_and_game_dates -q
```

结果：**2 种来源 uvx 实测通过，4 项定向检查通过**。脱敏机器记录见 [uvx-stdio-2026-10-22.json](records/uvx-stdio-2026-10-22.json)。本次仅修改打包/启动与文档，不重复平台 Docker 验收；没有访问远端、提交 Flag、修改 `.env` 或发布/推送。Windows/Linux uvx 尚未真机验收。
