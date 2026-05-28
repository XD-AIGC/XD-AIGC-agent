import json

import pytest

from src.conversation.session import ActiveJob, ConversationPhase, ConversationSession
from src.skill.job_controller import (
    InvalidJobPayloadError,
    JobController,
    PayloadTooLargeError,
    StaleSessionError,
)


class _MemoryRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True


def _controller(redis: _MemoryRedis) -> JobController:
    return JobController(
        redis=redis,
        now=lambda: 100.0,
        job_id_factory=lambda: "job-1",
    )


@pytest.mark.asyncio
async def test_begin_submit_creates_active_job_and_records_message_id():
    redis = _MemoryRedis()
    session = ConversationSession(
        phase=ConversationPhase.awaiting_confirmation,
        skill_name="xd-poster-gen",
        updated_at=50.0,
    )

    result = await _controller(redis).begin_submit(
        session,
        user_id="user-1",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-1",
        expected_updated_at=50.0,
    )

    assert result.created is True
    assert result.duplicate is False
    assert session.phase == ConversationPhase.running_job
    assert session.active_job == ActiveJob(
        job_id="job-1",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-1",
        status="submitted",
        started_at=100.0,
    )
    assert session.last_processed_message_ids == ["msg-1"]
    assert json.loads(next(iter(redis.data.values())))["source_message_id"] == "msg-1"


@pytest.mark.asyncio
async def test_begin_submit_returns_session_active_job_for_same_source_message_id():
    redis = _MemoryRedis()
    session = ConversationSession(
        phase=ConversationPhase.running_job,
        skill_name="xd-poster-gen",
        last_processed_message_ids=["msg-1"],
        active_job=ActiveJob(
            job_id="existing-job",
            skill_name="xd-poster-gen",
            action_name="submit",
            payload={"topic": "coffee"},
            source_message_id="msg-1",
            status="running",
            started_at=90.0,
        ),
    )

    result = await _controller(redis).begin_submit(
        session,
        user_id="user-1",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-1",
    )

    assert result.created is False
    assert result.duplicate is True
    assert result.active_job.job_id == "existing-job"
    assert session.last_processed_message_ids == ["msg-1"]
    assert redis.data == {}


@pytest.mark.asyncio
async def test_begin_submit_returns_redis_job_for_global_idempotency_conflict():
    redis = _MemoryRedis()
    existing = ActiveJob(
        job_id="redis-job",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-1",
        status="running",
        started_at=90.0,
    )
    redis.data[JobController.idempotency_key("user-1", "msg-1", "xd-poster-gen")] = existing.model_dump_json()
    session = ConversationSession(phase=ConversationPhase.awaiting_confirmation, skill_name="xd-poster-gen")

    result = await _controller(redis).begin_submit(
        session,
        user_id="user-1",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-1",
    )

    assert result.created is False
    assert result.duplicate is True
    assert result.active_job.job_id == "redis-job"
    assert session.active_job == existing
    assert session.phase == ConversationPhase.running_job


@pytest.mark.asyncio
async def test_begin_submit_rejects_stale_session_version():
    redis = _MemoryRedis()
    session = ConversationSession(updated_at=101.0)

    with pytest.raises(StaleSessionError):
        await _controller(redis).begin_submit(
            session,
            user_id="user-1",
            skill_name="xd-poster-gen",
            action_name="submit",
            payload={"topic": "coffee"},
            source_message_id="msg-1",
            expected_updated_at=100.0,
        )

    assert session.active_job is None
    assert redis.data == {}


@pytest.mark.asyncio
async def test_begin_submit_rejects_bytes_payload():
    redis = _MemoryRedis()
    session = ConversationSession()

    with pytest.raises(InvalidJobPayloadError, match="bytes"):
        await _controller(redis).begin_submit(
            session,
            user_id="user-1",
            skill_name="xd-poster-gen",
            action_name="submit",
            payload={"image": b"raw"},
            source_message_id="msg-1",
        )

    assert session.active_job is None
    assert redis.data == {}


@pytest.mark.asyncio
async def test_begin_submit_rejects_base64_payload():
    redis = _MemoryRedis()
    session = ConversationSession()

    with pytest.raises(InvalidJobPayloadError, match="base64"):
        await _controller(redis).begin_submit(
            session,
            user_id="user-1",
            skill_name="xd-poster-gen",
            action_name="submit",
            payload={"image_base64": "a" * 600},
            source_message_id="msg-1",
        )

    assert session.active_job is None
    assert redis.data == {}


@pytest.mark.asyncio
async def test_begin_submit_rejects_payload_above_soft_limit():
    redis = _MemoryRedis()
    session = ConversationSession()

    with pytest.raises(PayloadTooLargeError):
        await _controller(redis).begin_submit(
            session,
            user_id="user-1",
            skill_name="xd-poster-gen",
            action_name="submit",
            payload={"prompt": "x" * 10_200},
            source_message_id="msg-1",
        )

    assert session.active_job is None
    assert redis.data == {}


def test_recovery_candidate_returns_running_active_job_only():
    active = ActiveJob(
        job_id="job-1",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-1",
        status="running",
        started_at=90.0,
    )
    session = ConversationSession(phase=ConversationPhase.running_job, active_job=active)

    assert JobController.recovery_candidate(session) == active

    session.active_job = active.model_copy(update={"status": "completed"})
    assert JobController.recovery_candidate(session) is None
