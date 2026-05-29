"""Provenance checks for LLM-proposed skill parameter updates."""

from __future__ import annotations

import json
import re
from typing import Any

from src.conversation.options import OptionSet
from src.skill.schema import Skill, SkillParam

_ARTIFACT_PARAM_NAMES = {
    "fileId",
    "file_id",
    "jobId",
    "job_id",
    "v2JobId",
    "cachedStep1FileId",
}


def filter_updated_params(
    updated_params: dict[str, Any],
    *,
    session: Any,
    skill: Skill | None,
    user_text: str,
    trusted_text: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return accepted LLM updates plus rejected keys with machine-readable reasons."""
    accepted: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    if not isinstance(updated_params, dict):
        return accepted, {"_root": "updated_params_not_object"}

    params = {param.name: param for param in (skill.params if skill else [])}
    current = getattr(session, "collected_params", {}) or {}
    for key, new_value in updated_params.items():
        old_exists = key in current
        old_value = current.get(key)
        param = params.get(key)

        if param is None:
            if _is_valid_artifact_update(key, new_value, trusted_text):
                accepted[key] = new_value
                continue
            rejected[key] = "unknown_param"
            continue
        if old_exists and _same_value(old_value, new_value):
            accepted[key] = new_value
            continue
        if _is_valid_option_or_enum_value(key, new_value, param, session):
            accepted[key] = new_value
            continue
        if param is not None and param.type == "json" and _value_appears_in_trusted_sources(new_value, trusted_text, session):
            accepted[key] = new_value
            continue
        if _value_appears_in_text(new_value, user_text):
            accepted[key] = new_value
            continue
        if param is not None and param.type == "enum":
            rejected[key] = "enum_value_without_provenance"
            continue
        if old_exists and _is_structured_value(old_value):
            rejected[key] = "existing_structured_value_changed_without_provenance"
            continue

        rejected[key] = "value_without_provenance"
    return accepted, rejected


def _is_valid_artifact_update(key: str, value: Any, trusted_text: str) -> bool:
    return key in _ARTIFACT_PARAM_NAMES and _value_appears_in_text(value, trusted_text)


def _is_valid_option_or_enum_value(key: str, value: Any, param: SkillParam | None, session: Any) -> bool:
    option_set = _last_option_set(session)
    if option_set is not None and option_set.param_name == key:
        if any(_same_value(item.value, value) for item in option_set.items):
            return True

    if param is None or param.type != "enum" or not param.values:
        return False
    return all(item in param.values for item in _as_scalar_items(value))


def _last_option_set(session: Any) -> OptionSet | None:
    raw = getattr(session, "last_options", None)
    if raw is None:
        return None
    return raw if isinstance(raw, OptionSet) else OptionSet.model_validate(raw)


def _value_appears_in_text(value: Any, text: str) -> bool:
    items = _as_scalar_items(value)
    if not items:
        return False
    compact_text = _compact(text)
    return all(_compact(item) and _compact(item) in compact_text for item in items)


def _value_appears_in_trusted_sources(value: Any, trusted_text: str, session: Any) -> bool:
    source_text = "\n".join(_trusted_source_texts(trusted_text, session))
    if not source_text:
        return False
    return _value_appears_in_text(value, source_text) or _structured_value_appears_in_text(value, source_text)


def _trusted_source_texts(trusted_text: str, session: Any) -> list[str]:
    texts = [trusted_text] if trusted_text else []
    loaded = getattr(session, "loaded_resources", {}) or {}
    if isinstance(loaded, dict):
        texts.extend(str(value) for value in loaded.values() if value)
    return texts


def _structured_value_appears_in_text(value: Any, text: str) -> bool:
    tokens = _structured_identity_tokens(value)
    if not tokens:
        return False
    compact_text = _compact(text)
    return all(_compact(token) and _compact(token) in compact_text for token in tokens)


def _structured_identity_tokens(value: Any) -> list[str]:
    if isinstance(value, list):
        tokens: list[str] = []
        for item in value:
            item_tokens = _structured_identity_tokens(item)
            if not item_tokens:
                return []
            tokens.extend(item_tokens)
        return tokens
    if not isinstance(value, dict):
        return []
    token = value.get("key") or value.get("id") or value.get("name") or value.get("refImage")
    return [str(token)] if token else []


def _as_scalar_items(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, (dict, list)):
                return []
            items.append(str(item))
        return items
    if isinstance(value, dict):
        return []
    return [str(value)]


def _same_value(left: Any, right: Any) -> bool:
    return _stable_json(left) == _stable_json(right)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_structured_value(value: Any) -> bool:
    return isinstance(value, (dict, list))


def _compact(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？~～（）()_-]", "", str(text)).lower()
