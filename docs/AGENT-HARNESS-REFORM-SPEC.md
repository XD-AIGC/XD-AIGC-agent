# Agent Harness 改造 Spec

> 目标：把当前“Router + Skill prompt + 若干规则补丁”改造成受限 Hermes 风格的对话运行时。
> 约束：只服务公司内部；只调用白名单 toolbox skill；不扩大飞书权限；不引入 Hermes 的本机文件/命令大权限。
> 文档规则：spec 已拆分为两个文件——
> - 本文件（架构与静态契约）：≤600 行
> - `docs/AGENT-HARNESS-REFORM-RUNTIME.md`（运行时：JobController / Background Worker / State Table / 仲裁 / 并发）：≤250 行
> 拆分依据见 `docs/AGENT-HARNESS-REFORM-OPEN-ITEMS.md` 决策 B。

## 1. 背景

当前线上问题不是单个 skill 的问题，而是 agent 编排层不成熟。已经观察到的症状：

- 用户回复 `3` 被模型理解成 `33`。
- 用户回复 `bill` 被模型理解成 `billbill`。
- 比例/构图编号可能被旧逻辑当成角色编号。
- 完成后用户问“还能做什么”或“今天周几”仍可能触发 submit。
- 生成中用户插话时，系统只有 per-user lock，没有真正的 job intent 处理。
- LLM 在多阶段 skill 中可能重复调用 Step 1、重复 poll、重复 submit。
- 对话体验偏“脚本机器人”，不像 Hermes 那样能理解任务边界、进度、恢复和转场。

根因：

1. 当前 session schema 太薄，只保存少量字段。
2. 状态边界不清晰，`completed=True` 不是完整状态机。
3. 选项没有结构化持久化，靠上一条回复文本反推。
4. tool observation 格式不统一，LLM 不容易稳定接续。
5. prompt 同时承担状态控制、参数理解、工具规划，职责过重。

## 2. Hermes 对比结论

Hermes 的鲁棒性来自完整 agent loop，而不是某个“聪明 prompt”：

- 统一 conversation loop：历史 -> prompt/context -> model -> tool calls -> observations -> model。
- 所有工具调用都有 observation，并作为消息回到模型上下文。
- 有 interrupt / retry / fallback / context compression / persistent session。
- skill 是程序性记忆，作为完整上下文注入，而不是只靠 manifest 字段。
- 会话轨迹可恢复、可搜索、可复盘。

本项目不能照搬 Hermes，因为 Hermes 权限过大。我们的目标是“受限 Hermes”：

- 借鉴对话循环、状态、观察、恢复。
- 仍只允许 toolbox HTTP、Feishu reply/upload/download、LLM proxy。
- 不开放 shell、file、browser、MCP 泛化工具。

## 3. 设计原则

### 3.1 状态先于 prompt

每轮消息先经过状态机判断，再决定是否进入 LLM。

示例：

- `phase=completed` + 用户问“今天周几” -> 不进 skill LLM。
- `phase=completed` + 用户说“换成横版” -> 允许进 skill LLM 修改参数。
- `phase=running_job` + 用户说“取消” -> JobController 取消/停止等待。

### 3.2 结构化选项优先

任何编号菜单都必须保存 `OptionSet`。

禁止：

- 从 assistant 文本 regex 解析编号。
- 让 LLM 自己记“上一轮 1-8 是哪些角色”。

### 3.3 观察统一

每个后端调用都返回统一 observation：

- status
- summary
- data
- artifacts
- next_actions
- stop_condition

LLM 只看 observation，不看散乱异常字符串。

### 3.4 完成态默认不继续

任务完成后，用户下一句默认不是继续生成。只有明确重试或修改时才继续当前 skill。

明确继续：

- 再来一张
- 重做
- 换成横版
- 主标题改成 XX
- 角色换成 XX

不继续：

- 谢谢
- 你还能做什么
- 今天周几
- 好的
- 帮我看看你有哪些功能

### 3.5 LLM 只做理解和规划

LLM 不负责：

- 保存状态
- 维护 job
- 生成编号菜单格式
- 判断是否允许提交
- 解析数字编号

LLM 负责：

- 从自然语言提取参数
- 在当前状态内选择下一步 action
- 依据 SKILL.md 规划必要工具调用
- 用中文生成自然回复

## 4. 非目标

- 不改飞书权限范围。
- 不把 Hermes 作为运行时依赖。
- 不要求改 skill 仓库才能启动改造。
- 不实现用户 OAuth / user_access_token。
- 不开放本机文件、shell、browser、docs、drive、contact 权限。
- 不在第一阶段实现长期 memory 或自动 skill 生成。

## 5. 目标架构

```
Feishu Message
  -> MessageNormalizer
  -> ConversationManager
       -> SessionStore
       -> TurnClassifier
       -> StateMachine
       -> OptionResolver
       -> JobController
       -> SkillRuntime
            -> SkillContextBuilder
            -> ToolPlanner(LLM typed action)
            -> ToolExecutor
            -> ObservationReducer
       -> ResponseComposer
       -> TranscriptRecorder
  -> Feishu reply-only
```

## 6. 模块职责

| 模块 | 职责 |
|---|---|
| `conversation/session.py` | v2 session model、兼容迁移、phase 定义 |
| `conversation/classifier.py` | turn intent 分类，先规则后 LLM |
| `conversation/state_machine.py` | phase + intent -> allowed transition |
| `conversation/options.py` | 结构化菜单、分页、编号/别名解析 |
| `conversation/runtime.py` | 单轮 orchestrator，替代 `_agentic_loop` 大函数 |
| `conversation/response.py` | 回复文案、菜单渲染、完成/错误收尾 |
| `conversation/transcript.py` | 真实对话轨迹记录和脱敏 |
| `skill/runtime.py` | skill 上下文构建、typed action loop |
| `skill/job_controller.py` | submit/poll/retry/continue_wait/cancel/timeout |
| `skill/observation.py` | 后端结果标准化 |
| `evals/transcripts/` | 回放测试 fixture |

## 7. Session Model

新增 `ConversationSession`，旧 `UserSession` 作为迁移输入。**`phase` 是状态唯一源**（删 `mode` 字段——`mode` 可由 `phase` 推导，保留两个会导致状态分叉，违反单一数据源原则）。

```python
class ConversationPhase(str, Enum):
    idle = “idle”
    selecting_skill = “selecting_skill”
    collecting = “collecting”
    awaiting_confirmation = “awaiting_confirmation”
    running_job = “running_job”
    completed = “completed”
    cancelled = “cancelled”
    failed = “failed”

class Message(BaseModel):
    role: Literal[“user”, “assistant”]
    content: str

class CompletedResult(BaseModel):
    submitted_payload: dict       # 最后一次成功 submit 的参数（供”再来一张”复用）
    artifacts: dict               # fileId / image_key 等结果引用
    completed_at: float
    source_message_id: str        # 完成那一轮的 user message_id

class ConversationSession(BaseModel):
    schema_version: int = 2
    # === 状态唯一源 ===
    phase: ConversationPhase = ConversationPhase.idle
    skill_name: str | None = None
    initial_intent: str | None = None
    collected_params: dict = Field(default_factory=dict)
    pending_param: str | None = None
    last_options: OptionSet | None = None
    active_job: ActiveJob | None = None
    artifacts: dict = Field(default_factory=dict)
    completed_result: CompletedResult | None = None
    chat_history: list[Message] = Field(default_factory=list)
    # 幂等防御（S26）：已处理过的 user message_id；submit 前查重，防飞书事件重投递 + 用户重复确认
    last_processed_message_ids: list[str] = Field(default_factory=list)
    updated_at: float
    # === v1 兼容 mirror 字段（_sync_legacy_fields 自动同步，v2 逻辑禁用）===
    mode: Literal[“router”, “skill”] = “router”         # derived: phase==idle → router else skill
    completed: bool = False                              # derived: phase == completed
    state: Literal[“idle”, “collecting”] = “idle”       # derived: phase ∈ {collecting, awaiting_confirmation}
    loaded_resources: dict[str, str] = Field(default_factory=dict)
```

### 7.1 字段解释

- `phase`：当前会话状态，**唯一权威**；`mode/completed/state` 都从它派生。
- `last_options`：最后一次展示给用户的结构化菜单（详见 §9）。
- `active_job`：正在运行或可继续等待的后端任务（详见 §12）。
- `artifacts`：step1FileId、finalImageFileId、uploaded image key 等中间产物。
- `completed_result`：最后一次完成快照，用于”再来一张/换标题”复用。
- `chat_history`：给 LLM 看的短历史（最近 10 条），不承担状态职责；与 transcript（§16）区分。
- `last_processed_message_ids`：S26 幂等关键；滚动保留最近 20 条。

### 7.2 双向兼容（v1 ↔ v2 灰度回退）

**原则**：v2 schema = v1 superset。v2 写入时强制 mirror v1 兼容字段，v1 读 v2 数据时可降级运作；回退后 `running_job` 状态丢失（按 D2 接受损失）。

#### 7.2.1 v1 → v2 读取（升级）

```python
def load_session(raw: bytes) -> ConversationSession:
    data = json.loads(raw)
    if data.get(“schema_version”, 1) == 1:
        data[“phase”] = (
            ConversationPhase.completed if data.get(“completed”)
            else ConversationPhase.collecting if data.get(“state”) == “collecting”
            else ConversationPhase.collecting if data.get(“mode”) == “skill” or data.get(“skill_name”)
            else ConversationPhase.idle
        )
        data[“schema_version”] = 2
    return ConversationSession.model_validate(data)
```

#### 7.2.2 v2 → v1 写入兼容（`_sync_legacy_fields`）

**强制约束**：每次 `SessionStore.save(session)` 前**必须**调用 `_sync_legacy_fields(session)`，否则切 v2 再回滚 v1，v1 读不到完成态。建议把 save 与 sync 合并为一个不可分调用（实现层防御）。

```python
def _sync_legacy_fields(s: ConversationSession) -> None:
    s.mode = “router” if s.phase == ConversationPhase.idle else “skill”
    s.completed = s.phase == ConversationPhase.completed
    s.state = “collecting” if s.phase in {
        ConversationPhase.collecting,
        ConversationPhase.awaiting_confirmation,
    } else “idle”
```

#### 7.2.3 回退场景行为

| v2 phase | v1 看到 | 退化行为 |
|---|---|---|
| `collecting` | state=collecting + pending_param | 继续问 param ✅ |
| `completed` | completed=True + collected_params | retry 快路径可用 ✅ |
| `running_job` | mode=skill，**active_job 丢失** | v1 不能继续 poll；用户收不到结果。**D2 接受** |
| `awaiting_confirmation` | state=collecting + pending_param=None | v1 LLM 会重新问参数，体验差但不崩 |

## 8. Turn Intent

```python
class TurnIntent(str, Enum):
    start_skill = "start_skill"
    answer_option = "answer_option"
    provide_param = "provide_param"
    modify_param = "modify_param"
    confirm = "confirm"
    retry = "retry"
    continue_wait = "continue_wait"
    cancel = "cancel"
    ask_status = "ask_status"
    ask_capability = "ask_capability"
    unrelated = "unrelated"
    chitchat = "chitchat"
```

### 8.1 分类策略

TurnClassifier 分两层：

1. deterministic classifier：处理高置信、危险或状态边界意图。
2. LLM classifier：只在 deterministic 无法判断时使用，输出 typed intent。

deterministic 必须覆盖：

- 取消：取消、停下、不要了、算了。
- 重试：再来一张、重新生成、重做。
- 继续等待：继续等、再等等。
- 能力询问：你能做什么、还有什么功能、还能做什么。
- 单数字：如 `3`，优先交给 OptionResolver。
- 确认：确认、可以、继续、就这样。

### 8.2 状态边界

| phase | 允许 intent | 默认处理 |
|---|---|---|
| `idle` | start_skill, ask_capability, chitchat, unrelated | router 或能力说明 |
| `collecting` | answer_option, provide_param, modify_param, cancel | option/skill runtime |
| `awaiting_confirmation` | confirm, modify_param, cancel | submit 或回收集 |
| `running_job` | cancel, continue_wait, ask_status, unrelated | JobController |
| `completed` | retry, modify_param, start_skill, ask_capability, chitchat, unrelated | 默认不 submit |
| `cancelled` | start_skill, ask_capability, chitchat | router |
| `failed` | retry, modify_param, cancel, start_skill | recovery |

## 9. OptionSet（含 scope S13、过期刷新 D5、skill_version S6）

所有用户可选菜单都用统一结构。

```python
class OptionItem(BaseModel):
    index: int
    label: str
    value: Any                              # 写入 collected_params 的最终值；value provenance 唯一合法源（S8）
    param_name: str
    aliases: list[str] = Field(default_factory=list)

class OptionSet(BaseModel):
    id: str
    param_name: str                          # scope=”system” 时可以是 “_system” 之类的保留名
    scope: Literal[“skill_param”, “system”] = “skill_param”  # S13
    source: Literal[“enum”, “resource”, “skill_runtime”, “router_disambiguation”]
    items: list[OptionItem]
    page: int = 1
    page_size: int = 8
    allow_multi: bool = False
    # 防 hot-reload / 长会话陈旧（S6 + D5）
    skill_version: str | None = None         # skill manifest hash；scope=system 时 None
    created_at: float
    ttl_sec: int = 300                       # 默认 5min；过期不删，再用时强制刷新
```

### 9.1 解析规则

- 用户回复数字 → 匹配当前 page 的 `index`。
- 用户回复多个数字 → 仅 `allow_multi=True` 时允许。
- 用户回复名称 → 匹配 `label` 或 `aliases`。
- 用户回复 `更多/more` → page + 1。
- 用户回复 `返回/back` → page - 1。
- 无匹配 → 生成”没找到，请选当前列表编号或名称”，不进 LLM。

### 9.2 过期刷新（D5）

OptionSet 命中”过期”（`time.time() - created_at > ttl_sec`，或 `skill_version` 与当前 skill 不一致）时：
- **不删** `last_options`
- 下次需要解析时：**先重新构造同 `param_name` 的 OptionSet 并展示**，要求用户重新确认选择；不直接按陈旧菜单解析

示例话术：
```text
菜单可能已更新，请确认你的选择：
1. ...
2. ...
```

### 9.3 菜单来源

- `enum`：manifest 声明的 enum 参数（比例、分辨率、角色类型）
- `resource`：lazy_resource 拉取结果（角色、动物、场景）
- `skill_runtime`：LLM 按 SKILL.md 生成的临时选项，必须落成 OptionSet 后再展示
- `router_disambiguation`（S24）：router 多 skill 命中时的二选一菜单

## 10. SkillRuntimeAction（含 value provenance S8、complete vs exit_skill S9）

当前 `BotAction` 过宽，收窄为：

```python
class SkillRuntimeAction(BaseModel):
    action: Literal[
        "ask_options",
        "ask_free_text",
        "call_skill_action",
        "submit_job",
        "reply",
        "complete",       # 任务正常结束；保留 collected_params / completed_result，phase→completed
        "exit_skill",     # 用户中断或换需求；清 collected_params/artifacts，phase→idle
    ]
    param_name: str | None = None
    message: str | None = None
    options: list[OptionItem] = Field(default_factory=list)
    updated_params: dict = Field(default_factory=dict)
    action_name: str | None = None
    action_params: dict = Field(default_factory=dict)
    submit_payload: dict | None = None
```

### 10.1 action 语义边界

| action | 用途 | session 副作用 |
|---|---|---|
| `complete` | 任务**正常**结束 | `phase=completed`；保留 `collected_params/artifacts/completed_result` 供"再来一张/换标题" |
| `exit_skill` | 用户**中断**或换需求 | `phase=idle`；清 `collected_params/artifacts/pending_param/last_options`，保留 `chat_history` |

### 10.2 updated_params value provenance（S8）

**禁止 LLM 自由填写 `updated_params`**。必须按 provenance 校验：

| param 类型 | 合法来源 | 拒绝条件 |
|---|---|---|
| `enum` / `resource` / `skill_runtime` 选项 | **只能等于 `last_options.items[].value`** | LLM 自创值（即使字面相似），拒 |
| 自由文本 | 必须来自当前 user msg 文本，或 LLM 在 `reply` 中明确生成且经用户确认 | LLM 凭空生成、对已有 value 做相似扩写（如 `bill`→`billbill`），拒 |
| 图片 | 必须来自飞书 `image_key` 或 toolbox `fileId` 引用 | bytes / base64，拒 |

校验失败时：
- 不写入 `collected_params`
- 记 warning log
- 触发 ResponseComposer 用 fallback 模板（"我没听清，请重新说一下 X"）

### 10.3 其他变化

- `ask_param` 拆成 `ask_options` 和 `ask_free_text`
- `submit` 改名 `submit_job`，强调进入 JobController（含 §12.2 幂等校验）
- LLM 不直接控制 poll，poll 是 runtime/Background Worker 职责
- LLM 不能输出未声明 action（pydantic discriminated union 强约束）

## 11. Observation Contract（两层方案，S5）

**两层设计**：envelope 强 typed + `data` 用 `schema_id + payload`。避免一上来为所有 skill action 建巨型 union，未来 skill 扩展不被阻塞。

```python
class ObservationData(BaseModel):
    schema_id: str          # 如 "image.fileId" / "job.polling" / "lookup.characters"
    payload: dict           # 具体内容；按 schema_id 由 ObservationReducer/SkillRuntime 解读

class Observation(BaseModel):
    status: Literal["success", "warning", "error"]
    summary: str            # 一句话给 LLM 读
    data: ObservationData | None = None
    artifacts: dict = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    stop_condition: str | None = None
```

### 11.1 schema_id 注册

- **内置 schema_id**（在 spec 实现层维护，固定 discriminated union）：
  - `image.fileId` — `{fileId: str, width?, height?}`
  - `image.url` — `{url: str, expires_at?: float}`
  - `job.polling` — `{job_id: str, eta_sec?: int}`
  - `lookup.characters` — `{items: list[dict]}`（同 lazy_resource 输出）
  - `text.plain` — `{text: str}`
- **未知 skill action**：必须在 manifest 里声明 `actions[].data_schema_id = "<skill_id>.<name>"`，否则 ObservationReducer 拒绝接受 observation。

### 11.2 示例

```json
{
  "status": "success",
  "summary": "generate_step1_only completed",
  "data": {
    "schema_id": "image.fileId",
    "payload": {"fileId": "6a..."}
  },
  "artifacts": {"step1_file_id": "6a...", "sent_to_user": true},
  "next_actions": ["ask_user_confirm", "regenerate_step1", "change_action"],
  "stop_condition": null
}
```

### 11.3 错误 observation 必含

- root cause hint
- safe retry instruction
- explicit stop condition

## 12. JobController（已外置）

JobController（含幂等校验 S26、本地取消语义 R2、用户触发恢复 D4、payload 约束 R4）已拆到 `docs/AGENT-HARNESS-REFORM-RUNTIME.md §1`。

Background Worker（A1 / S1）见 RUNTIME §2。

## 13. ResponseComposer

所有用户可见文本集中生成，减少 prompt 飘移。

职责：

- 渲染 OptionSet。
- 渲染完成态收尾。
- 渲染 timeout/retry/cancel。
- 渲染 out-of-scope。
- 保证回复短、清晰、适合飞书气泡。

标准完成收尾：

```text
已完成。要继续这个任务、调整哪里，还是换别的需求？
```

能力说明：

```text
我目前可以帮你做这些事：
- ...

你可以直接告诉我想做哪个。
```

## 14. Prompt 设计

Skill prompt 不再负责状态边界，prompt 应只包含：

- 当前 skill 描述。
- SKILL.md 核心规则。
- 当前 phase。
- collected_params。
- pending_param。
- last observation。
- 可调用 action catalog。
- 当前允许 action。

必须移除或弱化：

- “completed=True 时自行判断是否继续”的模糊提示。
- 让 LLM 记住上轮编号列表的要求。
- 让 LLM 自行决定是否重复 poll/submit 的自由度。

## 15. Turn Flow

1. Normalize Feishu message。
2. Load session。
3. TurnClassifier 产出 intent。
4. StateMachine 决定是否允许进入 SkillRuntime。
5. OptionResolver 优先处理结构化选项。
6. JobController 处理 active_job 相关操作。
7. 如需 LLM，SkillRuntime 注入 skill + session + observation。
8. ToolExecutor 执行白名单 action。
9. ObservationReducer 更新 session。
10. ResponseComposer 生成回复。
11. Save session。
12. Append transcript。

## 16. Transcript Eval（含行为轨迹断言 S27、脱敏 S21）

### 16.1 必须覆盖的场景

- 完成后问能力 / 问日期 / 说谢谢
- 完成后”再来一张” / “换成横版”
- 生成中取消（断言文案为 R2 锁定版）
- 生成中继续等待
- timeout 后继续等 / 修改
- 单数字角色选择 / 比例选择 / 角色名别名选择
- `bill` 不变 `billbill`
- `3` 不变 `33`
- **重启恢复（D4）**：bot restart 期间 user 发 “好了没”，恢复 poll + delayed reply
- **重复 submit 防御（S26）**：飞书事件重投递同 `message_id`，不重复创建 job
- **OptionSet 过期刷新（D5）**：菜单 TTL 过期后，再次解析时强制重新展示

### 16.2 行为轨迹断言（S27）

每条 transcript 不只断言 `reply_contains`，还必须断言：

| 维度 | 断言 |
|---|---|
| LLM 调用 | 是否调 router LLM / skill LLM（次数）|
| Action 调用 | 是否调 skill action（哪个、几次）|
| Job | 是否 `submit_job`；`active_job.source_message_id` 是否符合预期 |
| Phase | session phase 变化序列（如 `idle → collecting → awaiting_confirmation → running_job → completed`）|
| OptionSet | `last_options` 是否写入；scope / source 是否符合预期 |
| 幂等 | `last_processed_message_ids` 是否新增对应 ID |

否则测试退化为 `reply_contains`，挡不住”重复 submit”、”重复 lookup”这类问题。

### 16.3 脱敏规则（S21）

transcript fixture 入 git 前必须脱敏：

| 原始 | 替换 |
|---|---|
| `open_id` `ou_xxx` | `<USER_1>` / `<USER_2>` 顺序编号 |
| `message_id` `om_xxx` | `<MSG_1>` / `<MSG_2>` 顺序编号 |
| `fileId` / toolbox file token | `<FILE_1>` / `<FILE_2>` 顺序编号 |
| `chat_id` `oc_xxx` | `<CHAT_1>` |
| 图片二进制 | 删除，只留 `<binary omitted>` |

提供 `tests/fixtures/transcripts/redact.py` 工具脚本；CI lint 检查原始 ID 格式不出现在 fixture 里。

## 17. 与 Plan 的关系

本文件定义目标架构和约束。以下内容放在阶段计划中维护：

- 迁移策略
- 验收标准
- 风险表
- 待确认问题
- 灰度部署步骤

阶段执行计划见：

- `docs/AGENT-HARNESS-REFORM-PLAN.md`

运行时细节见：

- `docs/AGENT-HARNESS-REFORM-RUNTIME.md`

讨论与决策追踪：

- GitHub issue: https://github.com/XD-AIGC/XD-AIGC-agent/issues/2
- `docs/AGENT-HARNESS-REFORM-OPEN-ITEMS.md`
