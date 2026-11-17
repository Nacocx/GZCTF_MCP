# WebSocketReflectorX / PlatformProxy 验收

日期：2026-10-21（Asia/Shanghai）。版本：GZCTF MCP 0.2.0，35 个工具。

## 实测环境

- macOS arm64，conda Python 3.12.15，官方 wsrx CLI 0.6.2。
- CLI 来自官方 `wsrx-cli-0.6.2-macos-aarch64.zip`，固定 SHA256 校验后安装在项目内 `.tools`；不使用桌面 App 或共享 daemon。
- GZCTF 1.9.0.0，固定官方镜像 `gztime/gzctf@sha256:a87b286f0807cf29d04305a5e2e9b1f8dc0bb660ff98d3e1bf7e032bc969e2fc`。
- 独立 `gzctf-mcp-proxy` Docker Compose 项目，PostgreSQL 与 GZCTF 配置为 PlatformProxy，仅绑定 `127.0.0.1:18081`。
- Docker 题目夹具使用最小 Python HTTP 服务返回注入的测试 Flag，用于验证字节收发；没有提交答案。

## 真实链路：8 项通过

2026-10-21 16:13:55–16:14:07，使用真实 MCP stdio 子进程与真实上游 CLI：

| 检查 | 结果 |
| --- | --- |
| 查询原站 portMapping=PlatformProxy | 通过 |
| 管理员 testContainer → wsrx → /api/proxy/noinst → 容器 HTTP 收发 | 通过 |
| 同实例重复开通复用同一个本地监听 | 通过 |
| 显式关闭隧道，端口消失，容器继续运行 | 通过 |
| 参赛实例 → wsrx → /api/proxy → 容器 HTTP 收发 | 通过，无答案提交 |
| 管理员/选手隧道独立，列表不返回远端能力 URL | 通过 |
| 停止参赛容器自动关闭关联本地隧道 | 通过 |
| MCP 退出后剩余管理员隧道自动回收 | 通过 |

初次真实探测遇到 Docker 已运行但夹具 HTTP 服务尚未绑定端口，GZCTF 明确记录 ConnectionRefused。验收脚本仅对只读 HTTP GET 作有限等待后验证，未重试创建容器或提交答案。proxy_open 的 listening 状态没有被当作业务服务已经就绪。

测试比赛与题目均已删除，题目容器停止，本项目受管代理进程剩余 0。专用 18081 夹具已停止并移除服务容器，数据卷保留以便复核；原 18080 夹具未改动。机器记录见 [records/wsrx-live-2026-10-21.json](records/wsrx-live-2026-10-21.json)。

## 定向测试：42 项通过

`python -m pytest -q`：42 passed。新增检查涉及：

- 普通 Default 模式无需 CLI，缺失 CLI 的安装提示，非法 UUID、空实例、未知映射模式拒绝。
- 真子进程的动态回环端口、并发复用、端口冲突、上限、关闭后端口释放。
- HTTPS→WSS 与管理员/参赛路由匹配，Cookie 不进入子进程参数/环境。
- httpx 代理 URL 日志过滤。
- 通过 MCP 停止参赛/管理员容器、禁用或删除题目时清理受管代理。
- 强制杀死管理父进程后，监督进程检测管道 EOF 并终止 CLI，端口消失。
- 其余已有 HTTP 契约、清理和 stdio 检查继续通过。

部分生命周期测试用可控的假 CLI 进程与模拟 HTTP 响应验证监督行为；上面 8 项实际收发使用的是官方下载的真实 wsrx，与这些测试分开记录。

## 许可与分发验证

上游 MIT 原文与 0.6.2 tag 的 LICENSE 逐字一致；SHA256 为 `6b1cf3d4baa48a8f2e2b9642798cebeb21a452153d67aab81c85aae64495d3f5`。原文包含 `Copyright (c) 2023 XDSEC` 和完整许可条款。

- 根目录 licenses/ 与 THIRD_PARTY_NOTICES.md 保留原文、来源、版本及集成方式。
- wheel 的包内 _licenses 和 dist-info/licenses 均包含原文与第三方声明；sdist 同样包含。
- 安装器保留 SHA256 校验后的上游原始归档；Python wheel 未打包 wsrx 可执行文件或 GZCTF 源码。
- sdist 包含安装脚本、测试 conftest、示例及 Docker 配置，原始凭据、.tools 和 .local-test 不进入分发包。
- 主项目自身许可证仍待用户决定，第三方 MIT 不替代该选择。

## 边界

真实收发在 macOS arm64 + 本地 WS 平台完成；WSS 的地址构造和参数已验证，但没有对用户远端平台做 WSS/TLS 实测。Windows/Linux 官方资产可由安装器选择，进程回收实现兼顾 Windows，但不能据此宣称已经通过这些平台运行验收。

本次仅完成审查 A8 及客户端配置查询；附件恢复、请求体加密、分组 CRUD 等其他审查项仍待实施。用户远端站点未操作，答案提交次数为 0。
