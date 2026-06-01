"""Skill schema 支持两种 backend：HTTP 单次 / Poll 异步。

为了向后兼容 frame-bg-remover.yaml（没有 type 字段），HttpBackend.type 有 default 'http'。
"""
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


class SkillParam(BaseModel):
    name: str
    type: Literal["enum", "text", "number", "image", "json"]
    values: list[str] = []
    required: bool = True
    prompt_to_user: str


class SkillOutput(BaseModel):
    type: Literal["image_url", "image_binary", "text"]
    display_as: Literal["feishu_card", "feishu_image", "feishu_text"]


class SkillActionMetadata(BaseModel):
    """Optional manifest metadata for callable skill actions."""

    name: str
    data_schema_id: Optional[str] = None


class HttpBackend(BaseModel):
    """单次 HTTP 调用，同步返回结果。frame-bg-remover 用这个。"""
    type: Literal["http"] = "http"
    # base_url：覆盖 TOOLBOX_BASE_URL。每个 skill 的后端可能在不同端口
    # （如 xd-poster-studio-v2 在 8090）。不填则回退 TOOLBOX_BASE_URL。
    base_url: Optional[str] = None
    endpoint_path: str
    method: Literal["POST", "GET"] = "POST"
    content_type: Literal["multipart/form-data", "application/json"] = "multipart/form-data"


class PollBackend(BaseModel):
    """异步任务：POST 拿 job_id → 轮询 → 完成后取结果。xd-poster-gen 用这个。"""
    type: Literal["poll"]
    base_url: Optional[str] = None  # 见 HttpBackend.base_url 说明
    submit_path: str
    submit_method: Literal["POST", "GET"] = "POST"
    submit_content_type: Literal["application/json", "multipart/form-data"] = "application/json"
    poll_path_template: str
    job_id_field: str = "v2JobId"
    status_field: str = "status"
    done_value: str = "completed"
    failed_value: str = "failed"
    error_field: str = "error"
    result_path: str = "images[0].url"
    poll_interval_sec: int = 3
    poll_timeout_sec: int = 300


SkillBackend = Union[HttpBackend, PollBackend]


class HttpResource(BaseModel):
    """HTTP 类型的 lazy_resource：动态从 URL 拉取，带 TTL 缓存。

    用于 toolbox 子工具暴露的列表端点（如 /api/characters?refresh=1）。
    URL 必须是绝对地址，且其 host+port 会被自动加入 agent HTTP 白名单。
    """
    type: Literal["http"]
    url: str
    method: Literal["GET", "POST"] = "GET"
    cache_ttl_sec: int = 300  # 内存缓存秒数，0 = 不缓存


# 两种来源：字符串 = 文件路径（registry 转成绝对路径）；dict = HTTP 配置
LazyResource = Union[str, HttpResource]


class Skill(BaseModel):
    name: str
    description: str
    api: SkillBackend = Field(discriminator="type")
    params: list[SkillParam]
    output: SkillOutput
    # Optional skill-level image fetch path for actions that return toolbox fileId refs.
    image_path_template: Optional[str] = None
    # Always-on Core：Skill Mode 期间每轮都注入 LLM 的简短规则
    system_prompt_core: Optional[str] = None
    # Lazy-load 资源：key 是 action 名（如 'lookup_characters'）；
    # value 可以是相对文件路径（file 类型）或 HttpResource dict（http 类型）
    lazy_resources: dict[str, LazyResource] = {}
    # Optional metadata for HTTP actions discovered from SKILL.md / manifest.
    actions: list[SkillActionMetadata] = []
