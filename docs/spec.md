# GZCTF MCP v0.1 开发规格

日期：2026-10-21。状态：P1–P3 已实现并通过本地契约与 MCP stdio 验证；另已通过 14 项本地 Docker 真实联调，版本与范围见 acceptance.md。

## 目标与范围

提供 Python MCP stdio 服务，使 AI 通过 GZCTF 官方 HTTP 接口管理比赛、创建与配置题目、上传附件和 Flag、发布题目；以参赛者身份查看比赛、报名、读取题目、管理容器、提交 Flag 并查询异步判题结果。AI 自行分析题目，本服务不内置解题模型或执行任意攻击代码。

## 源码基线与边界

只读参考本地 `GZCTF/`，commit `cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296`；整个目录被 gitignore，不复制和修改上游实现。接口以 `src/GZCTF/Controllers/{Edit,Game,Assets,Account}Controller.cs`、`Models/Request/` 和 `Utils/Enums.cs` 为准。独立适配服务，版本差异应明确报错。

## 设计

- Python 3.12，conda 环境；官方 MCP Python SDK，httpx，Pydantic；仅 stdio，stdout 只输出协议。
- 管理员与选手独立 HTTP 会话。管理员与选手均使用有真实用户身份的 Cookie。当前上题控制器标记 RequireAdmin，不允许 Token；API Token 不等价于管理员或参赛账号。
- 凭据通过环境变量提供，工具参数中不传密码、Token 或 Cookie。原站登录密码有加密与验证码流程，本期不实现伪造明文登录；用户登录后导入 Cookie。
- 请求固定在配置站点下，不跟随重定向；限时请求；不自动重试写操作；429 返回等待提示。网络超时明确提示结果不确定，需查询后再重试。
- 工具使用明确参数、类型约束与 MCP annotations。管理题目字段对齐上游 camelCase，拒绝未知字段。
- 高层上题：校验完整清单和附件 → 创建禁用题目 → 配置 → 上传绑定附件 → 添加 Flag → 可选发布。默认预演不写入，失败返回阶段与已创建题目 ID，支持指定 ID 继续配置；不会自动删除用户题目或自动重复添加 Flag。
- 文件只能读取配置的工作区根目录内的普通文件，限制上传大小。附件下载只允许同站相对路径，输出到工作区 downloads，不覆盖文件。
- 提交返回 submission ID；状态查询返回上游 AnswerResult，不能将 ID 当成 Accepted。容器接口采用上游路由。

## 实现步骤

1. P1：配置、认证隔离、HTTP 错误和数据模型。
2. P2：管理员/选手 MCP 工具、清单上题和附件处理。
3. P3：示例配置、使用说明、定向接口模拟测试与真实 MCP stdio 握手测试。

## 验收

- `GZCTF/` 与凭据、conda 环境均被忽略；所有修改留在功能分支。
- 安装后可运行 `gzctf-mcp` 与 `python -m gzctf_mcp`，客户端可列举及调用工具。
- 模拟验证方法、路由、请求体、multipart、身份隔离、异步判题、限流错误、路径越界和失败恢复。
- 未提供部署地址与凭据时，不宣称通过真实 GZCTF、数据库、容器平台端到端验收。

## 实现结果

已交付 31 个工具、1 个工作流资源、清单示例与客户端配置。23 项定向测试通过；Ruff、pip check 和 wheel 构建通过。完整结果及待验收边界见 `acceptance.md`。

P4 已完成：独立 Docker 平台、随机本地凭据与真实 MCP 客户端集成脚本，真实上题/答题/容器与 Writeup 验收通过。
