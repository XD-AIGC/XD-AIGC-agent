from typing import Literal, Optional
from pydantic import BaseModel, Field

from src.conversation.options import OptionSet


# 9 个 action：
#   Router only:   select_skill, reply (greeting), out_of_scope
#   Skill only:    lookup_characters, lookup_options, call_skill_action, submit, exit_skill
#   通用:          ask_param, reply
Action = Literal[
    "select_skill",
    "lookup_characters",
    "lookup_options",
    "call_skill_action",
    "ask_param",
    "submit",
    "exit_skill",
    "reply",
    "out_of_scope",
]


class BotAction(BaseModel):
    action: Action
    skill_name: Optional[str] = None
    param_name: Optional[str] = None
    param_value: Optional[str] = None
    message: Optional[str] = None
    submit_payload: Optional[dict] = None
    action_name: Optional[str] = None
    action_params: dict = Field(default_factory=dict)
    updated_params: dict = Field(default_factory=dict)


class UserSession(BaseModel):
    """Deprecated v1 runtime view. ConversationSession v2 is the new data model."""

    mode: Literal["router", "skill"] = "router"
    skill_name: Optional[str] = None
    collected_params: dict = Field(default_factory=dict)
    pending_param: Optional[str] = None
    loaded_resources: dict[str, str] = Field(default_factory=dict)
    # 进入 skill mode 时的原始用户请求，每轮 skill_decide 都注入避免 LLM 失忆
    initial_intent: Optional[str] = None
    # 上一次 submit 是否已成功；True 时新消息走 retry 快路径或 adjust 流程
    completed: bool = False
    # 最近 N 条 user/assistant 对话给 LLM 看，避免它忘记自己上轮 reply 了什么
    # 格式：[{"role": "user"|"assistant", "content": str}]
    chat_history: list[dict] = Field(default_factory=list)
    # PR-0c transitional field: structured options shown to the user.
    last_options: Optional[OptionSet] = None
    # 向后兼容字段（旧 Redis 数据反序列化用，新代码逻辑通过 mode 判断）
    state: Literal["idle", "collecting"] = "idle"
