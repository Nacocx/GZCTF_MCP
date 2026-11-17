# GZCTF MCP 源码来源与许可证核对

日期：2026-10-23；适配器版本：0.3.1；本次不选择主许可证，不修改运行代码，不发布或推送。

## 结论

**当前证据没有发现直接复制 GZCTF 源文件、较长代码文本或将其服务端实现逐行移植的明确情况；不能仅因本项目调用 GZCTF API，就认定整个 MCP 必须采用 AGPL。** 但本项目开发时实际阅读过 GZCTF 源码，特别是 API 加密实现，因此不能把它描述为 clean-room（未接触原实现的隔离开发），也不能用零文本匹配宣称“已完全排除衍生代码风险”。

主项目采用 MIT 仍是可评估的选择，**本次不是已完成 MIT 法律清权的结论**。加密实现的来源关系应保留明确记录；如果发布者要求消除这部分许可不确定性，可将本报告及对应片段交由上游确认授权或作独立许可审查。事后更换变量名、拆函数或自己再重写一次，并不能自动证明不是改编。

## 固定审查对象

- 本地只读参考：GZCTF commit `cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296`，本次检查时工作区干净。
- 适配器没有 Git 首次提交；以下逐文件 SHA256 是此次快照的身份依据，不能用不存在的 blame 历史证明作者来源。
- 纳入适配器 `src/`、`scripts/`、`tests/`、`deploy/`、`examples/`、`licenses/` 共 **49 个文件**，包括本次检查脚本；清单与 SHA256 见 [机器记录](records/source-origin-2026-10-23.json)。
- 对照 GZCTF Git 跟踪且非受限的源码/配置共 **549 个文件**。受限清单中的 5 个文件不读取实现正文，不作源码相似度比较；仅核对清单、适配器依赖和发布包的边界。
- `.env`、本地测试输出、下载的工具二进制、conda 环境未纳入内容比较，不读取或记录账号凭据。

## 上游许可边界

本地参考的 `LICENSE.txt` 是 AGPLv3；`LICENSE_ADDENDUM.txt` 与 `PROPRIETARY_COMPONENTS.md` 将以下路径单独列为受限组件：

- `src/GZCTF/Services/Container/Manager/*`
- `src/GZCTF/ClientApp/src/hooks/useConfig.ts`
- `src/GZCTF/ClientApp/src/components/Copyright.tsx`

适配器没有这些路径、未导入这些实现、未嵌入 GZCTF 服务端模块；容器启动/停止通过平台 API 完成。本地 Compose 引用官方容器镜像属于平台测试依赖，不能解释成把镜像内全部代码重新授权为 MIT。上游品牌规则仍独立适用；发布说明应采用“非官方 GZCTF MCP 客户端/适配器”，不暗示官方维护或背书。

来源链接固定到参考 commit：[许可补充](https://github.com/GZTimeWalker/GZCTF/blob/cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296/LICENSE_ADDENDUM.txt)、[受限清单](https://github.com/GZTimeWalker/GZCTF/blob/cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296/PROPRIETARY_COMPONENTS.md)、[品牌规则](https://github.com/GZTimeWalker/GZCTF/blob/cc12f65fe9cd9eb2a94ccfcb3604a81e394e0296/TRADEMARKS.md)。本地对应文件的 SHA256 已记录。

## 重点逐项核对

| 适配器位置 | 上游参考与实际关系 | 本次判断 |
| --- | --- | --- |
| `client.py:76`，`Client.encrypt` | 前端 `ClientApp/src/utils/Crypto.ts:14–54,59–85`；X25519 共享密钥、SHA256、AES-GCM、32 字节临时公钥/12 字节 nonce/密文及标签/Base64 格式一致 | 确认参考过官方源码；Python 直接使用 cryptography 高层 API，没有复制 WebCrypto 导入/deriveBits/缓冲区拼装函数、ClientError/i18n 包装。步骤相似主要由互操作格式决定，但跨语言改编不能仅凭文本不相同排除，是本次需保留许可不确定性的重点 |
| `client.py` 的登录/登出、上传/下载 | Account/Assets/Game 控制器的端点、Cookie 名和 multipart 约定 | 客户端请求封装；未移植 ASP.NET Identity、blob 存储或判题实现。独立增加环境凭据、角色隔离、错误脱敏、工作区和下载校验 |
| `models.py:41,166`，ChallengeUpdate/GameCreate 等 | 官方请求模型与 OpenAPI：JSON 字段、枚举、范围、日期含义 | 明确按接口契约编写 Pydantic 模型。字段与枚举一致不能单独证明复制可保护实现；未见 C# 方法体逐行翻译。额外预检为适配器逻辑 |
| `models.py:198–206`，BloodBonus | `Utils/Shared.cs:231–278`、`Models/Transfer/TransferExtensions.cs:226–229` | 10 bit 分组、20/10 位偏移和千分比是交换格式。当前只编码参数/校验字段，没有移植上游积分计算；短位运算保留来源记录，不凭这一行单独认定整体派生 |
| `models.py:254–271`，PERMISSIONS | `Utils/Enums.cs:419–508`，GamePermission | 名称和数值是 API 位掩码；MCP 只做名称到掩码的转换，没有移植服务器资格/排名/判题权限执行逻辑 |
| `models.py:63–89`，clearDeadline | `Models/Data/GameChallenge.cs` 对 DeadlineUtc 的更新语义 | Unix epoch 是服务器清空哨兵；MCP 把显式意图转换为请求字段，没有复制服务器 Update 实现 |
| `management.py:16`，join | Game 控制器的报名/检查/详情接口 | 客户端先解析唯一分组、发一次报名、读回状态；不是复制服务器 JoinGame 的成员管理、邀请验证或权限处理 |
| `management.py:104`，admin_update_game | Edit/GameInfoModel 整对象 PUT 约定 | 在客户端 GET→合并→本地验证→PUT→GET，未移植上游持久化代码 |
| `server.py` | 控制器路由与官方 MCP SDK | MCP 工具注册、类型、错误包装、资源与生命周期；相同 URL/字段属于接口对应关系，未见控制器实现复制 |
| `workflow.py` | 官方题目/附件/Flag 接口和观察到的重复绑定行为 | 客户端状态机、幂等比对、资源清单和内容校验；上游并无此 MCP 部署状态机 |
| `batch.py` | 无对应 GZCTF 批量 MCP 状态机 | 原子本地账本、指纹/锁、停止与显式恢复，未见上游代码移植 |
| `proxy.py` | `/api/proxy/{uuid}`、`/api/proxy/noinst/{uuid}` 与 wsrx CLI | 仅请求平台实例并启动独立 wsrx 进程，管理本地端口/生命周期；未实现/移植 GZCTF DockerManager/KubernetesManager 或 Rust 代理内部实现 |
| `_wsrx_runner.py` | 无对应 GZCTF 服务器组件 | stdlib 子进程/信号/管道 EOF 监督器 |
| `config.py`、`cli.py`、`__main__.py`、`__init__.py` | 无对应平台业务实现 | 本地配置、程序入口、stdio 参数和版本号 |

## 脚本、测试、部署与素材

| 文件组 | 核对结果 |
| --- | --- |
| `scripts/install_wsrx.py` | 固定版本/平台映射、官方分发包 SHA256、按文件名提取独立 CLI；未包含 Rust 实现。校验和、分发 URL 和 CLI 参数属于兼容配置，wsrx 仍单独安装 |
| `scripts/local_setup.py` | 本地随机凭据文件生成器；不是上游账号创建实现 |
| `scripts/live_acceptance.py`、`live_gap_acceptance.py`、`live_proxy_acceptance.py` | 编排测试 API/MCP 调用及测试数据；动态加密检查复用本适配器 Client，未移植官方测试框架 |
| `scripts/remote_admin_smoke.py` | 专项站点测试编排和清理，不是上游控制器。其固定站点地址属于另一个发布前隐私/通用化待办，本次不更改 |
| `scripts/uvx_acceptance.py` | uvx 子进程和 MCP 协议验证 |
| `scripts/source_origin_audit.py` | 本次新增的证据工具，无 GZCTF 实现依赖 |
| `tests/*.py`（7 个文件） | 适配器的 mock/CLI/stdio/代理/故障恢复回归；未发现与上游相同的文件或较长文本，结构对应本适配器而非移植上游 .NET 测试 |
| `deploy/local/*.yaml`、Dockerfile.challenge、challenge.py | 连接官方 Docker 镜像和本地 HTTP 测试夹具；不包含平台源码，测试响应仅读取平台约定的 GZCTF_FLAG 环境变量 |
| `examples/` | MCP 配置、清单与自建文本样例；没有 GZCTF 官方 logo/banner/字体等品牌素材 |
| `licenses/`、`src/gzctf_mcp/_licenses/` | 唯一明确保留的第三方许可文本为 wsrx MIT；根目录/包内两份 MIT 文本一致，两份 notices 也一致。许可文本复制是有意保留，不是“全部原创” |

## 自动比较方法及结果

运行：

```bash
.conda/bin/python scripts/source_origin_audit.py
```

1. 比较完整文件 SHA256；相同文件数 **0**。
2. 忽略空白及单行注释，保留长度至少 12 字符的有效行，比较连续 3 条保留行且总长至少 90 字符的块；命中的适配器文件数 **0**。
3. 对 Python AST 中长度至少 40 字符的字符串常量，检查是否完整出现于非受限上游源码；命中的文件数 **0**。

这是针对明确文本复制的筛查，没有进行“变量统一后证明原创”之类错误推断；短标识符、JSON 字段/数值、跨语言改写、先看源码后凭记忆重写及历史上曾存在的代码，均可能不被这些阈值捕获。加密、计分编码、权限和模型另作人工对照，不能把 0 命中当作许可放行证。

## 实际发布包边界

使用 setuptools 重新构建检查样本到 `.local-test/origin-dist/`，逐条检查 tar.gz 与 wheel 成员，而不是仅相信 .gitignore。结果：

| 样本 | 文件数 | 核对 |
| --- | --- | --- |
| `gzctf_mcp-0.3.1.tar.gz` | 81 | 未包含 GZCTF/、受限路径、平台 C#/TSX 源码、环境凭据、.conda、.tools、平台/代理二进制 |
| `gzctf_mcp-0.3.1-py3-none-any.whl` | 21 | 同上，且 12 个适配器 Python 模块与当前工作区逐字节一致 |

两份样本都包含 wsrx MIT 许可文本，不包含 wsrx 可执行文件。构建后新增的本报告/changelog 不改变已核对的运行源码，但会改变以后构建的 sdist 内容/哈希；记录内哈希只标识这两份审查样本，不是最终发布包校验值。

复核命令：

```bash
.conda/bin/python scripts/source_origin_audit.py \
  --artifact .local-test/origin-dist/gzctf_mcp-0.3.1.tar.gz \
  --artifact .local-test/origin-dist/gzctf_mcp-0.3.1-py3-none-any.whl
```

## 对“是否必须用 GZCTF 协议”的具体回答

- **不能因为适配 GZCTF API，就自动要求整个 MCP 使用 GZCTF 的许可证。** 从架构和本次源码对照看，它是独立运行的网络客户端，没有发现直接嵌入 GZCTF 服务端代码的证据。
- **也不能因为 Python 与 C# 不同、或者 GZCTF/ 被忽略，就证明 MIT 一定没有问题。** 加密确实参考过 AGPL 覆盖的官方实现；本次判定其主要相同点是互操作必需的算法/报文格式，但不能代替法律上的衍生作品判断。
- 若选择 MIT，需要为自己的代码添加主 LICENSE 和相应元数据，并保留接口/加密来源说明及 wsrx MIT 原文。致谢本身不能补足假如存在的 AGPL 改编义务。
- 若希望降低 AGPL 改编争议，可评估按 AGPL 发布或取得明确许可；这不意味着已发现必需 AGPL 的复制，也不能绕过受限组件和品牌的单独条款。
- 本次不评价全部 Python 依赖的再分发义务，不为所有司法辖区给出法律保证；最终许可证仍需发布者决定。

解释背景可参阅 [GNU 关于独立程序与聚合的说明](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation)；通信机制与语义都要考虑，不应把 HTTP、socket 或独立进程单独当作绝对豁免条件。

## 后续决定：2026-10-23

用户在核对完成后明确选择 MIT，已为原创适配代码添加主 LICENSE（2026 Nacocx）及打包元数据，根目录/包内第三方声明同步。上文是选择前的审查记录，其关于加密参考来源和证据限度的说明继续保留；本次决定不构成对上游代码的重新授权。

此前 source-origin JSON 和审查样本哈希对应 MIT 决定前的快照；这次更新的 notices 与主许可证分发证据另见 [MIT 验收记录](records/mit-license-2026-10-23.json)，不覆盖旧审查证据。
