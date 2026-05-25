from typing import Literal
from pydantic import BaseModel


class SkillParam(BaseModel):
    name: str
    type: Literal["enum", "text", "number", "image"]
    values: list[str] = []
    required: bool = True
    prompt_to_user: str


class SkillOutput(BaseModel):
    type: Literal["image_url", "text", "image_binary"]
    display_as: Literal["feishu_card", "feishu_image", "feishu_text"]


class SkillAPI(BaseModel):
    endpoint_path: str  # 相对路径（不含 host:port），实际 URL = TOOLBOX_BASE_URL + path
    method: Literal["POST", "GET"]
    content_type: Literal["multipart/form-data", "application/json"]


class Skill(BaseModel):
    name: str
    description: str
    api: SkillAPI
    params: list[SkillParam]
    output: SkillOutput
