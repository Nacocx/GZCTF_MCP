# 0.1.0 验收记录

日期：2026-10-21。环境：macOS arm64、项目内 conda Python 3.12.15；MCP SDK 1.30.0、httpx 0.28.1、Pydantic 2.14.1。

## 已验证

| 项目 | 结果与证据 |
| --- | --- |
| 源码契约 | 逐项检查上游控制器、请求模型、权限过滤器、枚举及附件序列化；基线 commit 见 spec |
| 环境安装 | conda 创建 `.conda/`，editable pip 安装成功 |
| MCP 运行 | 真实 Python 子进程 stdio initialize、tools/list、tools/call、resources/list，31 个工具可发现 |
| MCP 错误 | 缺少 Cookie 和非法 ID 通过协议返回 isError，stdout 可正常解析 |
| 答题 | 模拟 POST 返回提交编号，单独查询 pending 状态，未把提交编号当作 Accepted |
| 身份隔离 | 模拟验证 admin / player 请求使用各自 Cookie，不串用 |
| 上传 | 模拟验证 assets 的 files 字段、Writeup 的 file 字段与 PDF MIME，非 PDF 本地拒绝 |
| 上题 | 预演无网络；配置、上传、Flag、发布顺序；Flag 写入后超时，按 ID 恢复且不再次创建或重复添加 Flag |
| 恢复比较 | DynamicAttachment 用附件公开 url 读取 hash，不依赖 JsonIgnore 的内部字段 |
| 文件边界 | 路径越界、符号链接越界、外站 URL、下载不覆盖、大小限制和 SHA256 校验失败清理 |
| 请求错误 | 401 / 403 / 429 / 302 / 500 不暴露响应体、不跟随重定向、不重试写操作；网络超时提示结果不确定 |
| 容器与报名 | 模拟验证 start / extend / stop、管理员测试容器和报名路由 |
| 示例和创建比赛 | 清单示例通过模型验证；创建使用明确的带时区时间、默认隐藏 |

执行命令与最终数量见本文件末尾验证输出记录。测试只覆盖本服务的关键契约，不运行上游大规模 .NET 测试。

## 初始版本的待验收项（现已完成本地 Docker 联调）

初始交付时未提供运行中的实例，当时未验收：真实登录会话、报名审核、比赛时间与分组限制、附件存储、判题队列、Docker/Kubernetes 容器生命周期、镜像拉取、真实 Flag 注入和题目可解性。该初始状态已由下方 Docker 真实验收记录更新；本地参考源码仍未修改。

用户配置后建议先在测试比赛中执行：

1. `check_session(admin)` 与 `check_session(player)`。
2. 使用静态示例预演，然后创建禁用题目，核对题面、附件和 Flag。
3. 在测试比赛中发布，以参赛者读取、下载、提交示例 Flag 并查询 Accepted。
4. 替换动态容器示例镜像，检查测试容器与参赛容器，验证模板和注入的 Flag 一致。

## 交付边界

- 支持 stdio；未提供远程 HTTP 托管和多人共享 MCP 会话。
- 需要用户已有账号/队伍及有效 Cookie；不承诺不同版本的私有 API 自动兼容。
- 高层工作流非远端原子事务；失败保留状态，必须检查后恢复。禁止同题并发部署。
- 只提供比赛创建与读取，已有比赛完整编辑、队伍创建、自动登录、镜像构建推送不在本期范围。
- 不执行推送、PR 创建或部署；修改位于本地 `feat/gzctf-mcp` 分支。

## 最终验证输出

```text
python -m pytest -q
23 passed in 0.63s

ruff check src tests
All checks passed!

python -m pip check
No broken requirements found.

python -m pip wheel --no-deps --no-build-isolation . -w dist
Successfully built gzctf-mcp
```

wheel：`dist/gzctf_mcp-0.1.0-py3-none-any.whl`，SHA256：`14d790f68e81a6021034e0b430c53ba710574254eccc6e9f4c4f0be213e86055`。已检查压缩包含服务源码及入口，不包含 GZCTF 克隆、凭据或测试目录。dist 被忽略，可重新构建；本文记录的是本次构建产物。

`git check-ignore` 已验证 GZCTF/、.conda/、.env 与 .env.local 被忽略，.env.example 可纳入版本管理；本地参考克隆内容未修改。

## Docker 真实联调 — 2026-10-21 15:42（Asia/Shanghai）

**14 项检查通过，真实 Docker GZCTF + PostgreSQL + MCP stdio，无接口模拟。**

- 平台：GZCTF `1.9.0.0`，官方 arm64 镜像摘要 `a87b286f0807cf29d04305a5e2e9b1f8dc0bb660ff98d3e1bf7e032bc969e2fc`。
- 镜像 revision：`72ac811097b1b64eb5484f09bbcd4451aba60cc0`，与参考克隆 `cc12f65...` 有差异；本次证明该发布镜像的兼容性，未构建参考 commit 的同版本镜像。
- Docker Engine `29.4.2`、PostgreSQL `16-alpine`，独立 Compose 项目和存储卷。
- 地址：`http://127.0.0.1:18080`。站点保留运行，题目测试容器均已停止。
- 测试比赛 ID `1`，静态附件题 `1`，动态附件题 `2`，动态容器题 `3`。
- 错误提交 ID `1` → WrongAnswer，正确静态提交 ID `2` → Accepted；动态附件与动态容器各提交得到 Accepted。
- 完成管理员/选手 Cookie 身份验证、队伍创建与报名、预演不写入、清单上题发布、附件下载与 SHA256 校验、榜单公告、测试容器/参赛容器启动与销毁、真实动态 Flag 注入、PDF Writeup 上传读回、禁用题目恢复不重复追加 Flag、删除草稿 Flag 与题目。
- 账号注册测试夹具遵守原站用户名长度 15、队名长度 20 的限制；未修改 MCP 核心实现或上游源码。

执行：`python scripts/local_setup.py` → Compose `up -d --wait` → 构建 `deploy/local/Dockerfile.challenge` → `python scripts/live_acceptance.py`。

原始非敏感结果保存在 [records/docker-live-2026-10-21.json](records/docker-live-2026-10-21.json)，本机详细日志在被忽略的 `.local-test/live.log`。凭据与会话仅在 `.local-test/compose.env` 和 `.local-test/mcp.env`，均不进入报告。

本次采用本地 API 加密与验证码关闭配置、自动审核测试比赛；未覆盖 SMTP/验证码、开启 API 加密时的 Flag 提交、人工审核分组、远端 Kubernetes/S3、多队伍并发、容器到期续期，以及 StaticContainer 类型专门链路。不会将本次测试扩大为这些场景已验收。

## 用户部署站点的上题专项验收 — 2026-10-21

`https://covteam-ctf.nacocx.top` 的 9 项管理员检查通过：身份、独立隐藏未来比赛、预演不写入、上传附件/哈希、题目与 Flag/附件/分数配置读回、附件内容下载、恢复不重复 Flag、增删测试 Flag、发布/禁用与分数更新。

测试比赛 2 与测试题目 16 均删除（GET 404），测试源附件的管理清单和新 URL 也确认不存在。原有比赛数保持 1。本次无报名、无答案提交、无容器操作，不代表远端判题及容器场景已验证。登录使用已有 Cookie，不涉及账密登录。

详见 [远端测试规格与结果](remote-admin-test-spec.md) 与 [非敏感机器记录](records/remote-admin-20261021T075146Z-e4279149.json)。新增清理回归检查后，本地合计 27 项测试通过。

## 0.2.0 平台代理验收补充

WebSocketReflectorX 集成已完成，当前 35 个工具。42 项本地测试与 8 项真实 PlatformProxy 链路检查通过，独立 CLI 的 MIT 原文和第三方声明已随 wheel/sdist 分发。详见 [wsrx-acceptance.md](wsrx-acceptance.md)。此补充不替代之前其他功能的未覆盖边界。

## 0.3.0 缺口修复验收补充

当前为 73 个工具。50 项本地检查与 12 组加密 Docker/真实 MCP stdio 验收通过，记录见 [gap-remediation-acceptance.md](gap-remediation-acceptance.md)。本轮无 Flag 提交、无远端改动；前面的历史测试边界以各自版本为准。
