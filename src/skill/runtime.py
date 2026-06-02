"""Typed action schema for Skill Mode runtime decisions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.orchestrator.schema import JsonEntry, json_entries_to_dict


SkillRuntimeActionName = Literal[
    "lookup_characters",
    "lookup_options",
    "call_skill_action",
    "call_mivo_mcp",
    "ask_param",
    "await_confirmation",
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


class SkillRuntimeWireAction(BaseModel):
    """Bedrock-safe wire schema for skill LLM decisions.

    Dynamic JSON object payloads are represented as strict key/value arrays and
    converted back to the internal dict-based SkillRuntimeAction before use.
    """

    action: SkillRuntimeActionName
    param_name: str | None = None
    param_value: str | None = None
    message: str | None = None
    submit_payload: list[JsonEntry] = Field(default_factory=list)
    action_name: str | None = None
    action_params: list[JsonEntry] = Field(default_factory=list)
    updated_params: list[JsonEntry] = Field(default_factory=list)

    def to_runtime_action(self) -> SkillRuntimeAction:
        submit_payload = json_entries_to_dict(self.submit_payload)
        return SkillRuntimeAction(
            action=self.action,
            param_name=self.param_name,
            param_value=self.param_value,
            message=self.message,
            submit_payload=submit_payload or None,
            action_name=self.action_name,
            action_params=json_entries_to_dict(self.action_params),
            updated_params=json_entries_to_dict(self.updated_params),
        )
