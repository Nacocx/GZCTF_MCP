# GZCTF MCP 官方 API 核查

日期：2026-11-17；MCP 版本：0.3.1。

当前实现的主要路由、HTTP 方法和请求字段基本对齐官方 API。应优先修复附件引用生命周期、异常恢复、并发更新和会话续期，随后再补功能。

后续状态：R1–R6 已落实代码修复及定向回归，见 [修复结果](api-fixes-20261117.md)。本文和原始探针保留为修复前快照。

## 核查基准

- 官方入口：[Scalar](https://gzctf.gzti.me/scalar#description/introduction)，页面实际引用 [OpenAPI JSON](https://gzctf.gzti.me/openapi.json)。
- OpenAPI SHA256：`436320427f537eeca5c193a6568b203eb562b469c397268d7c040f3e172897fc`；`info.version=v1`，这个标签不是 GZCTF 发布版本。
- 官方源码核对到 [`7e61deefdd3d5232c9dfaabcc7cd856932f774ed`](https://github.com/GZTimeWalker/GZCTF/commit/7e61deefdd3d5232c9dfaabcc7cd856932f774ed)，对应 v1.9.1 发布提交。已检查其与本地参考 `cc12f65…` 的差异；本报告引用的 Edit/Assets 控制器、Game 模型、文件/题目仓库、时间转换器和权限过滤器均未变更。Identity 配置新增 Passkey，Cookie 滑动续期逻辑未变更。
- 本项目尚无 Git 提交，全部文件为未跟踪状态，当前分支为 `feat/gzctf-mcp`；核查快照在记录中保存了各运行源码文件的 SHA256。

| 项目 | 当前数量 |
| --- | ---: |
| 注册 MCP 工具 | 73 |
| 官方 HTTP 操作 | 131 |
| 直接或组合调用覆盖的操作 | 76 |
| 未接入操作 | 55 |

映射按 HTTP 方法和路径核对，忽略路由大小写与占位符名称；包含代理 GET/升级入口，不包含隐式自动登录在各工具下的重复列举。覆盖率不是运行正确率。相较仓库中的 2026-10-21 官方快照，增加了 8 个 Passkey 操作，没有删除旧操作。完整映射见 [机器可读记录](records/api-review-20261117.json)。

## 已对齐的部分

- `ChallengeUpdateModel` 的全部 20 个官方字段已覆盖；MCP 额外提供 `clearDeadline`。Flag、附件、分组创建和队伍配置字段与官方模型匹配。题目创建使用标题、类型、分类，计分等配置走更新接口，符合官方控制器的实际创建逻辑。
- 比赛更新先读取完整对象，再合并显式 patch，避免单次局部修改清空其他字段；但并发时仍有 R3。
- 上传附件使用 multipart `files`，Writeup、海报、头像、导入使用 `file`；Writeup 的 PDF 类型、扩展名和 20 MiB 上限与源码一致。二进制导出不再强行解析 JSON。
- Flag 提交和密码登录调用了 API 加密适配；提交结果按编号继续查询，未将 submission ID 当成解题成功。本次加密、提交状态和 multipart 定向检查通过。
- ISO 时间字符串可由官方转换器接受，不能因为 OpenAPI 描述为整数就判定请求格式错误；响应采用 Unix 毫秒。题目截止时间清空使用 epoch 哨兵，与源码一致。参考[时间转换器](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Utils/JsonSerializerContext.cs)。
- Cookie 鉴权是正确方向：上题控制器使用 `RequireAdmin`，并非 `RequireAdminOrToken`。不能因为官方提供 Token 管理接口就把这些工具统一改成 Bearer。参考[权限过滤器](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Middlewares/PrivilegeAuthentication.cs)。
- 同一道题恢复时，相同附件已跳过重复绑定并校验下载哈希；旧报告中的这一缺陷已修复。跨题复用哈希仍有下述独立风险。

## 需要修复的问题

### R1 · P1 · 跨题复用 fileHash 没有管理文件引用

位置：`src/gzctf_mcp/workflow.py:52`、`:151`、`:187`，`src/gzctf_mcp/server.py:316`。

触发方式：上传一次文件取得 hash H，将 H 直接用于两道题的公共附件，或用于多个动态 Flag 的本地附件，随后删除或替换其中一个引用。

MCP 的 `fileHash` 路径直接绑定现有文件，没有为新增消费者建立上传引用。上游 `UpdateAttachment`、`AddFlags` 只查询文件并建立附件关系；引用计数在上传时增加，删除附件时递减，计数为 1 时会删除实际文件。因此单次上传、多次绑定会出现引用计数不足，删除一处可能使另一处附件失效。依据：[题目仓库](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Repositories/GameChallengeRepository.cs)、[文件仓库](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Repositories/BlobRepository.cs)。

这是源码推导出的生命周期缺陷，本轮未在真实 GZCTF 实例重现删除后的下载结果。它不同于“同一题、同一 hash 恢复时跳过 POST”，后者应继续保留。

建议：把上传返回的引用与消费位置纳入部署账本；新绑定要求独立上传引用或通过受控流程补建引用；无本地文件且无法证明有可消费引用时拒绝直接复用。记录每个 Flag/公共附件的引用，而不只记录 hash。补一项真实实例检查：两题相同内容，删除其中一题，另一题使用新 URL 下载仍成功。

### R2 · P2 · 附件读回网络异常丢失部署恢复结果

位置：`src/gzctf_mcp/workflow.py:37`、`:199`，`src/gzctf_mcp/server.py:59`。

`verify_local_attachment` 直接调用 `session.stream()`，没有将 `httpx.RequestError` 转成 `GZCTFError`；`deploy` 的异常列表和工具包装器也没有捕获这种错误。创建和绑定已成功后，读回遇到网络超时会直接退出，调用方拿不到约定的 `completed=false`、`stage`、`challengeId` 和资源清单。

本地复现：模拟题目 9 已创建、附件已绑定，再令资产 GET 抛出 `ReadTimeout`，实际得到原始异常，没有部署结果对象。

建议：将流式请求纳入统一客户端封装，规范异常和 Cookie 处理；部署捕获规范化异常并保留已知 ID、阶段和账本。恢复先检查已存在的题目，不能重新创建。

### R3 · P2 · 并发比赛 patch 会互相覆盖

位置：`src/gzctf_mcp/management.py:107`。

官方比赛 PUT 是整对象更新。两个并发工具调用可能都读取旧设置，一个改标题，另一个改隐藏状态，然后各自回写完整快照；后写入者撤销前一个修改。末尾 GET 也未与本次 patch 比对，两个调用都可以返回成功。官方更新行为见 [Game.Update](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Models/Data/Game.cs)。

本地复现：并发 `{title: "changed"}` 和 `{hidden: false}`，两个调用完成，最终为 `title=changed, hidden=true`，隐藏状态修改丢失。

建议：同一 MCP 进程按比赛 ID 串行化读、合并、写、读回的完整操作，并检查本次修改字段。锁只能解决本进程并发；跨进程或网页同时编辑仍需明确冲突策略，上游目前接口未提供可直接使用的版本条件参数。

### R4 · P2 · 流式请求没有切换到续期 Cookie

位置：`src/gzctf_mcp/client.py:223`、`:297`、`:329`，`src/gzctf_mcp/workflow.py:37`。

环境 Cookie 被放入固定请求头。普通 `request()` 收到新 `GZCTF_Token` 会删除旧请求头并启用 cookie jar；下载、导出和附件验证绕过了这一步。HTTPX 虽已存入新 Cookie，后续请求仍被固定旧头覆盖。官方启用了滑动续期，见 [Identity 配置](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Extensions/Startup/IdentityExtension.cs)。

本地复现：第一次导出响应设置 `GZCTF_Token=renewed`，cookie jar 已更新，第二次导出仍发送 `GZCTF_Token=old-admin`。持续使用流式入口时可能在旧 Cookie 到期后丢失会话。

建议：统一处理所有 HTTP 响应的 Cookie 更新，或初始化时就将配置 Cookie 正确载入 cookie jar；同时覆盖失败响应携带续期 Cookie 的情况。

### R5 · P2 · 批量清理不能恢复已成功但响应丢失的删除

位置：`src/gzctf_mcp/batch.py:253`。

题目删除成功、响应超时或进程在保存账本前退出时，状态仍是 `complete`。再次清理会重复 DELETE 已不存在的题目，遇到 404 就中止，后续题目无法处理；`admin_batch_reconcile` 也要求读到现有题目，不能解决这个状态。

本地复现：题目 9 已从模拟服务删除但首次响应丢失，重试得到 404；账本未变，题目 10 未处理。

建议：增加持久化 `deleting` 阶段；对不确定结果先读回核对。只有在目标站点、比赛和当前权限均得到确认时，才将预期目标不存在记为删除完成，再继续后续项。不能把所有 404 无条件吞掉。

### R6 · P2 · 公开附件下载被错误绑定到选手会话

位置：`src/gzctf_mcp/client.py:295`。

官方 `/assets/{hash}/{filename}` 文件读取接口没有用户权限要求，但 `download_attachment` 强制 `ensure_auth("player")`。只有管理员配置或匿名读取公开附件时，工具会在发送 GET 之前失败。参考 [AssetsController.GetFile](https://github.com/GZTimeWalker/GZCTF/blob/7e61deefdd3d5232c9dfaabcc7cd856932f774ed/src/GZCTF/Controllers/AssetsController.cs)。

本地复现：仅配置 admin Cookie，下载一个合法同站资产路径，收到缺少 `GZCTF_PLAYER_COOKIE` 错误，HTTP 请求数为 0。

建议：标准公开资产使用无凭据客户端；若需适配额外鉴权的反向代理，提供显式角色选项。保留同站路径、大小限制、独占创建和 SHA256 校验。

## 可优化的地方

1. **在工具 Schema 写清单位与特殊语义。** 当前 `cpuCount` 没有描述，官方单位是 0.1 CPU，`10` 才是 1 核；内存/存储为 MB，响应时间为 Unix 毫秒。给 `clearDeadline`、`bloodBonus`、`flagTemplate` 补充字段描述。创建比赛仍要求原始 packed integer，更新比赛却接受三血对象，建议统一输入方式。
2. **为预演补上明确可判定的业务校验。** 非容器题启用流量捕获、空白 `fileName` 会在官方更新接口被拒绝，但当前清单可以通过 dry run，直到创建题目后才失败。动态模板也仅检查非空和长度，应验证官方模板规则或标记“需要服务端验证”。
3. **公开查询无需强制登录。** 比赛列表、公开比赛详情及配置等可考虑未配置会话时使用 public，配置会话时保留用户视角。当前 `list_games` 和 `platform_config` 也会因没有角色凭据而在本地失败。
4. **控制输出体积。** 73 个工具的 Schema、完整榜单、题目 Flag 明细和实例清单会增加上下文成本；可增加作者/选手工具分组和字段投影，给 `notices` 暴露官方已有的 `count/skip`。`admin_get_challenge` 的答案明细继续保持作者用途。
5. **统一响应模型与错误结构。** 当前大量工具仅返回 `dict[str, Any]`，错误 JSON 包在字符串里。可优先给报名、部署、删除和容器状态定义明确输出模型，将业务结果、HTTP 结果和完成状态分开。
6. **减少重复配置请求。** 每次加密都 GET `/api/config`。可采用短期缓存和显式刷新；密钥失效时提示刷新，仍不自动重试 Flag 等写操作。
7. **保持轻量契约检查。** 从固定 OpenAPI 快照检查方法、路径、字段和枚举，少量 MockTransport 覆盖异常路径；版本更新时只对差异做检查。不要把 mock 全绿当作真实服务已经兼容。

## 能力扩展顺序

55 个未接入操作主要涉及 Passkey、账户维护、站点/用户管理、Token、文章、流量取证与作弊信息。是否接入应由使用场景决定。

- 赛务优先：`cheatinfo`、流量抓包列表/下载、单场 Writeup 明细和日志查询。
- 后续再考虑：站点配置、用户管理及账号维护，适合独立管理员工具组。
- Passkey 依赖用户验证与 WebAuthn 流程，不适合简单地包装成密码式自动登录；可考虑浏览器登录后交接会话。

## 验证与交付

本次执行 5 个离线疑点探针，均复现预期问题；运行 5 项既有定向测试，全部通过，覆盖加密登录/提交、截止及数值校验、单次比赛合并、multipart、异步提交状态。R1 的依据为当前官方源码，尚需独立实例验证。

- [核查规格](api-review-20261117-spec.md)
- [操作覆盖与源码摘要](records/api-review-20261117.json)
- [离线复现脚本](records/api-review-20261117-probes.py)
- [离线复现结果](records/api-review-20261117-probes.json)

复现命令：在仓库根目录运行 `.conda/bin/python docs/records/api-review-20261117-probes.py`。脚本只使用 MockTransport 和临时目录；断言描述当前问题，修复后需要改成期望行为的回归检查。

本轮仅新增审查资料并更新 changelog，没有修改运行代码、加载用户部署凭据或操作真实业务站点。建议先处理 R1/R2/R5 的资源与恢复问题，再修复 R3/R4/R6，最后完善工具描述和能力扩展。
