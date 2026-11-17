# v0.3 使用说明

## 认证

`.env.example` 新增 `GZCTF_ADMIN_USERNAME/PASSWORD`、`GZCTF_PLAYER_USERNAME/PASSWORD`。密码只放本地环境。没有 Cookie 时首次请求会尝试一次账密登录；Cookie 过期不会重放写请求，先调用 `auth_login(role)` 再核对上次操作结果。Cookie 支持原始 Token、完整头值或 `Cookie:` 前缀，分块 Cookie 必须提供完整头。

`auth_requirements` 读取公开配置与验证码类型；非 None 时传入站点认可的 `challenge` 结果。`auth_pow_challenge` 只领取谜题，不绕过或代替验证码验证。`auth_logout` 清除当前内存会话；环境账密仍存在时后续请求可再次自动登录。密码与 Flag 按当前公开密钥采用官方 X25519 + SHA256 + AES-GCM 协议；公钥异常时停止，不降级发送明文。

## 题目配置及附件

题面、提示、分值、难度、最低分比例、三血开关等仍由 `ChallengeUpdate` 配置；初始分非负、难度为有限正数、最低分比例在 0–1。截止时间必须有时区。清空调用：

```json
{"game_id":1,"challenge_id":2,"configuration":{"clearDeadline":true}}
```

`deadlineUtc:null` 被拒绝，因为官方更新接口把 null 当作不修改。显式清空映射为 Unix epoch 哨兵。

恢复上题先比较附件类型与哈希/URL，相同附件不重复上传或绑定；本地附件使用新 URL 读回并核对 SHA256，避免缓存掩盖上游文件丢失。部署返回 `resources`（题目 ID、是否新建、已确认上传的哈希），可用于核对与清理。超时后先查看题目，不能仅凭错误认定写入未发生。

新绑定的每个本地附件需要独立上传一次，即使多个附件内容相同。`admin_upload_file` 在当前 MCP 会话记录一次可消费引用，绑定公共附件或 Flag 时消费；`fileHash` 只是内容标识，不能独自证明有可用引用。重启后新绑定应重新上传，或在清单中使用 `attachmentPath` 自动处理。相同题目、相同附件的恢复不重新上传或消费。手动删除文件会作废本会话该 hash 的待用引用。

`cpuCount` 单位为 0.1 核，`10` 表示 1 核；内存和存储单位为 MB。返回的官方时间值为 Unix 毫秒。预演会拒绝空白 `fileName` 和非容器题启用流量捕获；动态 Flag 模板的生成规则仍由服务器验证。

`download_attachment` 默认以 `role:"public"` 下载同站公开资产，无需配置选手凭据；仅在反向代理要求认证时显式传入 `admin` 或 `player`。下载及导出统一处理 Cookie 续期和网络异常，附件读回失败会保留部署阶段和题目 ID。

动态附件的每个 Flag 支持 `attachmentPath`，并要求 `attachmentType:"Local"`；路径相对 `GZCTF_WORKSPACE`。不要同时指定 fileHash。部署前检查全部文件，随后自动上传并保持 Flag/附件对应；普通 `admin_add_flags` 仍要求预先上传后的 hash。示例见 `examples/batch/plan.json`。

## 分组和审核

用 `admin_list_divisions` 查看，`admin_save_division` 创建/更新，`admin_delete_division` 删除。保存时必须明确名称，避免上游默认空字符串改名。权限使用名称列表：`JoinGame`、`RankOverall`、`RequireReview`、`ViewChallenge`、`SubmitFlags`、`GetScore`、`GetBlood`、`AffectDynamicScore`、`All`。空列表表示全部禁止，All 包含 RequireReview；遗漏 defaultPermissions 则使用平台默认。

```json
{
  "game_id":1,
  "division":{
    "name":"Player",
    "defaultPermissions":["JoinGame","RequireReview","RankOverall","ViewChallenge","SubmitFlags","GetScore","GetBlood","AffectDynamicScore"],
    "challengeConfigs":[{"challengeId":2,"permissions":["ViewChallenge"]}]
  }
}
```

`challengeConfigs` 是完整替换列表；更新时省略则保留，`[]` 清除覆盖。邀请码更新传空字符串清除，null/省略保留。报名可使用 `join_game(...,division_name="Player",invite_code=...)`；名称必须唯一，多个组不会自动挑选，名称与 ID 同时填写必须一致。工具读回最终 status，仅 Accepted 表示通过；Pending 仍需 `admin_participations` 取得参与记录 ID，然后 `admin_review_participation` 审核。队伍 ID 与参与记录 ID 不能混用。平台仅允许 Pending/Rejected 的参赛成员退赛，工具不会改变此规则。

## 比赛、队伍和赛务管理

`admin_update_game` 按比赛 ID 串行执行本 MCP 客户端内的读、合并、PUT 和读回，并检查本次修改字段；其他 MCP 进程或网页编辑仍需协调。三血奖励 `patch.bloodBonus={"first":100,"second":50,"third":20}` 使用千分比，100 表示加 10%；创建接口的 bloodBonus 是官方位打包整数。`admin_game_poster` 上传海报，`admin_save_notice/admin_notices/admin_delete_notice` 管理公告。选手 `notices` 支持 `count`（1–100）和 `skip`（0–300）。

队伍工具包括创建/修改、详情、邀请码查询/轮换/接受、队长转移、踢人、退出/删除和头像上传。转移/踢人需要用户 UUID。`writeup_status` 查询提交状态，PDF 提交仍使用 `submit_writeup`。`admin_events/admin_submissions/admin_instances/admin_stop_instance` 观察赛务和处理实例；删除实例和比赛会关闭本 MCP 管理的相应隧道。

`admin_export_game` 写出官方 ZIP，`admin_import_game` 上传官方 ZIP；`admin_export_records(kind="scoreboard"|"submissions"|"writeups")` 写出 XLSX 或 TAR。输出位于 workspace/downloads，不覆盖文件，限制大小并返回 SHA256，不解压、不把二进制误解析为 JSON。导出含组织者资料，应妥善保存。

## 批量部署与清理

```json
{"game_id":1,"plan_file":"examples/batch/plan.json","state_name":"trial-1","dry_run":true}
```

调用 `admin_deploy_batch`，检查预演后同参设置 `dry_run:false`。按顺序执行，第一次失败即停止。再次调用使用相同 state_name/计划可跳过已完成项并恢复已记录 ID 的禁用题。工作区 `.mcp-state/` 保存目标、输入及附件指纹、进度、ID 和上传哈希，不保存明文 Flag/Cookie/密码。计划和附件内容变化会拒绝恢复；已清理的计划不可重用，应更换 state_name。

状态文件权限 0600，原子替换；同一状态名有进程锁。进程崩溃后可能留下 `.lock` 或 `.tmp`，必须先核对原站状态，再由操作者删除残留锁/临时文件。锁仅保护同一状态文件；不同状态名、独立单题调用或其它客户端仍不能并发编辑相同题目。

新账本使用 `uploadReferences` 按 `attachment`（公共附件）或 `flag:0`、`flag:1` 等清单索引记录上传归属，状态为 uploading/uploaded/binding/bound。恢复只使用属于该位置的已确认引用；多个位置使用相同内容也分别记录。旧版未完成账本如果只有 `uploadedHashes`，先核对远端，再新建包含已有题目 ID 和本地附件路径的计划/状态；已经完成的旧条目仍可跳过。

处于 creating/uploading 的不确定状态不会自动重放。核对原站后调用 `admin_batch_reconcile(state_name,key,challenge_id,uploaded_hashes,reference_slot)`：创建结果已确认时传 `uploaded_hashes:[]`；确认某一次上传已完成且尚未被绑定消费时传 `[hash]`，`reference_slot` 指定已记录位置（默认使用 uncertainSlot）。仅发现文件存在不足以证明引用可用。对 uploading 位置传 `[]` 明确表示已确认上传未发生，恢复时才允许重新上传；已绑定引用不能这样释放。绑定响应丢失时先正常恢复，读回发现同一附件就完成该位置，发现缺失则停止等待核对。完成项代表上次成功，不是持续监控原站资源是否又被修改。

`admin_batch_status` 查看进度。`admin_cleanup_batch` 默认预演，仅清理账本明确记录的题目（包括显式传入的已有题目 ID，执行前务必核对）。`admin_delete_file` 默认预演，实际请求可能只减少共享引用，不宣称物理存储已删除；使用 `admin_files` 和新的资产 URL 复核。不会批量删除原站所有文件。

清理在 DELETE 前保存 deleting。若删除已生效但响应丢失，再次调用时先确认管理员可访问原比赛，读取完整题目列表；已确认不存在的 deleting 条目会记为 deleted 后继续清理。权限失败或比赛不存在会停止，不能把所有 404 都当作成功。

## 错误

MCP isError 的文本包含结构化 JSON 字段：httpStatus、businessStatus（有安全格式时）、脱敏限长的 title、nextStep、retryable、automaticRetry=false；认证错误还提示 nextTool。429 的 Retry-After 只接受数字。原始 HTML、任意响应文本和请求秘密不直接输出。网络错误提示写入结果不确定，部署另外返回 completed=false、失败阶段及资源清单。
