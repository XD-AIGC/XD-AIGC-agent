"""Deterministic resolver for structured user option replies."""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from src.conversation.options import OptionItem, OptionSet


_SINGLE_NUMBER_RE = re.compile(r"^\s*(?:选|选择|第)?\s*(\d{1,2})\s*(?:号|个)?\s*[。.!！?？]?\s*$")
_MULTI_NUMBER_RE = re.compile(r"^\s*(?:选|选择)?\s*(\d{1,2})(?:\s*[,，、 ]\s*\d{1,2})+\s*$")
_NUMBER_RE = re.compile(r"\d{1,2}")
_MORE = {"更多", "more", "next", "下一页"}
_BACK = {"返回", "back", "上一页"}


class OptionResolveResult(BaseModel):
    status: Literal["matched", "page", "expired", "out_of_range", "no_match"]
    item: OptionItem | None = None
    items: list[OptionItem] = Field(default_factory=list)
    values: list[Any] = Field(default_factory=list)
    option_set: OptionSet
    message: str = ""


class OptionResolver:
    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        skill_version: str | None = None,
    ) -> None:
        self._now = now or time.time
        self._skill_version = skill_version

    def resolve(self, text: str, option_set: OptionSet | dict[str, Any]) -> OptionResolveResult:
        option_set = _coerce_option_set(option_set)
        text = text.strip()
        if option_set.is_stale(now=self._now(), skill_version=self._skill_version):
            return OptionResolveResult(
                status="expired",
                option_set=option_set,
                message="菜单可能已更新，请重新确认你的选择。",
            )

        lowered = text.lower()
        if lowered in _MORE:
            return self._move_page(option_set, 1)
        if lowered in _BACK:
            return self._move_page(option_set, -1)
        if _MULTI_NUMBER_RE.match(text):
            return self._resolve_multi(text, option_set)

        single = _SINGLE_NUMBER_RE.match(text)
        if single:
            return self._resolve_index(int(single.group(1)), option_set)

        return self._resolve_label(text, option_set)

    def _move_page(self, option_set: OptionSet, delta: int) -> OptionResolveResult:
        target = option_set.page + delta
        max_page = max(1, (len(option_set.items) + option_set.page_size - 1) // option_set.page_size)
        if target < 1 or target > max_page:
            return OptionResolveResult(
                status="out_of_range",
                option_set=option_set,
                message="没有更多选项了，请选择当前列表中的编号或名称。",
            )
        updated = option_set.model_copy(update={"page": target})
        return OptionResolveResult(status="page", option_set=updated, message=render_option_set(updated))

    def _resolve_multi(self, text: str, option_set: OptionSet) -> OptionResolveResult:
        if not option_set.allow_multi:
            return OptionResolveResult(
                status="no_match",
                option_set=option_set,
                message="请选择一个选项。",
            )
        indexes = [int(value) for value in _NUMBER_RE.findall(text)]
        by_index = {item.index: item for item in option_set.page_items()}
        selected = [by_index[index] for index in indexes if index in by_index]
        if len(selected) != len(indexes):
            return self._out_of_range(option_set)
        return OptionResolveResult(
            status="matched",
            item=selected[0] if selected else None,
            items=selected,
            values=[item.value for item in selected],
            option_set=option_set,
        )

    def _resolve_index(self, index: int, option_set: OptionSet) -> OptionResolveResult:
        by_index = {item.index: item for item in option_set.page_items()}
        item = by_index.get(index)
        if item is None:
            return self._out_of_range(option_set, index)
        return OptionResolveResult(
            status="matched",
            item=item,
            items=[item],
            values=[item.value],
            option_set=option_set,
        )

    def _resolve_label(self, text: str, option_set: OptionSet) -> OptionResolveResult:
        wanted = _normalize(text)
        for item in option_set.page_items():
            candidates = [item.label, *item.aliases]
            if any(_normalize(candidate) == wanted for candidate in candidates):
                return OptionResolveResult(
                    status="matched",
                    item=item,
                    items=[item],
                    values=[item.value],
                    option_set=option_set,
                )
        return OptionResolveResult(
            status="no_match",
            option_set=option_set,
            message="没找到这个选项，请选择当前列表编号或名称。",
        )

    def _out_of_range(self, option_set: OptionSet, index: int | None = None) -> OptionResolveResult:
        visible = option_set.page_items()
        indexes = [item.index for item in visible]
        if indexes:
            scope = f"{min(indexes)}-{max(indexes)}"
        else:
            scope = "当前页"
        prefix = f"编号 {index} 超出范围，" if index is not None else ""
        return OptionResolveResult(
            status="out_of_range",
            option_set=option_set,
            message=f"{prefix}请回复 {scope} 的编号，或回复“更多”查看后续选项。",
        )


def render_option_set(option_set: OptionSet) -> str:
    lines = [f"{item.index}. {item.label}" for item in option_set.page_items()]
    if option_set.has_next_page():
        lines.append("回复“更多”查看后续选项。")
    if option_set.has_previous_page():
        lines.append("回复“返回”查看上一页。")
    return "\n".join(lines)


def build_enum_option_set(
    param_name: str,
    values: list[str],
    *,
    skill_version: str | None = None,
    now: float | None = None,
) -> OptionSet:
    return OptionSet(
        id=f"enum:{param_name}",
        param_name=param_name,
        source="enum",
        skill_version=skill_version,
        created_at=_timestamp(now),
        items=[
            OptionItem(index=index, label=value, value=value, param_name=param_name)
            for index, value in enumerate(values, start=1)
        ],
    )


def build_resource_option_set(
    param_name: str,
    items: list[dict[str, Any]],
    *,
    skill_version: str | None = None,
    now: float | None = None,
) -> OptionSet:
    option_items: list[OptionItem] = []
    for item in items:
        key = item.get("key") or item.get("id") or item.get("name")
        label = item.get("name") or key
        if not isinstance(key, str) or not isinstance(label, str) or not key or not label:
            continue
        aliases = [value for field in ("key", "id") if isinstance((value := item.get(field)), str) and value]
        value: Any = [key] if param_name == "characters" else key
        option_items.append(
            OptionItem(index=len(option_items) + 1, label=label, value=value, param_name=param_name, aliases=aliases)
        )
    return OptionSet(
        id=f"resource:{param_name}",
        param_name=param_name,
        source="resource",
        skill_version=skill_version,
        created_at=_timestamp(now),
        items=option_items,
    )


def build_router_disambiguation_option_set(
    skills: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> OptionSet:
    return OptionSet(
        id="router:skill",
        param_name="_skill",
        scope="system",
        source="router_disambiguation",
        created_at=_timestamp(now),
        items=[
            OptionItem(
                index=index,
                label=f"{skill['name']} - {skill.get('description', '')}".strip(" -"),
                value=skill["name"],
                param_name="_skill",
                aliases=[skill["name"]],
            )
            for index, skill in enumerate(skills, start=1)
            if isinstance(skill.get("name"), str)
        ],
    )


def _coerce_option_set(value: OptionSet | dict[str, Any]) -> OptionSet:
    if isinstance(value, OptionSet):
        return value
    return OptionSet.model_validate(value)


def _normalize(value: str) -> str:
    return re.sub(r"[\s，,。.!！?？~～()（）]", "", value).lower()


def _timestamp(value: float | None) -> float:
    return time.time() if value is None else value
