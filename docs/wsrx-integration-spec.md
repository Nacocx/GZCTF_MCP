# WebSocketReflectorX 集成规格 v0.2

日期：2026-10-21；状态：实现与本地真实验收完成，见 wsrx-acceptance.md。承接 API 审查 A8，仅实现平台代理与相应验证，不擅自扩展到其他待修复项。

## 目标与依据

调用上游原版 wsrx CLI，将 GZCTF PlatformProxy 容器入口转为本机 TCP 地址。上游 https://github.com/XDSEC/WebSocketReflectorX ，本次固定安装/验收版本 0.6.2；源码研究 revision ccddb64658e2e2ca0b0c08e0fdfe90bd94f81a56。GZCTF 代理协议由 InstanceEntry/getProxyUrl/ProxyController 确认。

## 设计契约

- 新增 platform_config、proxy_open、proxy_list、proxy_close 工具；普通模式返回 direct 入口，PlatformProxy 模式启动受管 wsrx connect 子进程。
- proxy_open 按明确 role=player/admin 查询当前题目的实例，UUID 只能来自配置站点已认证响应。player 使用 /api/proxy/{uuid}，admin 测试实例使用 /api/proxy/noinst/{uuid}，HTTPS 自动转 wss。
- 不接受任意代理 URL，不将 Cookie 传给 wsrx；GZCTF 原生代理按实例 UUID 验证。UUID/代理 URL 视作连接凭据，不返回到一般列表或日志。
- 固定监听 127.0.0.1；默认由 wsrx 选择端口 0，从真实启动输出获得端口；不预占用再释放随机端口。stdout/stderr 管道消费，不污染 MCP 协议。
- 拒绝无效/无实例/错误身份、端口冲突；同一实例重复调用复用现有连接。数量默认限制 8。CLI 缺失时给出安装提示，其他工具不受影响。
- 代理开通前 GET 原站代理路径确认有效，返回只承诺 local listening，不把它当成远端业务可达。真实 HTTP/TCP 收发由验收验证。
- 显式关闭、容器停止、题目禁用/删除和 MCP 退出时停止本进程管理的隧道。不操作外部桌面 wsrx、用户既有隧道或任意 PID；退出/异常时 terminate→kill 限时回收。
- GZCTF_WSRX_BINARY 显式配置路径，未设置时在源码 checkout 优先发现安装器生成的项目内 CLI，否则从 PATH 查找 wsrx；GZCTF_MAX_TUNNELS 控制上限。不自动安装/联网下载二进制。
- 提供显式安装脚本：固定 0.6.2、GitHub 官方 CLI 资产、已确认 SHA256 校验、仅提取可执行文件与保留 MIT 文件到被忽略的 .tools。macOS arm64/x64、Linux x64 glibc/musl、Windows x64 资产可选择；不宣称所有平台已实测。

## 许可证与分发

保留上游版权声明和完整 MIT 许可（licenses 与 Python 包内 _licenses），在 THIRD_PARTY_NOTICES.md 记录项目、版本、来源和集成方式。wheel/sdist 包含该声明及许可。独立安装的可执行文件不放进 Python wheel，分发二进制时还需保留其上游依赖的许可。第三方 MIT 不自动决定本项目自身许可证；本次不替用户选择主项目许可证，也不复制 GZCTF 代码。

## 验收

定向测试：路径/role/UUID/mode、缺失 CLI、端口冲突、并发重复开通、列表关闭、MCP 清理与不泄露凭据。真实测试：启用专用本地 Docker PlatformProxy 站点、构建夹具题目，经真实 MCP→wsrx→GZCTF WebSocket→容器 HTTP 收发；覆盖管理员测试实例与参赛实例，仅测试本地连接，不提交答案。验证关闭后端口消失及 MCP 退出无遗留进程。用户远端站点不操作。

## 实现记录

采用 connect CLI 与标准库监督进程，通过父进程存活管道处理异常退出；不依赖 GUI 或用户既有 daemon。42 项定向测试通过（含父进程强制终止后的监听消失），8 项真实 PlatformProxy HTTP 链路检查通过；真实测试只在本地独立夹具执行。
