"""Safe per-skill HTTP action catalog and executor.

This is the first slice of a restricted Hermes-like skill runtime: SKILL.md can
describe multi-step HTTP workflows, but the model can only call endpoints that
the current skill document or manifest already exposes.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlparse

from pydantic import BaseModel

from src.config import TOOLBOX_BASE_URL
from src.http_client.allowlist import allowed_client
from src.skill.observation import ObservationReducer, ObservationStatus
from src.skill.schema import HttpBackend, HttpResource, PollBackend, Skill


_HTTP_LINE_RE = re.compile(r"^\s*(GET|POST)\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
_MAX_TEXT_CHARS = 6000
_COMPACT_LIST_ITEMS = 6
_COMPACT_TEXT_CHARS = 360
_PREFERRED_RECORD_KEYS = (
    "id",
    "key",
    "name",
    "displayName",
    "category",
    "type",
    "refImage",
    "url",
    "fileId",
    "file_id",
    "artdamAssetId",
    "artdamPublicId",
    "public_id",
    "fusionDesc",
    "prompt",
)
log = logging.getLogger(__name__)


class SkillHttpAction(BaseModel):
    """A single HTTP action the model may call for the active skill."""

    name: str
    method: Literal["GET", "POST"]
    path_template: str
    source: Literal["skill_md", "manifest_api", "lazy_resource"]
    data_schema_id: str | None = None


@dataclass
class SkillActionObservation:
    status: ObservationStatus
    summary: str
    data: Any = None
    data_schema_id: str | None = None
    source_name: str | None = None
    artifact: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    stop_condition: str | None = None
    content_bytes: bytes | None = None

    def for_prompt(self) -> str:
        observation = ObservationReducer().reduce(
            status=self.status,
            summary=self.summary,
            data=_truncate_data(self.data),
            artifacts=self.artifact,
            data_schema_id=self.data_schema_id,
            source_name=self.source_name,
            next_actions=self.next_actions,
            stop_condition=self.stop_condition,
        )
        return observation.model_dump_json(exclude_none=False)


class SkillActionError(Exception):
    """Raised when a requested skill action is unsafe or cannot execute."""


def build_action_catalog(skill: Skill) -> dict[str, SkillHttpAction]:
    """Build a deterministic allowlist of HTTP actions for a skill."""
    actions: dict[str, SkillHttpAction] = {}

    for method, path in _extract_http_lines(skill.system_prompt_core or ""):
        _add_action(actions, method, path, "skill_md")

    for name, resource in skill.lazy_resources.items():
        if isinstance(resource, HttpResource):
            parsed = urlparse(resource.url)
            path = parsed.path
            if parsed.query:
                path = f"{path}?{parsed.query}"
            _add_action(actions, resource.method, path, "lazy_resource", preferred=name)

    api = skill.api
    if isinstance(api, HttpBackend):
        _add_action(actions, api.method, api.endpoint_path, "manifest_api", preferred="manifest_submit")
    elif isinstance(api, PollBackend):
        _add_action(actions, api.submit_method, api.submit_path, "manifest_api", preferred="manifest_submit")
        _add_action(actions, "GET", api.poll_path_template, "manifest_api", preferred="manifest_poll")

    _apply_action_metadata(actions, skill)
    return actions


def format_action_catalog(skill: Skill) -> str:
    catalog = build_action_catalog(skill)
    if not catalog:
        return "（当前 skill 没有声明可直接调用的 HTTP action）"
    lines = [
        "【可调用的 skill actions（只能调用这里列出的 action_name）】",
        "调用格式：action=call_skill_action, action_name=<name>, action_params=[{\"key\":\"json\",\"value_json\":\"{...}\"}]",
        "GET 推荐 action_params=[{\"key\":\"path_params\",\"value_json\":\"{...}\"},{\"key\":\"query\",\"value_json\":\"{...}\"}]；POST 推荐 action_params=[{\"key\":\"json\",\"value_json\":\"{...}\"}]。",
    ]
    for action in catalog.values():
        placeholders = ", ".join(_PLACEHOLDER_RE.findall(action.path_template)) or "无"
        lines.append(
            f"- {action.name}: {action.method} {action.path_template} "
            f"(source={action.source}, path_params={placeholders})"
        )
    return "\n".join(lines)


async def execute_skill_action(
    skill: Skill,
    action_name: str | None,
    action_params: dict[str, Any] | None,
) -> SkillActionObservation:
    catalog = build_action_catalog(skill)
    if not action_name or action_name not in catalog:
        allowed = ", ".join(catalog) or "无"
        raise SkillActionError(f"未知或未允许的 skill action: {action_name!r}; allowed={allowed}")

    action = catalog[action_name]
    params = action_params or {}
    path_params = params.get("path_params", params)
    if not isinstance(path_params, dict):
        raise SkillActionError("path_params 必须是对象")
    path = _render_path(action.path_template, path_params)
    url = _full_url(skill, path)

    request_kwargs: dict[str, Any] = {}
    if action.method == "GET":
        query = params.get("query") if isinstance(params.get("query"), dict) else {}
        if query:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode(query, doseq=True)}"
    else:
        request_kwargs["json"] = params.get("json", params)

    try:
        async with allowed_client() as client:
            resp = await client.request(action.method, url, timeout=300.0, **request_kwargs)
            resp.raise_for_status()
    except Exception as exc:
        return SkillActionObservation(
            status="error",
            summary=f"{action.name} 调用失败: {type(exc).__name__}: {exc}",
        )

    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("image/"):
        return SkillActionObservation(
            status="success",
            summary=f"{action.name} 返回图片 ({content_type}, {len(resp.content)} bytes)",
            artifact={"kind": "image_binary", "content_type": content_type, "byte_count": len(resp.content)},
            data_schema_id="image.binary",
            content_bytes=resp.content,
        )

    data = _response_data(resp, content_type)
    return SkillActionObservation(
        status="success",
        summary=f"{action.name} 调用成功",
        data=data,
        data_schema_id=action.data_schema_id,
        source_name=action.name,
    )


def _extract_http_lines(content: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for method, raw_path in _HTTP_LINE_RE.findall(content):
        path = raw_path.strip()
        parsed = urlparse(path)
        # Absolute URLs in SKILL.md are documentation/fallback hints, not safe
        # tool actions. Only relative endpoints on the active skill backend are callable.
        if parsed.scheme or parsed.netloc:
            continue
        if not path.startswith("/"):
            continue
        result.append((method.upper(), path))
    return result


def _add_action(
    actions: dict[str, SkillHttpAction],
    method: str,
    path: str,
    source: Literal["skill_md", "manifest_api", "lazy_resource"],
    preferred: str | None = None,
) -> None:
    method = method.upper()
    if method not in {"GET", "POST"} or not path.startswith("/"):
        return
    if any(existing.method == method and existing.path_template == path for existing in actions.values()):
        return
    name = _unique_name(actions, preferred or _action_name(method, path))
    actions[name] = SkillHttpAction(
        name=name,
        method=method,  # type: ignore[arg-type]
        path_template=path,
        source=source,
    )


def _apply_action_metadata(actions: dict[str, SkillHttpAction], skill: Skill) -> None:
    for metadata in skill.actions:
        action = actions.get(metadata.name)
        if action is None:
            log.warning(
                "[SKILL] manifest action %r not in SKILL.md HTTP blocks for skill=%s",
                metadata.name,
                skill.name,
            )
            continue
        actions[metadata.name] = action.model_copy(update={"data_schema_id": metadata.data_schema_id})


def _unique_name(actions: dict[str, SkillHttpAction], base: str) -> str:
    name = base
    idx = 2
    while name in actions:
        name = f"{base}_{idx}"
        idx += 1
    return name


def _action_name(method: str, path: str) -> str:
    parsed = urlparse(path)
    parts = [p for p in parsed.path.split("/") if p and not p.startswith("{")]
    tail = "_".join(parts[-2:] if len(parts) > 1 and parts[-1].startswith("{") else parts[-1:])
    tail = re.sub(r"[^a-zA-Z0-9]+", "_", tail).strip("_").lower() or "root"
    prefix = "list" if method.upper() == "GET" and "characters" in tail else method.lower()
    if method.upper() == "POST" and tail.startswith("generate"):
        prefix = ""
    return "_".join(p for p in [prefix, tail] if p)


def _render_path(path_template: str, params: dict[str, Any]) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        val = _lookup_path_param(params, key)
        if val is None:
            raise SkillActionError(f"缺少 path 参数: {key}")
        return quote(str(val), safe="")

    return _PLACEHOLDER_RE.sub(replace, path_template)


def _lookup_path_param(params: dict[str, Any], key: str) -> Any:
    if key in params:
        return params[key]
    aliases = {
        "job_id": ["jobId", "v2JobId"],
        "jobId": ["job_id", "v2JobId"],
        "v2JobId": ["job_id", "jobId"],
        "fileId": ["file_id"],
        "file_id": ["fileId"],
    }
    for alias in aliases.get(key, []):
        if alias in params:
            return params[alias]
    return None


def _full_url(skill: Skill, path: str) -> str:
    base = getattr(skill.api, "base_url", None) or TOOLBOX_BASE_URL
    return base.rstrip("/") + path


def _response_data(resp, content_type: str) -> Any:
    if "json" in content_type:
        return resp.json()
    text = resp.text
    try:
        return resp.json()
    except Exception:
        return text[:_MAX_TEXT_CHARS] + ("...[truncated]" if len(text) > _MAX_TEXT_CHARS else "")


def _truncate_data(data: Any) -> Any:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= _MAX_TEXT_CHARS:
        return data
    return _compact_for_prompt(data)


def _compact_for_prompt(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return _compact_scalar(value)
    if isinstance(value, dict):
        return _compact_dict(value, depth=depth)
    if isinstance(value, list):
        items = [_compact_for_prompt(item, depth=depth + 1) for item in value[:_COMPACT_LIST_ITEMS]]
        if len(value) > _COMPACT_LIST_ITEMS:
            items.append({"_truncated": len(value) - _COMPACT_LIST_ITEMS})
        return items
    return _compact_scalar(value)


def _compact_dict(value: dict[str, Any], *, depth: int) -> dict[str, Any]:
    keys = _ordered_compact_keys(value)
    compacted = {key: _compact_for_prompt(value[key], depth=depth + 1) for key in keys}
    list_counts = {
        key: len(item)
        for key, item in value.items()
        if isinstance(item, list) and len(item) > _COMPACT_LIST_ITEMS
    }
    if list_counts and depth == 0:
        compacted["_list_counts"] = list_counts
    return compacted


def _ordered_compact_keys(value: dict[str, Any]) -> list[str]:
    preferred = [key for key in _PREFERRED_RECORD_KEYS if key in value]
    if preferred:
        return preferred
    return list(value.keys())


def _compact_scalar(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _COMPACT_TEXT_CHARS:
        return value[:_COMPACT_TEXT_CHARS] + "...[truncated]"
    return value
