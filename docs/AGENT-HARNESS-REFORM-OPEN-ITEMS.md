# Agent Harness 改造：调研项 + Spec 待补 + 决策记录

> 配套文档：`docs/AGENT-HARNESS-REFORM-SPEC.md` / `docs/AGENT-HARNESS-REFORM-PLAN.md`
> 来源：2026-05-27 spec audit + Johnny 在 issue #2 的反馈。本文件汇总待讨论项，敲定后回写 spec。
> 讨论 issue：https://github.com/XD-AIGC/XD-AIGC-agent/issues/2

---

## 已敲定决策

| # | 决策 | 备注 |
|---|---|---|
| D1 | 后台通知走 **A1（Background Worker + Delayed Reply）** | 前提 R1 通过；不通过退化 A2 |
| D2 | v1 回退**不保留** `running_job` 通知能力 | 灰度回退是应急止血，回退时手工群播兜底 |
| D3 | 当前明确**单实例约束**，多实例扩展留下一阶段 | spec 写明 contract，不实现 Redis lock |
| D4 | `running_job` 恢复采用**「用户触发恢复」**，非启动时自动扫 | reply-only 约束下，启动时自动 poll 大量旧 job 可能无处 reply；用户下一句"还在吗/继续等"触发 resume |
| D5 | `OptionSet` 过期**不硬删**，再用时强制刷新/确认 | TTL 5min 太短；改成「过期 → 下次用到时重新展示并要用户确认」 |

---

## 调研项（必须先做完才能写实施细节）

### R1. 飞书 `message.reply` 延迟有效期 ⭐ 卡 A1（架构前提，必须实测）
- **问题**：`message.reply(message_id, content)` 在 `message_id` 发出 5/10/30/60 分钟后是否仍能成功？
- **怎么查**：
  1. lark-oapi 文档 + 飞书开放平台 IM v1 文档（必要但不充分）
  2. **必须实测**：脚本发一条 user msg → sleep N 秒 → reply → 看响应码
  3. N 取 60s / 300s / 1800s / 3600s
- **决策影响**：
  - 不限时 → A1 直接走
  - ≤ 10 分钟 → A1 配合 timeout 给"继续等"按钮
  - ≤ 5 分钟 → 退化 A2
  - reply 失效且禁 `message.create` → **不能承诺后台自动通知**，改"用户主动查询状态"模式

### R2. toolbox 子工具的 cancel 能力
- **问题**：`frame-bg-remover` 等子工具的 poll API 是否支持外部 cancel？
- **怎么查**：扫 toolbox 仓库 API 文档 + 试 `POST /cancel/{jobId}`
- **决策影响**（直接影响 spec §12 + 用户文案）：
  - 支持 → 文案"已取消生成"
  - 不支持 → 文案"我已停止等待这次结果，后续即使完成也不会再发送"

### R3. lark-oapi WebSocket 进程内 background task 生命周期（必要但不充分）
- **问题 1**：`asyncio.create_task` 起的 poll worker 在 `ws.start()` 的 event loop 里能否长跑 ≥120s？
- **问题 2**：**进程重启时内存 task 会丢，Redis `active_job` 是唯一信源**——v2 不能把 job 状态只放内存
- **怎么查**：写最小 demo 跑 5 分钟 + 重启场景演练
- **决策影响**：
  - 能长跑 → A1 用 `asyncio.create_task`
  - 不能 → 起独立 `asyncio.Queue` + 长跑 consumer
  - 重启场景与 D4 联动：恢复策略统一走"用户触发"

### R4. Redis `active_job` 序列化体积
- **问题**：`ActiveJob.payload` 序列化后大小？是否需要强制只存 `fileId` 引用？
- **决策影响**：
  - <10KB → 直接存
  - 偏大 → spec 强制 `payload` 只存引用，禁存 bytes

---

## Spec 待补条目

### P0（开工前必补）

| ID | 对应 audit / issue | 改动点 |
|---|---|---|
| S1 | #1 后台通知 | spec §12 重写 + 新增 §18 Background Worker 设计；依赖 D1 + R1/R3 |
| S2 | #6 v1/v2 回退（Johnny 强化）| §7.2 重写，v2 schema = v1 superset；**`_sync_legacy_fields(session)` 必须在每次 v2 save 都触发**，否则切 v2 再回滚 v1 读不到完成态 |
| S3 | #2 mode/phase 重复 | 删 `mode` 字段；`phase + skill_name` 单一数据源 |
| S4 | #3 类型未定义 | 补 `CompletedResult` / `Message` 定义 |
| S5 | #4 Observation.data（Johnny 渐进式）| **两层方案**：envelope 强类型（status/summary/artifacts/next_actions/stop_condition）+ `data = schema_id + payload`；内置 action 用 discriminated union，未知 skill action 经 manifest 声明 schema_id。不一上来做巨型 union |
| S6 | #5 OptionSet hot-reload（D5 修订）| 加 `skill_version` + `created_at`；**过期不硬删，再用时强制刷新** |
| S7 | #7 多进程 lock | spec 写「当前单实例，未来加 Redis lock 时改 `_user_locks` → `SET NX`」契约 |
| S8 | #8 updated_params（Johnny 强化）| 比白名单更强：**value provenance**——enum 参数只能来自 `OptionSet.value`；自由文本必须可追溯到 user text 或明确 LLM 字段；已有结构化 value LLM 不得相似扩写（`bill` 与 `billbill` 字面不等就拒）|
| **S26** | Johnny #2 新增 | **`active_job` idempotency key**：飞书事件可能重投递、用户重复确认。同一 `(user_id, source_message_id, skill_name)` 只允许一次 job。session 加 `last_processed_message_ids`；`active_job.source_message_id` 必填 |

### P1（设计澄清）

| ID | 对应 | 改动点 |
|---|---|---|
| S9 | #9 | `complete`（保留上下文供再来/修改）vs `exit_skill`（清上下文回 idle）|
| S10 | #10 | manifest 标注哪些 action 是 long-running → 走 `submit_job` |
| S11 | #11 | OptionSet paging 由 `OptionResolver` 切分（lazy_resource 仍一次性返回）|
| S12 | #12 | 补完整 State Transition Table：`(phase, intent) → (next_phase, side_effects)` |
| S13 | #13 | `OptionSet.scope: Literal["skill_param","system"]`，timeout 菜单是 system |
| S14 | #14 | 依赖 R2 结论；文案分支见 R2 |
| S15 | #15 | TurnClassifier 仲裁：OptionResolver > deterministic > LLM |
| S16 | #16 | 定义 `ObservationReducer` 契约 |
| S17 | #17 | simple skill（无 `system_prompt_core`）走 fast-path |
| S18 | #18 | enum param 自动构造 `OptionSet`；`_enum_options_block` 保留作 deterministic 兜底 |
| S24 | #24 升级 | router 多 skill 命中 → disambiguation `OptionSet`（与 S6 共用一套 OptionSet 机制，不另写选择逻辑）|
| **S27** | Johnny P1 #4 新增 | transcript eval 断言**行为轨迹**：是否调 router/skill LLM、是否调 skill action、是否 submit job、phase 变化、last_options 写入、active_job 创建/清除——不只是 `reply_contains` |

### P2（小项）

| ID | 改动点 |
|---|---|
| S19 | 删 `turn_count` |
| S20 | `chitchat` 用模板回复 |
| S21 | transcript 脱敏标准：open_id → `<USER_N>`，file_id → `<FILE_N>` |
| S22 | 区分 `chat_history`（短，给 LLM）vs `transcript`（长全脱敏，给 eval）|
| S23 | observation 累积超 3 条自动摘要 |
| S25 | `ActiveJob.payload` 只存 `fileId` 引用（依赖 R4）|

---

## PLAN 重组（取代原 6 阶段）

原 `AGENT-HARNESS-REFORM-PLAN.md` 的 P0-P6 重组为 4 个新阶段：

### 新 P0：地基（三件事 = 三个独立 PR）

| PR | 内容 | 依赖 |
|---|---|---|
| **PR-0a** | transcript fixture 格式 + runner（先 mock 现有 v1 跑通；包含 S27 行为轨迹断言）| 无 |
| **PR-0b** | `ConversationSession` v2 + 双向兼容 helper（纯数据层，不接 runtime）| PR-0a |
| **PR-0c** | `OptionSet` + `OptionResolver`，替换 `_resolve_numbered_character_reply` | PR-0b |

每 PR ≤500 行 diff，可独立 review + 回滚。

### 新 P1：State machine + TurnClassifier（原 P3）
### 新 P2：JobController + Background Worker（原 P4，最有风险，依赖 R1）
### 新 P3：SkillRuntime 精简 prompt（原 P5）
### 新 P4：Eval + 灰度部署（原 P6）

---

## 执行顺序（Johnny 建议，已采纳）

1. ✅ open-items.md 合入 main（commit `e62552c`）
2. **R1-R4 调研，R1 必有结论**
3. 按 S1-S8 + S26/S27 改 `AGENT-HARNESS-REFORM-SPEC.md` 到 spec v2
4. 同步重写 `AGENT-HARNESS-REFORM-PLAN.md` 为新 4 阶段结构
5. 再开始实现（新 P0 → 新 P4）

---

## 待 Johnny 确认（剩余）

1. ✅ D1 / D2 / D4 / D5（A1 + v1 不保 + 用户触发恢复 + OptionSet 过期刷新）
2. ❓ **调研 R1-R4 分工**：
   - R1 需要真实飞书 app 凭证（你 .env 有），建议你本地跑
   - R2 需要 toolbox 服务可达，我可在 SSH 隧道下跑
   - R3 可独立写 demo
   - R4 可独立跑
