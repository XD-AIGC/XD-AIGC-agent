"""Typed action schema for Skill Mode runtime decisions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SkillRuntimeActionName = Literal[
    "lookup_characters",
    "lookup_options",
    "call_skill_action",
    "ask_param",
    "submit",
    "complete",
    "exit_skill",
    "reply",
]


class SkillRuntimeAction(BaseModel):
    """Skill-only action space.

    Router-only actions such as select_skill/out_of_scope intentionally do not
    exist here. Skill Mode may finish a task with `complete` while preserving
    context, or leave the skill entirely with `exit_skill`.
    """

    action: SkillRuntimeActionName
    param_name: str | None = None
    param_value: str | None = None
    message: str | None = None
    submit_payload: dict[str, Any] | None = None
    action_name: str | None = None
    action_params: dict[str, Any] = Field(default_factory=dict)
    updated_params: dict[str, Any] = Field(default_factory=dict)
