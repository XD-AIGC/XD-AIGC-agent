# Agent Harness 改造：调研项 + Spec 待补 + 决策记录

> 配套文档：`docs/AGENT-HARNESS-REFORM-SPEC.md` / `docs/AGENT-HARNESS-REFORM-PLAN.md`
> 来源：2026-05-27 spec audit。本文件汇总待讨论项，敲定后回写 spec。

---

## 已敲定决策

| # | 决策 | 备注 |
|---|---|---|
| D1 | 后台通知走 **A1（Background Worker + Delayed Reply）** | 前提 R1 通过；不通过退化 A2 |
| D2 | v1 回退**不保留** `running_job` 通知能力 | 灰度回退是应急止血，回退时手工群播兜底（2026-05-27 Johnny 确认）|
| D3 | 当前明确 **单实例约束**，多实例扩展留下一阶段 | spec 写明 contract，不实现 Redis lock |

---

## 调研项（必须先做完才能写实施细节）

### R1. 飞书 `message.reply` 延迟有效期 ⭐ 卡 A1
- **问题**：`message.reply(message_id, content)` 在 `message_id` 发出 5/10/30/60 分钟后是否仍能成功？
- **怎么查**：
  1. lark-oapi 文档 + 飞书开放平台 IM v1 文档
  2. 实测：写一个脚本，发一条 user msg → sleep N 秒 → reply → 看响应码
  3. N 取 60s / 300s / 1800s / 3600s
- **决策影响**：
  - 不限时 → A1 直接走
  - ≤ 10 分钟 → A1 配合 timeout 给"继续等"按钮，避免超时后没法 reply
  - ≤ 5 分钟 → 退化 A2

### R2. toolbox 子工具的 cancel 能力
- **问题**：`frame-bg-remover` 等子工具的 poll API 是否支持外部 cancel？
- **怎么查**：扫 `D:\GIT\XD-AIGC-toolbox` 的 API 文档 + 试一下 POST `/cancel/{jobId}`
- **决策影响**：
  - 不支持 → spec §12.2 "取消" 改为"本地遗弃 + 丢弃结果"
  - 支持 → 额外加 cancel HTTP 调用

### R3. lark-oapi WebSocket 进程内 background task 生命周期
- **问题**：`asyncio.create_task` 起的 poll worker，在 lark-oapi `ws.start()` 的 event loop 里能否长跑 ≥120s 不被回收？
- **怎么查**：写最小 demo 跑 5 分钟看任务是否还活着
- **决策影响**：
  - 能 → A1 直接 `asyncio.create_task`
  - 不能 → 起独立 `asyncio.Queue` + 长跑 consumer

### R4. Redis `active_job` 序列化体积
- **问题**：`ActiveJob.payload` 序列化后大小？接近 Redis 单 key 上限（512MB 理论，实操 1MB 警戒）？
- **怎么查**：拉一个真实 submit payload 序列化看 byte 数
- **决策影响**：
  - <10KB → 直接存
  - 偏大 → spec 强制 `payload` 只存 `fileId` 引用，禁存 bytes

---

## Spec 待补条目（按 audit 编号）

### P0（开工前必补）

| ID | 对应 audit | 改动点 | 备注 |
|---|---|---|---|
| S1 | #1 后台通知 | spec §12 重写 + 新增 §18 Background Worker 设计 | 依赖 D1 + R1/R3 |
| S2 | #6 v1/v2 回退 | spec §7.2 重写，v2 schema = v1 superset；写明 `_sync_legacy_fields(session)` helper 契约 | D2 已敲 |
| S3 | #2 mode/phase 重复 | 删 `mode` 字段；`phase` 单一数据源 | 全局原则 §单一数据源 |
| S4 | #3 类型未定义 | 补 `CompletedResult` / `Message` 定义 | 现在 spec 引用了不存在的类型 |
| S5 | #4 Observation.data | 改 `data: Any` 为 per-action discriminated union | manifest 里声明每个 action 的 data schema |
| S6 | #5 OptionSet hot-reload | `OptionSet` 加 `skill_version` + `created_at`，TTL 5 分钟 | watcher reload 后旧 OptionSet 过期 |
| S7 | #7 多进程 lock | spec 写「当前单实例，未来加 Redis lock 时改 _user_locks → redis SET NX」契约 | D3 |
| S8 | #8 updated_params 校验 | 按 `skill.params` 白名单 key + 对已有 value "字面相等" 防 `bill→billbill` | 加 input validation 层 |

### P1（设计澄清）

| ID | 对应 audit | 改动点 |
|---|---|---|
| S9 | #9 | 明确 `complete`（正常完成保留 session）vs `exit_skill`（中断清 session）|
| S10 | #10 | manifest 标注哪些 action 是 long-running → 走 `submit_job` |
| S11 | #11 | OptionSet paging 由 `OptionResolver` 切分（lazy_resource 仍一次性返回）|
| S12 | #12 | 补完整 State Transition Table：`(phase, intent) → (next_phase, side_effects)` |
| S13 | #13 | `OptionSet.scope: Literal["skill_param","system"]`，timeout 菜单是 system |
| S14 | #14 | 依赖 R2 结论 |
| S15 | #15 | TurnClassifier 冲突仲裁规则：OptionResolver 优先 > deterministic > LLM；列 fallback 表 |
| S16 | #16 | 定义 `ObservationReducer` 契约（输入/输出/触发时机）|
| S17 | #17 | simple skill（无 `system_prompt_core`）走 fast-path：不进 `SkillRuntime`，直接 ask 第一个 param |
| S18 | #18 | enum param 自动构造 `OptionSet`；保留 `_enum_options_block` 作 deterministic 兜底层 |

### P2（小项）

| ID | 对应 audit | 改动点 |
|---|---|---|
| S19 | #19 | 删 `turn_count`（无用途）|
| S20 | #20 | `chitchat` 用模板回复（"我还在当前任务里…"）|
| S21 | #21 | transcript 脱敏标准：open_id → `<USER_N>`，file_id → `<FILE_N>`，写到 `tests/fixtures/transcripts/README.md` |
| S22 | #22 | 区分：`chat_history` 给 LLM（短，10 条），`transcript` 给 eval（长全脱敏）|
| S23 | #23 | observation 累积超 3 条自动摘要为 `summary` only |
| S24 | #24 | router 多 skill 命中 → 构造 disambiguation `OptionSet` |
| S25 | #25 | `ActiveJob.payload` 强制只存 `fileId` 引用；依赖 R4 |

---

## 待 Johnny 确认

1. ✅ D1 A1 方案
2. ✅ D2 v1 回退接受 `running_job` 损失
3. ❓ 本文件留 docs/ 还是同步开成 GitHub issue？
   - **倾向 GitHub issue**：评论可时序追加调研结果，关闭时 close = 决策落地
   - 留 docs/ 优势：跟 spec 在同一仓库，对照方便
   - 推荐：**两者并存** — md 留仓库作为最终落地版本，issue 用作过程讨论
4. ❓ 调研 R1-R4 谁来做？
   - R1 需要真实飞书 app 凭证（你 .env 有），建议你本地跑
   - R2 需要 toolbox 服务可达，我可在 SSH 隧道下跑
   - R3 可独立写 demo
   - R4 我可以独立跑（拼一个 mock payload）

---

## 下一步流程

```
R1-R4 调研 → 结论回写本文件
   ↓
S1-S25 按优先级改 spec
   ↓
spec v2 提 PR 给你 review
   ↓
PLAN 同步更新（验收标准 + 灰度 SOP）
   ↓
P0 → P6 实施
```
