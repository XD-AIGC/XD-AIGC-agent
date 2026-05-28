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
            data=self._observation_data(data, data_schema_id),
            artifacts=dict(artifacts or {}),
            next_actions=normalized_next_actions,
            stop_condition=normalized_stop_condition,
        )

    def _observation_data(self, data: Any, schema_id: str | None) -> ObservationData | None:
        if data is None:
            return None
        payload = self._payload_dict(data)
        return ObservationData(
            schema_id=schema_id or _infer_schema_id(payload),
            payload=payload,
        )

    @staticmethod
    def _payload_dict(data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            return {"items": data}
        return {"value": data}


def _infer_schema_id(payload: dict[str, Any]) -> str:
    if _first_str(payload, "fileId", "file_id"):
        return "image.fileId"
    if _first_str(payload, "url", "result_url"):
        return "image.url"
    if _first_str(payload, "job_id", "jobId", "v2JobId"):
        return "job.polling"
    if isinstance(payload.get("items"), list):
        return "lookup.characters"
    if _first_str(payload, "text"):
        return "text.plain"
    return "unknown.raw"


def _first_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None
