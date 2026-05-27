"""Structured option sets shown to users during conversation."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


OptionScope = Literal["skill_param", "system"]
OptionSource = Literal["enum", "resource", "skill_runtime", "router_disambiguation"]


class OptionItem(BaseModel):
    index: int
    label: str
    value: Any
    param_name: str
    aliases: list[str] = Field(default_factory=list)


class OptionSet(BaseModel):
    id: str
    param_name: str
    source: OptionSource
    items: list[OptionItem]
    scope: OptionScope = "skill_param"
    page: int = 1
    page_size: int = 8
    allow_multi: bool = False
    skill_version: str | None = None
    created_at: float = Field(default_factory=time.time)
    ttl_sec: int = 300

    def page_items(self) -> list[OptionItem]:
        start = (self.page - 1) * self.page_size
        end = start + self.page_size
        return self.items[start:end]

    def has_next_page(self) -> bool:
        return self.page * self.page_size < len(self.items)

    def has_previous_page(self) -> bool:
        return self.page > 1

    def is_stale(self, *, now: float, skill_version: str | None = None) -> bool:
        if now - self.created_at > self.ttl_sec:
            return True
        return bool(self.skill_version and skill_version and self.skill_version != skill_version)
