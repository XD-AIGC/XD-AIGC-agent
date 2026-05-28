"""Job submission guardrails for skill execution.

P2a keeps execution synchronous. This controller only creates the durable
ActiveJob record and enforces idempotency before the existing executor runs.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from src.conversation.session import ActiveJob, ConversationPhase, ConversationSession


_DEFAULT_TTL_SEC = 3600
_MAX_PAYLOAD_BYTES = 10_000
_MAX_PROCESSED_MESSAGE_IDS = 20
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/\r\n=]+$")
_ACTIVE_RECOVERY_STATUSES = {"submitted", "running", "timeout"}


class JobControllerError(Exception):
    """Base class for job controller failures."""


class InvalidJobPayloadError(JobControllerError):
    """The payload contains data that must not be persisted in active_job."""


class PayloadTooLargeError(InvalidJobPayloadError):
    """The payload exceeds the Redis active_job soft limit."""


class StaleSessionError(JobControllerError):
    """The session changed after the caller made the submit decision."""


@dataclass(frozen=True)
class SubmitJobResult:
    active_job: ActiveJob
    created: bool
    duplicate: bool = False


class JobController:
    def __init__(
        self,
        *,
        redis: Any | None = None,
        redis_getter: Callable[[], Any | None] | None = None,
        ttl_sec: int = _DEFAULT_TTL_SEC,
        max_payload_bytes: int = _MAX_PAYLOAD_BYTES,
        now: Callable[[], float] = time.time,
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._redis_getter = redis_getter or (lambda: redis)
        self._ttl_sec = ttl_sec
        self._max_payload_bytes = max_payload_bytes
        self._now = now
        self._job_id_factory = job_id_factory or (lambda: f"agent-{uuid.uuid4().hex}")

    @staticmethod
    def idempotency_key(user_id: str, source_message_id: str, skill_name: str) -> str:
        return f"job_idempotency:{user_id}:{source_message_id}:{skill_name}"

    async def begin_submit(
        self,
        session: Any,
        *,
        user_id: str,
        skill_name: str,
        action_name: str,
        payload: dict[str, Any],
        source_message_id: str,
        expected_updated_at: float | None = None,
    ) -> SubmitJobResult:
        self._check_session_version(session, expected_updated_at)
        normalized_payload = self._validate_payload(payload)

        session_job = self._duplicate_from_session(session, source_message_id, skill_name)
        if session_job is not None:
            return SubmitJobResult(active_job=session_job, created=False, duplicate=True)

        active_job = ActiveJob(
            job_id=self._job_id_factory(),
            skill_name=skill_name,
            action_name=action_name,
            payload=normalized_payload,
            source_message_id=source_message_id,
            status="submitted",
            started_at=self._now(),
        )

        key = self.idempotency_key(user_id, source_message_id, skill_name)
        if not await self._try_reserve(key, active_job):
            existing = await self._load_active_job(key)
            if existing is not None:
                self._apply_active_job(session, existing, source_message_id)
                return SubmitJobResult(active_job=existing, created=False, duplicate=True)

        self._apply_active_job(session, active_job, source_message_id)
        return SubmitJobResult(active_job=active_job, created=True)

    @staticmethod
    def recovery_candidate(session: ConversationSession) -> ActiveJob | None:
        if session.phase != ConversationPhase.running_job or session.active_job is None:
            return None
        if session.active_job.cancelled_locally:
            return None
        if session.active_job.status not in _ACTIVE_RECOVERY_STATUSES:
            return None
        return session.active_job

    def mark_completed(self, session: Any, active_job: ActiveJob, *, observation: dict[str, Any] | None = None) -> None:
        completed = active_job.model_copy(
            update={
                "status": "completed",
                "last_poll_at": self._now(),
                "last_observation": observation,
            }
        )
        self._set_if_present(session, "active_job", completed)
        self._set_if_present(session, "phase", ConversationPhase.completed)
        self._set_if_present(session, "updated_at", self._now())

    def mark_failed(self, session: Any, active_job: ActiveJob, *, observation: dict[str, Any] | None = None) -> None:
        failed = active_job.model_copy(
            update={
                "status": "failed",
                "last_poll_at": self._now(),
                "last_observation": observation,
            }
        )
        self._set_if_present(session, "active_job", failed)
        self._set_if_present(session, "phase", ConversationPhase.failed)
        self._set_if_present(session, "updated_at", self._now())

    def _check_session_version(self, session: Any, expected_updated_at: float | None) -> None:
        if expected_updated_at is None:
            return
        actual = getattr(session, "updated_at", None)
        if actual is not None and actual != expected_updated_at:
            raise StaleSessionError("session was modified before submit")

    def _duplicate_from_session(
        self,
        session: Any,
        source_message_id: str,
        skill_name: str,
    ) -> ActiveJob | None:
        processed = getattr(session, "last_processed_message_ids", None) or []
        active_job = getattr(session, "active_job", None)
        if source_message_id not in processed or active_job is None:
            return None
        if active_job.source_message_id != source_message_id:
            return None
        if active_job.skill_name != skill_name:
            return None
        return active_job

    async def _try_reserve(self, key: str, active_job: ActiveJob) -> bool:
        redis = self._redis_getter()
        if redis is None:
            return True
        result = await redis.set(key, active_job.model_dump_json(), ex=self._ttl_sec, nx=True)
        return bool(result)

    async def _load_active_job(self, key: str) -> ActiveJob | None:
        redis = self._redis_getter()
        if redis is None:
            return None
        raw = await redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ActiveJob.model_validate_json(raw)

    def _apply_active_job(self, session: Any, active_job: ActiveJob, source_message_id: str) -> None:
        self._set_if_present(session, "active_job", active_job)
        self._set_if_present(session, "phase", ConversationPhase.running_job)
        processed = list(getattr(session, "last_processed_message_ids", []) or [])
        if source_message_id not in processed:
            processed.append(source_message_id)
        self._set_if_present(session, "last_processed_message_ids", processed[-_MAX_PROCESSED_MESSAGE_IDS:])
        self._set_if_present(session, "updated_at", self._now())

    @staticmethod
    def _set_if_present(session: Any, field: str, value: Any) -> None:
        if hasattr(session, field):
            setattr(session, field, value)

    def _validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InvalidJobPayloadError("active_job payload must be a JSON object")
        _reject_forbidden_payload_values(payload)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise InvalidJobPayloadError(f"active_job payload must be JSON serializable: {exc}") from exc
        if len(encoded) > self._max_payload_bytes:
            raise PayloadTooLargeError("active_job payload exceeds 10KB; use compact fileId/public_id refs")
        return json.loads(encoded.decode("utf-8"))


def _reject_forbidden_payload_values(value: Any, path: str = "$") -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise InvalidJobPayloadError(f"{path} contains bytes; persist fileId/public_id instead")
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            key_path = f"{path}.{key_text}"
            _reject_forbidden_key(key_text, item, key_path)
            _reject_forbidden_payload_values(item, key_path)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_payload_values(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        _reject_forbidden_string(value, path)


def _reject_forbidden_key(key: str, value: Any, path: str) -> None:
    lowered = key.lower()
    compact = lowered.replace("-", "_")
    if "base64" in compact:
        raise InvalidJobPayloadError(f"{path} looks like base64 content; persist fileId/public_id instead")
    if "signed_url" in compact or "signedurl" in compact:
        raise InvalidJobPayloadError(f"{path} contains a signed URL; persist stable refs instead")
    if compact in {"loaded_resources", "lazy_resources"}:
        raise InvalidJobPayloadError(f"{path} contains full lazy resources; persist compact refs only")
    if compact.startswith("lookup_") and isinstance(value, (dict, list, tuple)):
        raise InvalidJobPayloadError(f"{path} contains a full lookup resource; persist selected refs only")


def _reject_forbidden_string(value: str, path: str) -> None:
    if value.startswith("data:"):
        raise InvalidJobPayloadError(f"{path} contains data URL/base64 content")
    if _looks_like_signed_url(value):
        raise InvalidJobPayloadError(f"{path} contains a signed URL; persist stable refs instead")
    if _looks_like_base64_blob(value):
        raise InvalidJobPayloadError(f"{path} looks like base64 content; persist fileId/public_id instead")


def _looks_like_base64_blob(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 512 or len(compact) % 4 != 0:
        return False
    if not _BASE64_RE.fullmatch(compact):
        return False
    # Long natural-language prompts can be alphanumeric. Require a base64-only
    # marker to avoid rejecting legitimate text before the 10KB size check.
    return any(marker in compact for marker in ("+", "/", "="))


def _looks_like_signed_url(value: str) -> bool:
    if not value.startswith(("http://", "https://")) or "?" not in value:
        return False
    lowered = value.lower()
    signed_markers = (
        "x-amz-signature=",
        "x-oss-signature=",
        "signature=",
        "expires=",
        "x-amz-expires=",
    )
    return any(marker in lowered for marker in signed_markers)
