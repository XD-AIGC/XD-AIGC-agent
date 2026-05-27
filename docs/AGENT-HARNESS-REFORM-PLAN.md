# Agent Harness 改造 Plan

> 配套 spec：`docs/AGENT-HARNESS-REFORM-SPEC.md`。
> 本计划只覆盖 agent 编排层，不扩大飞书权限和 toolbox 出站范围。

## P0：固定事故回放

- 建 `tests/fixtures/transcripts/*.json`。
- 覆盖：`3->33`、`billbill`、完成后问能力、完成后问日期、生成中插话、比例选择、确认后生成。
- 先让现状测试暴露问题，再逐步修。

验收：

- transcript runner 能回放多轮 Feishu 对话。
- 每条 transcript 有预期回复类型、是否允许 submit、是否允许 skill action。

## P1：引入新 Session Model

- 新增 `ConversationSession`，保留旧 `UserSession` 兼容读。
- Redis 存储支持版本字段 `schema_version=2`。
- 新旧 session 自动迁移，不清空线上用户上下文。

验收：

- 旧 Redis session 可读。
- 新 session 保存 phase、last_options、active_job。

## P2：OptionSet 替代文本反推

- 角色类型、角色清单、构图、比例全部结构化保存。
- 删除 `_resolve_numbered_character_reply` 对 assistant 文本的依赖。
- `more/back` 由 OptionResolver 处理。

验收：

- 用户回复数字只会解析为当前 OptionSet 编号。
- 比例/构图编号不会落到角色参数。
- 角色名、别名、编号都可解析。

## P3：完成态与运行态状态机

- completed 后默认不进入 skill LLM。
- running_job 时支持取消、继续等待、状态说明。
- 用户换需求时退出当前 skill 回 router。

验收：

- 完成后问“今天周几/还能做什么/谢谢”不触发 submit。
- “再来一张/换成横版/标题改成 X”仍可继续当前 skill。

## P4：JobController

- submit/poll/retry/continue_wait/cancel 统一实现。
- `active_job` 存 job_id、payload、started_at、poll_count、last_status。
- timeout 时给用户可选下一步，不直接丢异常。

验收：

- 生成中用户发“取消”会停止等待并标记 cancelled。
- timeout 后用户可“继续等/重试/修改/取消”。
- restart 后不会重复 submit 同一个 job。

## P5：SkillRuntime 精简 prompt

- prompt 从“控制状态”改为“在当前状态内规划下一步”。
- action schema 收窄为 `SkillRuntimeAction`。
- SKILL.md 仍完整注入，但状态、选项、job 不再靠 LLM 记忆。

验收：

- 新增生图 skill 不需要改主流程，只需 manifest + SKILL.md。
- LLM 不能输出未声明 action。

## P6：评估与灰度

- transcript eval 全绿后本地跑 mock Feishu。
- L20_1 feature flag：`AGENT_RUNTIME=v2`。
- 先 Johnny 单人灰度，再放测试同事。

验收：

- 完整测试不少于 120 个，其中 transcript eval 不少于 12 条。
- `bash ci/check-banned-apis.sh` 继续通过。
- 不新增飞书 forbidden API 调用。

## 风险

| 风险 | 级别 | 缓解 |
|---|---|---|
| v2 session 迁移破坏线上上下文 | 高 | versioned session + fallback 旧字段 |
| 状态机过硬导致不够智能 | 中 | 状态只管边界，参数理解仍交给 LLM |
| prompt/context 变长 | 中 | skill lazy load + observation 摘要 |
| 多 skill 差异过大 | 中 | 共性进 OptionSet/JobController，特性留在 SKILL.md |
| 开发中重复线上事故 | 中 | 先 transcript eval，再灰度 |

## 待确认

1. 是否接受 `AGENT_RUNTIME=v2` 灰度开关？
2. 是否把真实 Feishu 对话脱敏后写入 `tests/fixtures/transcripts/`？
3. `/取消`、`/重新开始`、`/帮助` 是否要作为用户可见命令？
4. 运行中是否需要主动进度消息，还是继续只在开始和完成时回复？
