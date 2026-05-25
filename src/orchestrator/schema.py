from typing import Literal, Optional
from pydantic import BaseModel


class BotAction(BaseModel):
    action: Literal["select_skill", "ask_param", "call_api", "reply", "out_of_scope"]
    skill_name: Optional[str] = None
    param_name: Optional[str] = None
    param_value: Optional[str] = None
    message: Optional[str] = None


class UserSession(BaseModel):
    state: Literal["idle", "collecting"] = "idle"
    skill_name: Optional[str] = None
    collected_params: dict = {}
    pending_param: Optional[str] = None
