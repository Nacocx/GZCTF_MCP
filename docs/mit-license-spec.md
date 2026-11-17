# 主项目 MIT 许可证配置规格

日期：2026-10-23；版本保持 0.3.1，作为未发布整理。

用户已明确选择 MIT。本次为本项目原创适配代码添加根目录 LICENSE，版权署名使用当前 Git user.name（Nacocx），年份 2026。pyproject.toml 声明 SPDX MIT 并将主 LICENSE 纳入分发；README 和根目录/包内第三方声明同步。

GZCTF 与 WebSocketReflectorX 的许可和权利归属保持不变；保留源码核对报告和加密实现参考记录，不将改标 MIT 当作消除潜在第三方权利义务的证明。历史报告不覆盖改写，只追加本次决定。

验收：实际构建 wheel/sdist，验证 License-Expression: MIT、完整主许可证和 wsrx 许可证/声明均在包内且与工作区相同。无需重跑平台测试；不提交、推送或发布。

## 验收完成

已实际构建并检查 wheel 与 sdist：两者的 License-Expression 均为 MIT，License-File 同时列出主 LICENSE、THIRD_PARTY_NOTICES.md 和 wsrx MIT。包内文本与当前工作区逐字节一致，两份第三方声明同步。记录见 [mit-license-2026-10-23.json](records/mit-license-2026-10-23.json)。未更改平台运行逻辑，因此不重跑平台测试。
