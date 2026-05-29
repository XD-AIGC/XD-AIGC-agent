# Agent Harness 改造：调研项 + Spec 待补 + 决策记录

> 配套文档：`docs/AGENT-HARNESS-REFORM-SPEC.md` / `docs/AGENT-HARNESS-REFORM-PLAN.md`
> 来源：2026-05-27 spec audit + Johnny 在 issue #2 的反馈。本文件汇总待讨论项，敲定后回写 spec。
> 讨论 issue：https://github.com/XD-AIGC/XD-AIGC-agent/issues/2

---

## 已敲定决策

| # | 决策 | 备注 |
|---|---|---|
| D1 | 后台通知走 **A1（Background Worker + Delayed Reply）** | R1 已实测通过：`message.reply` 至少 5.6h 后仍有效 |
| D2 | v1 回退**不保留** `running_job` 通知能力 | 灰度回退是应急止血，回退时手工群播兜底 |
| D3 | 当前明确**单实例约束**，多实例扩展留下一阶段 | spec 写明 contract，不实现 Redis lock |
| D4 | `running_job` 恢复采用**「用户触发恢复」**，非启动时自动扫 | reply-only 约束下，启动时自动 poll 大量旧 job 可能无处 reply；用户下一句"还在吗/继续等"触发 resume |
| D5 | `OptionSet` 过期**不硬删**，再用时强制刷新/确认 | TTL 5min 太短；改成「过期 → 下次用到时重新展示并要用户确认」 |

---

## 调研结论（2026-05-27 已完成）

### R1. 飞书 `message.reply` 延迟有效期 ⭐ 卡 A1（架构前提，必须实测）
- **结论**：A1 成立。真实 `message_id` 在 94.2 分钟、337.6 分钟后再次 `message.reply` 均返回 `success/code=0`。
- **证据**：本地 Conda env 使用当前 `.env` 凭证，仅调用 `im.v1.message.reply`；未调用 `message.create`。
- **边界**：只能宣称"已实测至少 5.6h 有效"，不要写成永久有效。超过业务 timeout 很久的 job 仍走 D4 用户触发恢复。
- **spec 影响**：Background Worker 可在 job 完成后 delayed reply；仍保留 timeout 菜单和用户主动查询入口。

### R2. toolbox 子工具的 cancel 能力
- **结论**：当前两个生图 skill（8085 `xd-town-studio`、8090 `xd-poster-studio-v2`）不支持服务端 cancel。
- **证据**：toolbox server route 只有 submit/poll/image/history；线上 8085/8090 候选 `POST /api/cancel/*`、`/api/jobs/*/cancel` 均 404。前端取消只是停止本地轮询。
- **边界**：shared batch API 有 `/jobs/{job_id}/cancel`，但这不是当前两个 skill 使用的后端。
- **spec 影响**：取消文案必须写"我已停止等待这次结果，后续即使完成也不会再发送"，不能写"已取消生成"。

### R3. lark-oapi WebSocket 进程内 background task 生命周期（必要但不充分）
- **结论**：进程内 task 可行，但只能作为执行器，不能作为状态源。
- **证据**：lark-oapi `ws/client.py` 使用模块级 event loop，`start()` 创建 ping/receive task 后 `run_until_complete(_select())` 常驻；最小 demo 中 `ensure_future()` 调度的 worker 在 callback 返回后继续运行 130.1s 并完成。
- **边界**：systemd restart / process crash 一定会丢内存 task；Redis `active_job` 是唯一可信状态。
- **spec 影响**：A1 用 `asyncio.create_task` 或等价 JobController worker；恢复统一走 D4 用户触发，不做启动时扫旧 job 自动 reply。

### R4. Redis `active_job` 序列化体积
- **结论**：正常 compact payload 很小，但必须限制内容形态。
- **测量**：`xd-town-studio` 典型 active job 约 816B；`xd-poster-studio-v2` 典型约 731B；展开 8 个角色长描述约 14KB；误存 1MB base64 图片约 1,049,331B。
- **spec 影响**：`active_job.payload` 只存 compact 参数、`fileId/public_id`、必要短文本；禁止 bytes/base64/signed URL/完整 lazy_resource 列表。建议软上限 10KB，超过则拒绝创建 job 并要求改为引用。

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
| S14 | #14 | 按 R2 结论写本地取消语义：停止等待并丢弃后续结果，不承诺取消后端生成 |
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
| S25 | `ActiveJob.payload` 只存 compact refs；禁 bytes/base64/signed URL/完整资源列表，软上限 10KB |

## 已知实现偏离

- **PR #14 / P3d（2026-05-29）**：SPEC §11.1 原计划要求未知 skill action 必须声明 `actions[].data_schema_id`，否则 ObservationReducer 拒绝 observation。当前实现改为向后兼容策略：`data_schema_id` 可选，内置 action 自动推断，未知结构降级为 `unknown.raw`。后续需二选一：更新 SPEC §11.1 为“可选但推荐”，或等现有 skill 迁移后再收紧为强校验。
- **PR #22 / P4 dispatch（2026-05-29）**：PLAN P4 原计划接 v1/v2 进程内 dispatch；实际改为 dry-run 标签 + 代码级回滚。原因：v1 不是独立可运行的执行器，伪造 dispatch 会绕过 `active_job`、background worker 和幂等防线（详见 `docs/RUNTIME-DRY-RUN.md` §8）。

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
2. ✅ R1-R4 调研完成（R1 已实测通过）
3. 按 S1-S8 + S26/S27 改 `AGENT-HARNESS-REFORM-SPEC.md` 到 spec v2
4. 同步重写 `AGENT-HARNESS-REFORM-PLAN.md` 为新 4 阶段结构
5. 再开始实现（新 P0 → 新 P4）

---

## 当前状态

1. ✅ D1 / D2 / D4 / D5（A1 + v1 不保 + 用户触发恢复 + OptionSet 过期刷新）
2. ✅ R1-R4 已完成，结论已回写本文件
3. 下一步：按 S1-S8 + S26/S27 改 spec v2，并同步重写 plan 为新 P0-P4
