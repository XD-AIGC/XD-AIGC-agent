# Agent Harness 改造 Spec

> 目标：把当前“Router + Skill prompt + 若干规则补丁”改造成受限 Hermes 风格的对话运行时。
> 约束：只服务公司内部；只调用白名单 toolbox skill；不扩大飞书权限；不引入 Hermes 的本机文件/命令大权限。

## 背景

当前线上问题不是单个 skill 的问题，而是 agent 编排层不成熟：

- 状态只靠 `completed/pending_param/collected_params` 等少数字段推断。
- 编号选择曾靠解析上一条 assistant 文本，容易出现 `3 -> 33`、比例选项误当角色。
- 完成后闲聊、问能力、换需求、继续生成缺少统一边界。
- 生成中插话、取消、继续等待、重试没有一等模型。
- tool observation 不统一，LLM 不稳定时容易重复调用、跳步或误提交。

Hermes 的优势不是某个 prompt，而是完整 agent loop：历史、工具调用、观察、重试、压缩、持久化、恢复、技能注入。我们要借鉴这个结构，但保留项目安全边界。

## 设计原则

1. **受限 Hermes**：吸收 conversation loop / skill context / observation / recovery，不接 shell、file、browser、MCP 泛化权限。
2. **状态先于 prompt**：是否继续 skill、是否提交、是否取消，先由状态机判定；LLM 只在允许状态内规划。
3. **结构化选项**：任何编号菜单保存为 `last_options`，用户回复数字时查结构，不解析 assistant 文本。
4. **标准观察**：所有 skill action 返回 `{status, summary, data, artifacts, next_actions}`。
5. **完成态默认不继续**：completed 后只有明确“再来/修改/调整/重试”才进入 skill。
6. **测试来自真实对话**：把 Feishu 事故固化为 transcript eval。

## 非目标

- 不改飞书权限范围。
- 不把 Hermes 作为直接依赖。
- 不要求改 skill 仓库才能启动改造。
- 不实现用户 OAuth / user_access_token。
- 不开放本机文件、shell、docs、drive、contact 权限。

## 目标架构

```
Feishu Message
  -> MessageNormalizer
  -> ConversationManager
       -> TurnClassifier
       -> StateMachine
       -> SkillRuntime
            -> SkillContextBuilder
            -> ToolPlanner(LLM typed action)
            -> ToolExecutor
            -> ObservationReducer
       -> ResponseComposer
  -> Feishu reply-only
```

| 模块 | 职责 |
|---|---|
| `conversation/session.py` | phase、active_job、last_options、artifacts |
| `conversation/classifier.py` | turn intent 分类 |
| `conversation/state_machine.py` | phase + intent → allowed action |
| `conversation/options.py` | 菜单生成、分页、数字/名称解析 |
| `conversation/runtime.py` | 单轮 agent loop，替代 `_agentic_loop` 大函数 |
| `skill/runtime.py` | skill 上下文、typed action、observation 回喂 |
| `skill/job_controller.py` | submit/poll/continue_wait/retry/cancel/timeout |
| `evals/transcripts/` | 真实 Feishu 对话回放 |

## Session Model

核心字段：

- `phase`: `idle/selecting_skill/collecting/awaiting_confirmation/running_job/completed/cancelled`
- `skill_name`
- `initial_intent`
- `collected_params`
- `pending_param`
- `last_options`
- `active_job`
- `artifacts`
- `completed_result`
- `chat_history`

旧 `UserSession` 保留兼容读，Redis 新增 `schema_version=2`。

## Turn Intent

统一分类：

- `start_skill`
- `answer_option`
- `provide_param`
- `modify_param`
- `confirm`
- `retry`
- `continue_wait`
- `cancel`
- `ask_capability`
- `unrelated`
- `chitchat`

状态边界：

- `running_job`：只接受取消、继续等待、状态说明、无关问题，不进 skill LLM。
- `completed`：只接受重试、修改参数、换任务、问能力、闲聊、无关问题。
- `collecting`：允许选项、参数、修改、取消，必要时进 skill LLM。
- `idle`：router 选 skill 或能力说明。

## OptionSet

所有编号菜单使用统一结构：

- `id`
- `param_name`
- `items[index,label,value,aliases]`
- `page`
- `page_size`

要求：

- assistant 展示的编号来自 `OptionSet`。
- 用户回复 `3` 时只查 `items[index=3]`。
- `more/back` 改变 page，不交给 LLM。
- 角色类型、角色清单、构图、比例都走同一个 resolver。

## Skill Runtime Action

替代当前宽泛 `BotAction`：

- `ask_options`
- `ask_free_text`
- `call_skill_action`
- `submit_job`
- `reply`
- `complete`
- `exit_skill`

关键变化：

- `ask_param` 拆成选项和自由文本。
- LLM 不负责编号文本格式；编号由 `ResponseComposer` 统一生成。
- `submit_job` 只创建 `active_job`，poll 由 `JobController` 接管。

## Observation Contract

所有 toolbox HTTP、poll、upload Feishu、lazy resource 都转换为：

```json
{
  "status": "success|warning|error",
  "summary": "一句话结果",
  "data": {},
  "artifacts": {"image_file_id": "...", "job_id": "..."},
  "next_actions": ["ask_user_confirm", "poll_job", "retry", "change_params"],
  "stop_condition": "completed|failed|cancelled|timeout"
}
```

## Turn Flow

1. Normalize Feishu message。
2. Load session。
3. TurnClassifier 产出 intent。
4. StateMachine 决定是否允许进入 SkillRuntime。
5. OptionResolver 先处理结构化选项。
6. JobController 处理 job 操作。
7. 如需 LLM，SkillRuntime 注入 skill + session + observation。
8. ToolExecutor 执行白名单 action。
9. ObservationReducer 更新 session。
10. ResponseComposer 生成回复。
11. Save session + append transcript。

## 执行计划

分阶段实现、验收标准、风险和待确认问题见：

- `docs/AGENT-HARNESS-REFORM-PLAN.md`
