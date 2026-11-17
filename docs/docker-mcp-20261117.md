# 本地 Docker / MCP 真实验收

日期：2026-11-17。21 组真实服务检查通过，平台保留运行。

## 实例

- 地址：<http://127.0.0.1:18082>，仅监听本机回环。
- Compose 项目：`gzctf-mcp-verify-20261117`，数据库/文件卷与原 `gzctf-mcp-local` 独立。
- GZCTF 实际版本：1.9.0，arm64；沿用仓库固定镜像 `gztime/gzctf@sha256:a87b286f0807cf29d04305a5e2e9b1f8dc0bb660ff98d3e1bf7e032bc969e2fc`，源码标签 revision `72ac811097b1b64eb5484f09bbcd4451aba60cc0`。
- PostgreSQL：16-alpine。验收结束时两个容器均为 healthy。
- API 加密开启；本地专用夹具允许注册、禁用验证码及通用限流。
- 管理员：`Admin`；密码在 `.local-test/compose.env` 的 `ADMIN_PASSWORD`。凭据文件位于忽略目录，不进入报告。

## 通过项目

通过真实 MCP stdio 初始化并发现 73 个工具。两组验收共 21 项：

| 范围 | 实际验证 |
| --- | --- |
| 认证 | 管理员/选手使用环境账密、官方 API 加密登录，身份检查与登出 |
| 上题与文件 | 创建/更新/发布、附件路径上传、同 hash 独立引用、重复恢复不增引用、删除一题后另一题仍可下载、未上传引用的复用被拒绝 |
| 分组与审核 | 命名分组、邀请码、Pending→Accepted、单题可见性覆盖、分组删除与退赛规则 |
| 比赛与赛务 | 读改写保留字段、两个并发 patch 均生效、截止设定与清空、公告、事件、提交与实例查询 |
| 队伍 | 创建、修改保留 bio、邀请码查询/轮换、头像上传及删除 |
| 判题 | 本地临时比赛提交 3 次：静态题错误答案→WrongAnswer、正确答案→Accepted、动态容器注入答案→Accepted |
| 实际容器 | 管理员测试容器和选手题目容器分别启动、从宿主访问 HTTP、确认动态 Flag 注入、停止 |
| 导入导出 | 官方比赛 ZIP 导出/重新导入、榜单/提交 XLSX、PDF Writeup 上传与 TAR 导出 |
| 批量恢复 | 动态附件按位置记录引用，MCP 进程重启后恢复且文件引用计数不增加 |
| 清理 | 比赛、队伍、批量题目、独立文件与本次图片引用清理 |

专项脚本使用本机临时 HTTP 中继向真实 GZCTF 转发请求。它只在服务已处理后主动丢弃指定的三次响应：附件读回 GET、题目 DELETE、动态 Flag 追加 POST。验证了部署保留恢复 ID、删除后重试继续清理、重启后不重复追加 Flag/上传引用。中继不伪造 API 数据，验收后关闭。

## 联调发现及修复

1. **时间精度误报。** GZCTF 响应的 Unix 毫秒会丢弃输入 ISO 时间的微秒尾数，比赛更新的严格读回比较误报冲突。现在将 datetime 比较统一到毫秒精度，并保留真正不同字段的冲突检查。补充回归后，3 项相关本地检查通过；Writeup 设置及后续真实流程重新通过。
2. **夹具公钥生效等待不足。** 首次启动后启用加密，旧脚本只等待 5 秒，早于公钥可见。轮询上限改为 30 秒，只重读配置；初始化时先覆盖本次报告，避免启动失败后误读历史成功记录。
3. **脚本分页参数过期。** 将旧脚本的 `admin_files(count=500)` 改为当前工具允许的 `100`；本次独立夹具文件数量低于一页。

## 最终状态

管理员读回：比赛 0、队伍 0、题目实例 0、文件 0。两个重复测试留下的 avatar/poster 图片记录经真实 MCP 按引用删除，合计 5 次引用删除后消失。测试注册账号保留在本地夹具；平台、数据库及空资源状态保留供后续检查。

没有操作用户远端平台，也没有改项目原 `.env`。本次使用固定的 1.9.0 镜像，不代表已运行 1.9.1。未等待七天会话期限测试自然 Cookie 滑动续期，也未重跑 PlatformProxy 模式；这些与已完成的本地流式 Cookie 回归、Default 容器连通检查区分记录。

## 继续使用与复跑

已生成并通过真实 stdio 验证管理员配置：`.local-test/verify-mcp.env`，权限 0600。配置指向当前本地实例，工作区为 `.local-test/manual-workspace`。

在仓库根目录启动本地 MCP：

```bash
.conda/bin/python -m gzctf_mcp --env-file "$PWD/.local-test/verify-mcp.env"
```

这是 stdio 服务器，需由 MCP 客户端连接，手动运行会等待标准输入。

复跑本次两个脚本：

```bash
.conda/bin/python scripts/live_gap_acceptance.py
.conda/bin/python scripts/live_api_fixes_acceptance.py
```

专项容器镜像为 `gzctf-mcp-fixture:verify-20261117`，通过当前 `deploy/local/Dockerfile.challenge` 构建。脚本会创建并清理专用比赛/队伍；平台图片引用可能需要在确认归属后另外清理。

停止平台并保留数据卷：

```bash
docker compose -p gzctf-mcp-verify-20261117 \
  --env-file .local-test/compose.env \
  -f deploy/local/compose.yaml -f deploy/local/compose.encrypted.yaml down
```

再次启动使用相同命令，将 `down` 替换为 `up -d --wait`。

完整非敏感证据：[验收 JSON](records/docker-mcp-20261117.json)。开发与验证范围：[规格](docker-mcp-20261117-spec.md)。本次变更的运行代码、回归和验收脚本 Ruff 检查通过。
