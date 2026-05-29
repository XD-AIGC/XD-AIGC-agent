"""Typed observation envelope for Skill Runtime feedback."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ObservationStatus = Literal["success", "warning", "error"]


class ObservationData(BaseModel):
    schema_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    status: ObservationStatus
    summary: str
    data: ObservationData | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    next_actions: list[str] = Field(default_factory=list)
    stop_condition: str | None = None


class ObservationReducer:
    """Normalize raw skill action results into the two-layer prompt envelope."""

    def reduce(
        self,
        *,
        status: ObservationStatus,
        summary: str,
        data: Any = None,
        artifacts: dict[str, Any] | None = None,
        data_schema_id: str | None = None,
        source_name: str | None = None,
        next_actions: list[str] | None = None,
        stop_condition: str | None = None,
    ) -> Observation:
        normalized_next_actions = list(next_actions or [])
        normalized_stop_condition = stop_condition
        if status == "error":
            if not normalized_next_actions:
                normalized_next_actions = ["check_action_params", "retry_or_exit_skill"]
            if normalized_stop_condition is None:
                normalized_stop_condition = "do not retry the same action without changed parameters"

        return Observation(
            status=status,
            summary=summary,
            data=self._observation_data(data, data_schema_id, source_name),
            artifacts=dict(artifacts or {}),
            next_actions=normalized_next_actions,
            stop_condition=normalized_stop_condition,
        )

    def _observation_data(
        self,
        data: Any,
        schema_id: str | None,
        source_name: str | None,
    ) -> ObservationData | None:
        if data is None:
            return None
        payload = self._payload_dict(data)
        return ObservationData(
            schema_id=schema_id or _infer_schema_id(payload, source_name),
            payload=payload,
        )

    @staticmethod
    def _payload_dict(data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, str):
            return {"text": data}
        if isinstance(data, list):
            return {"items": data}
        return {"value": data}


def _infer_schema_id(payload: dict[str, Any], source_name: str | None) -> str:
    if _first_str(payload, "fileId", "file_id"):
        return "image.fileId"
    if _first_str(payload, "url", "result_url"):
        return "image.url"
    if _first_str(payload, "job_id", "jobId", "v2JobId"):
        return "job.polling"
    if _first_str(payload, "text"):
        return "text.plain"
    items = payload.get("items")
    if isinstance(items, list):
        if _items_contain_image_ref(items):
            return "image.list"
        if _source_is_character_lookup(source_name):
            return "lookup.characters"
        return "unknown.raw"
    return "unknown.raw"


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _items_contain_image_ref(items: list[Any]) -> bool:
    for item in items:
        if isinstance(item, dict) and _first_str(item, "fileId", "file_id", "url", "result_url"):
            return True
    return False


def _source_is_character_lookup(source_name: str | None) -> bool:
    return bool(source_name and "characters" in source_name.lower())
