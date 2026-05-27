"""ConversationSession v2 model and v1 compatibility helpers."""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.orchestrator.schema import UserSession


_MAX_PROCESSED_MESSAGE_IDS = 20


class ConversationPhase(str, Enum):
    idle = "idle"
    selecting_skill = "selecting_skill"
    collecting = "collecting"
    awaiting_confirmation = "awaiting_confirmation"
    running_job = "running_job"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CompletedResult(BaseModel):
    submitted_payload: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    completed_at: float
    source_message_id: str


class ActiveJob(BaseModel):
    job_id: str
    skill_name: str
    action_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source_message_id: str
    status: Literal["submitted", "running", "completed", "failed", "cancelled", "timeout"]
    started_at: float
    last_poll_at: float | None = None
    poll_count: int = 0
    last_observation: dict[str, Any] | None = None
    cancelled_locally: bool = False


class ConversationSession(BaseModel):
    schema_version: int = 2
    phase: ConversationPhase = ConversationPhase.idle
    skill_name: str | None = None
    initial_intent: str | None = None
    collected_params: dict[str, Any] = Field(default_factory=dict)
    pending_param: str | None = None
    # OptionSet lands in PR-0c; keep this field opaque in PR-0b.
    last_options: dict[str, Any] | None = None
    active_job: ActiveJob | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    completed_result: CompletedResult | None = None
    chat_history: list[Message] = Field(default_factory=list)
    last_processed_message_ids: list[str] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)

    # v1 mirror fields. v2 logic must treat phase as the only source of truth.
    mode: Literal["router", "skill"] = "router"
    completed: bool = False
    state: Literal["idle", "collecting"] = "idle"
    loaded_resources: dict[str, str] = Field(default_factory=dict)


def load_session(raw: bytes | str | dict[str, Any] | None) -> ConversationSession:
    """Load missing, v1, or v2 session data into ConversationSession v2."""
    if raw is None:
        return sync_legacy_fields(ConversationSession())

    data = _decode_raw(raw)
    if int(data.get("schema_version", 1)) < 2:
        data = _migrate_v1_data(data)
    else:
        data["schema_version"] = 2

    return sync_legacy_fields(ConversationSession.model_validate(data))


def dump_session(session: ConversationSession | UserSession) -> str:
    """Serialize a session as v2 JSON after syncing legacy mirror fields."""
    if isinstance(session, ConversationSession):
        conversation = session
    else:
        conversation = load_session(session.model_dump())
    sync_legacy_fields(conversation)
    return conversation.model_dump_json()


def sync_legacy_fields(session: ConversationSession) -> ConversationSession:
    """Mirror v2 phase into v1 fields before persistence or rollback."""
    session.mode = "router" if session.phase == ConversationPhase.idle else "skill"
    session.completed = session.phase == ConversationPhase.completed
    session.state = (
        "collecting"
        if session.phase in {ConversationPhase.collecting, ConversationPhase.awaiting_confirmation}
        else "idle"
    )
    session.last_processed_message_ids = session.last_processed_message_ids[-_MAX_PROCESSED_MESSAGE_IDS:]
    return session


def to_legacy_user_session(session: ConversationSession) -> UserSession:
    """Return the degraded v1 view used for rollback compatibility checks."""
    sync_legacy_fields(session)
    return UserSession(
        mode=session.mode,
        skill_name=session.skill_name,
        collected_params=session.collected_params,
        pending_param=session.pending_param,
        loaded_resources=session.loaded_resources,
        initial_intent=session.initial_intent,
        completed=session.completed,
        chat_history=[message.model_dump() for message in session.chat_history],
        state=session.state,
    )


def _decode_raw(raw: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("session payload must be a JSON object")
    return data


def _migrate_v1_data(data: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(data)
    migrated["schema_version"] = 2
    migrated["phase"] = _phase_from_v1(migrated).value
    return migrated


def _phase_from_v1(data: dict[str, Any]) -> ConversationPhase:
    if data.get("completed"):
        return ConversationPhase.completed
    if data.get("state") == "collecting":
        return ConversationPhase.collecting
    # Current v1 complex-skill sessions often keep state=idle and only set
    # mode=skill. Treat that as active collection, otherwise migration drops
    # the whole in-flight skill context.
    if data.get("mode") == "skill" or data.get("skill_name"):
        return ConversationPhase.collecting
    return ConversationPhase.idle
