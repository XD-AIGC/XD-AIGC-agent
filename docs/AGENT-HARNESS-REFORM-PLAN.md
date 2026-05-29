# Agent Harness 改造 Plan（v2，重写）

> 配套文档：
> - `docs/AGENT-HARNESS-REFORM-SPEC.md`（架构与静态契约）
> - `docs/AGENT-HARNESS-REFORM-RUNTIME.md`（运行时）
> - `docs/AGENT-HARNESS-REFORM-OPEN-ITEMS.md`（决策追踪）
>
> 重写依据：issue#2 + OPEN-ITEMS。原 P0-P6 六阶段被合并/重排为新 P0-P4 四阶段；新 P0 拆三个 PR。

## 阶段总览

| 阶段 | 目标 | PR 数 | 风险 |
|---|---|---|---|
| **P0 地基** | transcript + session v2 + OptionSet 三个独立 PR | 3 | 低（不接 runtime）|
| **P1 状态机** | State machine + TurnClassifier + ResponseComposer | 1 | 中（行为可见）|
| **P2 异步运行时** | JobController 拆三个 PR：idempotency → worker → cancel/timeout | 3 | 高（依赖 R1 / R3）|
| **P3 Prompt 精简** | SkillRuntime + 收窄 SkillRuntimeAction | 1 | 中（prompt 回归）|
| **P4 Eval + 灰度** | transcript eval 全绿 + runtime dry-run 标签 + 部署级回滚 SOP | 1 | 中（线上回归）|

约束：每个 PR 体积 ≤ 500 行 diff；CI 必须包含 `bash ci/check-banned-apis.sh`。

---

## P0：地基（三件事 = 三个独立 PR）

### PR-0a：transcript fixture + runner（含 S27 行为轨迹）

- 建 `tests/fixtures/transcripts/*.json` 目录与脱敏脚本 `redact.py`（S21）
- runner 能回放多轮 Feishu 对话，先 mock 现有 v1 跑通（暴露 bug，不修）
- **断言必须包含行为轨迹**（S27）：LLM 调用次数 / skill action / submit_job / phase 变化 / last_options 写入 / last_processed_message_ids
- CI 必须 lint 检查 fixture 中无原始 `ou_*/om_*/oc_*/fileId` 真实 ID

**首批 fixture**：`3→33` / `billbill` / 完成后问能力 / 完成后问日期 / 生成中插话 / 比例选择 / 确认后生成 / 重启恢复占位（先标 xfail）

**验收**：
- runner 跑 ≥8 条 fixture，全绿或显式 xfail
- 脱敏脚本 + lint CI 接入
- 不引入 runtime 改动

### PR-0b：ConversationSession v2 + 双向兼容（纯数据层）

- 新 `src/conversation/session.py`：`ConversationSession` / `ConversationPhase` / `Message` / `CompletedResult`（含 `last_processed_message_ids`）
- 旧 `src/orchestrator/schema.py` 的 `UserSession` 标记 deprecated 但保留
- `SessionStore` 升级：`load_session` 自动 v1→v2 迁移；`save` 强制调 `_sync_legacy_fields(session)`（SPEC §7.2.2）
- **运行时尚不切换到 v2**（main.py 继续用 v1 路径）
- 加单测：v1→v2 迁移矩阵、v2→v1 mirror 矩阵、回退场景四种 phase 的退化行为（SPEC §7.2.3）

**验收**：
- 单测覆盖 4 种回退场景
- `bash ci/check-banned-apis.sh` 通过
- main.py 行为零变化（PR-0a fixtures 全绿）

### PR-0c：OptionSet + OptionResolver

- 新 `src/conversation/options.py`：`OptionItem` / `OptionSet`（含 `scope/skill_version/created_at/ttl_sec`，SPEC §9）
- 新 `src/conversation/option_resolver.py`：数字 / 别名 / 更多 / 返回 解析；过期重新展示（D5）
- 替换 `src/main.py:_resolve_numbered_character_reply`：迁到 OptionResolver；旧逻辑保留 fallback 一个 release
- 单测：OptionSet TTL 过期、skill_version 不一致、enum 来源、router_disambiguation 来源

**验收**：
- `3→33` fixture 转绿
- enum / lazy_resource / runtime 三个 source 都有单测
- OptionResolver 在 main.py 接入但不破坏现有路径

---

## P1：状态机 + TurnClassifier（原 P3）

- 新 `src/conversation/state_machine.py`：按 RUNTIME §3 State Transition Table 实现 `(phase, intent) → (next_phase, side_effects)`
- 新 `src/conversation/classifier.py`：分类层级 OptionResolver → Deterministic → LLM（RUNTIME §4）
- 新 `src/conversation/response.py`：ResponseComposer，把散落 reply 文本集中（SPEC §13）
- main.py 改造：用 phase 替代 `mode/completed/state`；保留 mirror 字段（PR-0b 已铺路）

**验收**：
- 完成后问能力 / 谢谢 / 今天周几 三条 fixture 转绿
- 单数字 + 角色名 + 别名 fixture 全绿
- `取消主标题` 不命中 cancel
- `bash ci/check-banned-apis.sh` 通过

---

## P2：JobController + Background Worker（原 P4，最有风险）

> Johnny 提醒：A1 worker 一旦上，就把"重复 submit/重启恢复"问题放大。所以**幂等先于 worker**。

### PR-2a：JobController + 幂等（S26）+ 用户触发恢复（D4）

- 新 `src/skill/job_controller.py`：`ActiveJob` model + 同步 submit（继续阻塞 reply 链，不接 worker）
- 幂等三件套：`source_message_id` 去重 / 三元组唯一 / session CAS（RUNTIME §1.2）
- `payload` 软上限 10KB 校验，超限拒绝（R4）
- 用户触发恢复入口（D4）：`phase=running_job` 下任何消息 → 检查 worker 不存在则拉起（PR-2b 接管）
- 此 PR 不动 reply 链同步行为；只是把 submit/poll 路径迁到 JobController

**验收**：
- 飞书事件重投递同 `message_id` 不创建第二个 job（fixture）
- payload 含 base64 拒绝 submit
- 现有 retry 快路径行为不变

### PR-2b：Background Worker（A1，依赖 R1/R3）

- 实现 `_background_poll(active_job, message_id)`（RUNTIME §2.1）
- submit 后立即 reply "✅ 已开始生成…" 并释放 user_lock
- 完成时 delayed reply 到 source_message_id（R1 实测 ≥5.6h 有效）
- timeout 走 system OptionSet 给"继续等/重试/修改/取消"
- D4 恢复路径接通：用户触发时 reply 到当前 msg（而非原 source_msg）
- 红线 grep：仍只用 `message.reply`

**验收**：
- 完成后 delayed reply 收到图片（mock + 真实环境各一次）
- timeout fixture 给出菜单
- 重启演练：杀进程 + restart + 用户发"还在吗" → 恢复并发图

### PR-2c：cancel + ResponseComposer 文案锁定

- 用户"取消" → `cancelled_locally=True`，worker 退出
- 文案锁定为 R2 版本：「我已停止等待这次结果，后续即使完成也不会再发送。」
- 不调 toolbox cancel API
- ResponseComposer 增加 timeout / cancel / retry / chitchat 模板

**验收**：
- 取消 fixture 通过，文案精确匹配
- 取消后再"再来一张"，旧 job 不影响新 job

---

## P3：SkillRuntime 精简 prompt（原 P5）

- 新 `src/skill/runtime.py`：替代当前 `skill_decide`
- prompt 不再承担状态控制（SPEC §14）；只负责参数提取 + action 规划
- `BotAction` → `SkillRuntimeAction` 严格 typed（含 `complete` / `exit_skill` 区分，SPEC §10.1）
- `updated_params` value provenance 校验（SPEC §10.2）：enum 必须来自 `OptionSet.value`；自由文本必须来自 user text；`bill→billbill` 这类字面非相等的扩写拒绝
- `Observation` 两层方案（SPEC §11）：内置 schema_id 注册表 + manifest 声明未知 action 的 schema_id

**验收**：
- `billbill` fixture 转绿
- 新增生图 skill 不需要改主流程，只需 manifest + SKILL.md
- LLM 输出 unknown action 被 pydantic 拒

---

## P4：Eval + 灰度部署（原 P6）

- transcript eval ≥ 12 条全绿（含 S27 行为轨迹断言）
- L20-1 dry-run 标签：`AGENT_RUNTIME_DRY_RUN_TARGET=v2`（按 user_id hash 分桶；不切换执行路径）
- 不做进程内 v1/v2 dispatch；v1 不是独立执行器，代码级回滚靠部署上一版镜像/commit（详 `docs/RUNTIME-DRY-RUN.md` §8）
- 灰度 10% → 1 周观察 → 50% → 1 周 → 100% + 真实 bot smoke test
- 监控：`phase=running_job` 异常率、duplicate submit 计数、delayed reply 失败率
- 回退 SOP：先 flip 标签回 v1；必要时部署上一版代码，不清 Redis，靠 TTL=1h 自然消化；接受 `running_job` 通知丢失（D2）
- 跑稳 2 周后：删 v1 兼容 mirror 字段（schema_version=3，单独 PR）

**验收**：
- 测试总数 ≥ 120（含 ≥12 条 transcript）
- `bash ci/check-banned-apis.sh` 通过
- 灰度期间无 forbidden API 调用
- 监控 24h 无 running_job 异常

---

## 风险表

| 风险 | 级别 | 缓解 |
|---|---|---|
| delayed reply 在生产环境 TTL 比实测短 | 高 | A1 上线后第一周监控 reply 失败率；失败率 >1% 立刻退化 A2 |
| v2 session 迁移破坏线上上下文 | 高 | `_sync_legacy_fields` 强制约束 + 单测覆盖回退矩阵 |
| 幂等漏洞导致重复扣费/生成 | 高 | PR-2a 单测覆盖 4 种重投递场景；CI 必须包含 |
| 状态机过硬导致不够智能 | 中 | 状态只管边界；参数理解仍交 LLM |
| Background worker 内存泄漏（长跑积累）| 中 | worker 完成/取消必须 close session；R3 测过 130s 单次 |
| prompt/context 变长 | 中 | skill lazy load + observation 摘要（S23）|
| 开发中重复线上事故 | 中 | transcript eval 先行 |

---

## 待确认问题（PLAN 层）

1. dry-run 标签灰度比例阈值（10/50/100% 是建议，可调）
2. `/取消`、`/重新开始`、`/帮助` 是否要作为用户可见斜杠命令？（当前用 deterministic classifier）
3. 运行中是否需要中间进度消息（如"已生成 step1，正在合成…"），还是只在开始和完成时回？

---

## 与 issue#2 的对应

| 阶段 | 关闭的 S 编号 |
|---|---|
| P0 PR-0a | S21, S27（基础部分）|
| P0 PR-0b | S2, S3, S4, S19 |
| P0 PR-0c | S6, S13, S18, S24 |
| P1 | S12, S15, S20 |
| P2 PR-2a | S25, S26, R4 落地 |
| P2 PR-2b | S1, D1, D4, R1/R3 落地 |
| P2 PR-2c | S14, R2 落地 |
| P3 | S5, S8, S9, S10, S11, S16, S17, S22, S23 |
| P4 | 灰度 SOP + 监控落地 |

每个 PR description 必须列出 `Closes part of #2` 并勾选对应 S 项。
