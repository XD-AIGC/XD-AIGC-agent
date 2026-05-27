# Agent Harness 改造 Spec — Runtime

> 配套主 spec：`docs/AGENT-HARNESS-REFORM-SPEC.md`。本文件聚焦运行时（JobController、Background Worker、状态机、分类仲裁、并发约束），与主 spec 静态契约分册。
> 拆分原因：合体后超过 500 行（OPEN-ITEMS 决策 B）。

## 1. JobController（含幂等 S26、用户触发恢复 D4、本地取消 R2）

`active_job` 用于所有异步任务。

```python
class ActiveJob(BaseModel):
    job_id: str
    skill_name: str
    action_name: str
    payload: dict                  # ≤10KB compact refs，禁 bytes/base64/signed URL/完整资源列表（R4）
    source_message_id: str         # S26 幂等关键：哪条 user msg 触发的本 job
    status: Literal["submitted", "running", "completed", "failed", "cancelled", "timeout"]
    started_at: float
    last_poll_at: float | None = None
    poll_count: int = 0
    last_observation: Observation | None = None
    # cancelled_locally: bot 已停止 listen；后端 job 仍在跑，结果将被丢弃（R2: toolbox 无服务端 cancel）
    cancelled_locally: bool = False
```

### 1.1 状态流

```
submit_job
  ↓ (幂等校验：见 1.2)
active_job.status=submitted → running
  ↓ (poll worker，详见 §2)
completed | failed | timeout | cancelled_locally
```

### 1.2 幂等校验（S26）

`submit_job` 入口必须校验：

1. **`source_message_id` 去重**：若 `source_message_id ∈ session.last_processed_message_ids`，拒绝重复 submit，直接返回已存在的 `active_job`。
2. **三元组唯一**：同一 `(user_id, source_message_id, skill_name)` 在 Redis 全局只允许一个 active_job。冲突时返回已有 job，不创建新的。
3. **session 版本**：submit 时校验 `session.updated_at` 是否未被并发修改（CAS-like 防御），失败重读 session。

submit 成功后：`session.last_processed_message_ids.append(source_message_id)`，滚动保留最近 20 条。

### 1.3 用户交互

- **取消**（toolbox 无服务端 cancel，R2）：
  - `active_job.cancelled_locally=True`，poll worker 退出，结果丢弃
  - 文案锁定为：**「我已停止等待这次结果，后续即使完成也不会再发送。」**
  - 不写 "已取消生成"（误导）
- **继续等**：什么都不做；poll worker 仍在跑就让它跑（reply-only 约束下，结果完成时 worker 会 delayed reply）
- **重试**：复用 `completed_result.submitted_payload` 重新 submit；旧 worker（如果还在）独立结束、结果丢弃
- **修改**：退出 running/completed → 回 `collecting`，清 `active_job`

### 1.4 timeout 策略

timeout 不直接结束对话；通过 `OptionSet`（`scope="system"`，详见主 spec §9）回复用户：

```text
生成还没完成。你可以：
1. 继续等待
2. 重试
3. 修改信息
4. 取消
```

### 1.5 状态恢复（D4：用户触发恢复，非启动时扫描）

**约束**：进程重启时 in-memory `asyncio.Task` 必丢，Redis `active_job` 是唯一可信状态源（R3）。

**恢复策略**：
- **不在启动时自动扫描所有 `active_job` 起 worker**——reply-only 约束下，对没人 listen 的 message_id 主动 reply 等于无效操作；且大量并发 poll 容易冲爆 toolbox。
- **由用户下一句触发**：用户在 `phase=running_job` 下发任何消息（如"还在吗"、"好了没"、"继续等"），ConversationManager 检测到 `active_job` 存在且无 in-memory worker，则即时拉起 worker 继续 poll；poll 完成后 delayed reply 到**当前这条** user msg（而非原 source_message_id）。
- 用户 30 分钟内不回来 → active_job 留在 Redis（TTL=1h 自然失效）。

### 1.6 payload 大小约束（R4）

`active_job.payload` 序列化后**软上限 10KB**。超过则拒绝 submit，要求改为引用形式（fileId / public_id）。禁止内容：
- 图片 bytes / base64
- signed URL（过期就是垃圾数据）
- 完整 lazy_resource 列表（如全部角色清单）

---

## 2. Background Worker（S1，依赖 D1 / R1 / R3）

A1 方案：异步 job poll 不阻塞 user reply 链；完成时 delayed reply 原 message_id。

### 2.1 生命周期

```
ConversationManager:
  submit_job(payload, source_message_id)
    → 1.2 幂等校验
    → 创建 ActiveJob，写 Redis
    → asyncio.create_task(_background_poll(active_job, source_message_id))
    → 立即 reply "✅ 已开始生成，预计 30-60s"
    → 释放 user_lock

_background_poll(active_job, message_id):
  while not active_job.cancelled_locally and elapsed < timeout:
    poll backend
    if done:
      reply_image(client, message_id, result)   # delayed reply
      session.phase = completed
      session.completed_result = CompletedResult(...)
      return
    sleep(2s)
  if timeout:
    reply_text(client, message_id, "生成还没完成。你可以：1. 继续等待 2. 重试 3. 修改信息 4. 取消")
    # 保留 active_job；用户下一句触发 D4 恢复
```

### 2.2 约束

- **Redis `active_job` 是唯一可信状态源**（R3）。in-memory `asyncio.Task` 仅作执行器，不作状态。
- **delayed reply 有时效**（R1 实测 ≥5.6h 有效；不宣称永久）。超长 job 走 D4 用户触发恢复。
- **进程重启**：丢失所有 in-memory worker。不在启动时自动 resume（D4）。
- **取消**：set `cancelled_locally=True`；worker 检测到即退出；不调 toolbox cancel API（R2）。
- **延迟 reply 仍是 `message.reply`，不是 `message.create`**（红线合规）。

### 2.3 异常处理

| 异常 | 行为 |
|---|---|
| poll HTTP 5xx | 指数退避（2s/4s/8s），最多 5 次后转 timeout 路径 |
| job_id 后端返回 not_found | `active_job.status=failed`，reply 友好错误 |
| event loop 关闭（罕见） | 重启后用户触发恢复（D4）|

---

## 3. State Transition Table（S12）

完整状态机：`(phase, intent) → (next_phase, side_effects)`

| 当前 phase | intent | next phase | side effects |
|---|---|---|---|
| idle | start_skill | selecting_skill 或 collecting | 设 skill_name；若 simple skill 走 fast-path 直接 collecting |
| idle | ask_capability | idle | reply 能力清单 |
| idle | chitchat / unrelated | idle | reply 模板 / out_of_scope |
| selecting_skill | answer_option (router_disambiguation) | collecting | 锁定 skill；清 last_options |
| collecting | answer_option | collecting | 写 collected_params；OptionResolver 推进 |
| collecting | provide_param | collecting | 写 collected_params；可能转 awaiting_confirmation |
| collecting | modify_param | collecting | 改 collected_params |
| collecting | cancel | idle | 清 collected_params/artifacts/last_options |
| awaiting_confirmation | confirm | running_job | submit_job（含 §1.2 幂等）|
| awaiting_confirmation | modify_param | collecting | 退回收集 |
| awaiting_confirmation | cancel | idle | 同上 |
| running_job | cancel | completed | `cancelled_locally=True`；reply R2 文案 |
| running_job | continue_wait | running_job | no-op（worker 在跑）|
| running_job | ask_status | running_job | reply 状态；若无 worker 触发 D4 恢复 |
| running_job | unrelated | running_job | reply "我还在生成中…" |
| completed | retry | running_job | 复用 completed_result.submitted_payload 重 submit |
| completed | modify_param | collecting | 退回收集 |
| completed | start_skill | selecting_skill | 切换 skill |
| completed | ask_capability / chitchat | completed | reply 模板（不触发 submit）|
| completed | unrelated | completed | reply 边界提示 + 能力清单 |
| cancelled | start_skill | selecting_skill | 切换 |
| failed | retry | running_job | 复用 payload |
| failed | modify_param | collecting | 退回 |
| failed | cancel | idle | 清 session |

---

## 4. TurnClassifier 仲裁（S15）

多分类器命中冲突时的优先级：

```
OptionResolver (deterministic, scope-aware)
  ↓ 无命中
Deterministic regex/keyword classifier
  ↓ 无命中
LLM classifier (typed intent)
```

### 4.1 冲突示例

| 输入 | OptionResolver | Deterministic | LLM | 仲裁 |
|---|---|---|---|---|
| `3` (有 last_options) | match index=3 | 数字短语 | quantity? | **OptionResolver** |
| `3` (无 last_options) | miss | 数字短语 | quantity? | LLM 决定 |
| `取消主标题` | miss | match cancel | modify_param | **LLM**（deterministic 退让，因为含动作宾语）|
| `继续等` | miss | match continue_wait | continue_wait | Deterministic |
| `谢谢` | miss | match chitchat | chitchat | Deterministic |

### 4.2 Deterministic 退让规则

`cancel/retry/continue_wait/chitchat` 类 deterministic 命中时，若文本**额外包含动作宾语**（如"取消**主标题**"），退让给 LLM 重新分类，避免误删 modify_param 意图。

---

## 5. 多进程与并发约束（S7）

### 5.1 当前阶段：单实例约束

- `_user_locks: dict[str, asyncio.Lock]` 仍为单进程内存锁
- L20-1 部署 `replicas=1`，spec 写明此前提
- 不实现 Redis 分布式锁

### 5.2 未来扩展契约

横向扩展时按以下契约改造（不在本次改造范围）：

- per-user lock：`_user_locks` → `SET NX session_lock:{user_id} <instance_id> EX 30`
- active_job ownership：`SET NX job_owner:{job_id} <instance_id> EX 60`，worker 定期续期
- 启动 resume 仍走 D4 用户触发，多实例时 OptionResolver/ JobController 通过 ownership 决定是否处理
