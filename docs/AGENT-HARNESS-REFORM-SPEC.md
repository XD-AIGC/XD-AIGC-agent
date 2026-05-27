# Agent Harness 改造 Spec

> 目标：把当前“Router + Skill prompt + 若干规则补丁”改造成受限 Hermes 风格的对话运行时。
> 约束：只服务公司内部；只调用白名单 toolbox skill；不扩大飞书权限；不引入 Hermes 的本机文件/命令大权限。
> 文档规则：本 spec 经 Johnny 明确允许放宽到 500 行以内；超过 500 行再拆分。

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

建议新增 `ConversationSession`，旧 `UserSession` 只作为迁移输入。

```python
class ConversationPhase(str, Enum):
    idle = "idle"
    selecting_skill = "selecting_skill"
    collecting = "collecting"
    awaiting_confirmation = "awaiting_confirmation"
    running_job = "running_job"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"

class ConversationSession(BaseModel):
    schema_version: int = 2
    mode: Literal["router", "skill"] = "router"
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
    turn_count: int = 0
    updated_at: float
```

### 7.1 字段解释

- `phase`：当前会话状态，替代散落的 `completed/state/pending_param`。
- `last_options`：最后一次展示给用户的结构化菜单。
- `active_job`：正在运行或可继续等待的后端任务。
- `artifacts`：step1FileId、finalImageFileId、uploaded image key 等。
- `completed_result`：最后一次完成结果，用于“再来一张/换标题”。
- `chat_history`：只保存对 LLM 有用的短历史，不承担状态职责。

### 7.2 旧数据迁移

读取 Redis 时：

- 没有 `schema_version` -> 当作 v1 `UserSession`。
- `completed=True` -> `phase=completed`。
- `pending_param` 非空 -> `phase=collecting`。
- `skill_name` 非空 -> `mode=skill`。
- `collected_params` 原样迁移。

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

## 9. OptionSet

所有用户可选菜单都用统一结构。

```python
class OptionItem(BaseModel):
    index: int
    label: str
    value: Any
    param_name: str
    aliases: list[str] = Field(default_factory=list)

class OptionSet(BaseModel):
    id: str
    param_name: str
    source: Literal["enum", "resource", "skill_runtime"]
    items: list[OptionItem]
    page: int = 1
    page_size: int = 8
    allow_multi: bool = False
```

### 9.1 解析规则

- 用户回复数字 -> 匹配当前 page 的 `index`。
- 用户回复多个数字 -> 仅 `allow_multi=True` 时允许。
- 用户回复名称 -> 匹配 `label` 或 `aliases`。
- 用户回复 `更多/more` -> page + 1。
- 用户回复 `返回/back` -> page - 1。
- 无匹配 -> 生成“没找到，请选当前列表编号或名称”的回复，不进 LLM。

### 9.2 菜单来源

- manifest enum：比例、分辨率、角色类型。
- lazy resource：角色、动物、场景。
- skill runtime：LLM 根据 SKILL.md 生成的临时选项，但必须落成 OptionSet 后再展示。

## 10. SkillRuntimeAction

当前 `BotAction` 过宽，建议收窄。

```python
class SkillRuntimeAction(BaseModel):
    action: Literal[
        "ask_options",
        "ask_free_text",
        "call_skill_action",
        "submit_job",
        "reply",
        "complete",
        "exit_skill",
    ]
    param_name: str | None = None
    message: str | None = None
    options: list[OptionItem] = Field(default_factory=list)
    updated_params: dict = Field(default_factory=dict)
    action_name: str | None = None
    action_params: dict = Field(default_factory=dict)
    submit_payload: dict | None = None
```

变化：

- `ask_param` 拆成 `ask_options` 和 `ask_free_text`。
- `submit` 改名 `submit_job`，强调先进入 JobController。
- LLM 不直接控制 poll，poll 是 runtime 职责。
- LLM 不能输出未声明 action。

## 11. Observation Contract

统一 observation：

```python
class Observation(BaseModel):
    status: Literal["success", "warning", "error"]
    summary: str
    data: Any = None
    artifacts: dict = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    stop_condition: str | None = None
```

示例：

```json
{
  "status": "success",
  "summary": "generate_step1_only completed",
  "data": {"fileId": "6a..."},
  "artifacts": {"step1_file_id": "6a...", "sent_to_user": true},
  "next_actions": ["ask_user_confirm", "regenerate_step1", "change_action"],
  "stop_condition": null
}
```

错误 observation 必须包含：

- root cause hint
- safe retry instruction
- explicit stop condition

## 12. JobController

`active_job` 用于所有异步任务。

```python
class ActiveJob(BaseModel):
    job_id: str
    skill_name: str
    action_name: str
    payload: dict
    status: Literal["submitted", "running", "completed", "failed", "cancelled", "timeout"]
    started_at: float
    last_poll_at: float | None = None
    poll_count: int = 0
    last_observation: Observation | None = None
```

### 12.1 状态流

```
submit_job
  -> active_job.status=submitted
  -> poll loop
  -> completed | failed | timeout | cancelled
```

### 12.2 用户交互

- 用户说“取消”：停止当前等待，标记 cancelled。
- 用户说“继续等”：继续 poll existing job，不重新 submit。
- 用户说“重试”：复用 payload 重新 submit。
- 用户说“修改”：退出 running/completed，回到 collecting。

### 12.3 timeout 策略

timeout 不直接结束对话，应回复：

```text
生成还没完成。你可以：
1. 继续等待
2. 重试
3. 修改信息
4. 取消
```

此回复也必须写入 OptionSet。

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

## 16. Transcript Eval

首批必须覆盖：

- 完成后问能力。
- 完成后问日期。
- 完成后说谢谢。
- 完成后“再来一张”。
- 完成后“换成横版”。
- 生成中取消。
- 生成中继续等待。
- timeout 后继续等。
- timeout 后修改。
- 单数字角色选择。
- 单数字比例选择。
- 角色名别名选择。
- `bill` 不变 `billbill`。
- `3` 不变 `33`。

## 17. 与 Plan 的关系

本文件定义目标架构和约束。以下内容放在阶段计划中维护：

- 迁移策略
- 验收标准
- 风险表
- 待确认问题
- 灰度部署步骤

阶段执行计划见：

- `docs/AGENT-HARNESS-REFORM-PLAN.md`
