# uvx / stdio 接入规格

日期：2026-10-22；版本：0.3.1。

## 目标

通过 `uvx --from <本地项目或 wheel> gzctf-mcp --transport stdio` 启动现有工具，无需用户先激活开发 conda 环境。保持默认 stdio 和现有 Python 启动方式兼容，不改变平台操作与认证语义。

## 实施

1. 增加轻量 CLI，支持默认 stdio、显式 `--transport stdio`、`--env-file`、`--version` 与 `--help`；协议 stdout 不输出启动提示。
2. 默认 MCP 配置改用 uvx 本地源码安装；保留 conda 配置。记录 wheel 与未来 Git/PyPI 分发方式，未发布不能声称裸 `uvx gzctf-mcp` 可用。
3. 使用真实 uvx 进程验证源码与 wheel 两种安装源，执行 initialize、73 工具发现、connection_info、资源发现和缺失认证的协议错误。不访问实际平台、不提交 Flag。

## 边界

uvx 管理运行缓存，开发继续用项目 conda。工作区及 .env 显式使用绝对路径；uvx 缓存不是用户数据目录。WebSocketReflectorX 仍是独立可执行程序，缓存安装需要 PATH 或 GZCTF_WSRX_BINARY，不自动下载或运行外部 CLI。保留 MIT 第三方声明，不发布或推送仓库。
