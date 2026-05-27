import json

import pytest

from src.conversation.session import (
    ActiveJob,
    CompletedResult,
    ConversationPhase,
    ConversationSession,
    dump_session,
    infer_phase_from_legacy_fields,
    load_session,
    sync_legacy_fields,
    to_legacy_user_session,
)
from src.orchestrator.schema import UserSession
from src.session.redis_store import SessionStore


def _load(data: dict) -> ConversationSession:
    return load_session(json.dumps(data).encode("utf-8"))


def test_load_session_returns_default_v2_session_when_missing():
    session = load_session(None)

    assert session.schema_version == 2
    assert session.phase == ConversationPhase.idle
    assert session.mode == "router"
    assert session.completed is False
    assert session.state == "idle"


@pytest.mark.parametrize(
    ("legacy", "phase"),
    [
        ({}, ConversationPhase.idle),
        ({"state": "collecting", "pending_param": "image"}, ConversationPhase.collecting),
        ({"mode": "skill", "skill_name": "xd-poster-gen"}, ConversationPhase.collecting),
        ({"completed": True, "state": "collecting"}, ConversationPhase.completed),
    ],
)
def test_load_session_migrates_v1_phase_matrix(legacy, phase):
    session = _load({"schema_version": 1, **legacy})

    assert session.schema_version == 2
    assert session.phase == phase
    assert session.mode == ("router" if phase == ConversationPhase.idle else "skill")
    assert session.completed is (phase == ConversationPhase.completed)


def test_public_legacy_phase_inference_matches_v1_migration_matrix():
    assert infer_phase_from_legacy_fields({}) == ConversationPhase.idle
    assert infer_phase_from_legacy_fields({"state": "collecting"}) == ConversationPhase.collecting
    assert infer_phase_from_legacy_fields(UserSession(mode="skill", skill_name="xd-poster-gen")) == (
        ConversationPhase.collecting
    )
    assert infer_phase_from_legacy_fields(UserSession(completed=True, state="collecting")) == (
        ConversationPhase.completed
    )


def test_load_session_preserves_v1_payload_fields():
    session = _load(
        {
            "schema_version": 1,
            "mode": "skill",
            "skill_name": "xd-poster-gen",
            "initial_intent": "做一张海报",
            "collected_params": {"characters": ["bill"]},
            "pending_param": "ratio",
            "loaded_resources": {"lookup_characters": "[]"},
            "chat_history": [{"role": "assistant", "content": "请选择角色"}],
        }
    )

    assert session.phase == ConversationPhase.collecting
    assert session.skill_name == "xd-poster-gen"
    assert session.initial_intent == "做一张海报"
    assert session.collected_params == {"characters": ["bill"]}
    assert session.pending_param == "ratio"
    assert session.loaded_resources == {"lookup_characters": "[]"}
    assert session.chat_history[0].role == "assistant"


@pytest.mark.parametrize(
    ("phase", "legacy"),
    [
        (ConversationPhase.idle, {"mode": "router", "completed": False, "state": "idle"}),
        (ConversationPhase.collecting, {"mode": "skill", "completed": False, "state": "collecting"}),
        (
            ConversationPhase.awaiting_confirmation,
            {"mode": "skill", "completed": False, "state": "collecting"},
        ),
        (ConversationPhase.running_job, {"mode": "skill", "completed": False, "state": "idle"}),
        (ConversationPhase.completed, {"mode": "skill", "completed": True, "state": "idle"}),
        (ConversationPhase.cancelled, {"mode": "skill", "completed": False, "state": "idle"}),
        (ConversationPhase.failed, {"mode": "skill", "completed": False, "state": "idle"}),
    ],
)
def test_sync_legacy_fields_mirror_matrix(phase, legacy):
    session = ConversationSession(phase=phase, skill_name="xd-poster-gen")

    sync_legacy_fields(session)

    assert session.mode == legacy["mode"]
    assert session.completed is legacy["completed"]
    assert session.state == legacy["state"]


def test_to_legacy_user_session_degradation_matrix():
    running = ConversationSession(
        phase=ConversationPhase.running_job,
        skill_name="xd-poster-gen",
        active_job=ActiveJob(
            job_id="job-1",
            skill_name="xd-poster-gen",
            action_name="submit_job",
            payload={"ratio": "3:2"},
            source_message_id="msg-1",
            status="running",
            started_at=100.0,
        ),
    )
    awaiting = ConversationSession(
        phase=ConversationPhase.awaiting_confirmation,
        skill_name="xd-poster-gen",
        collected_params={"ratio": "3:2"},
    )
    completed = ConversationSession(
        phase=ConversationPhase.completed,
        skill_name="xd-poster-gen",
        completed_result=CompletedResult(
            submitted_payload={"ratio": "3:2"},
            artifacts={"file_id": "result-file"},
            completed_at=101.0,
            source_message_id="msg-2",
        ),
    )

    assert to_legacy_user_session(running).model_dump() == {
        "mode": "skill",
        "skill_name": "xd-poster-gen",
        "collected_params": {},
        "pending_param": None,
        "loaded_resources": {},
        "initial_intent": None,
        "completed": False,
        "chat_history": [],
        "last_options": None,
        "state": "idle",
    }
    assert to_legacy_user_session(awaiting).state == "collecting"
    assert to_legacy_user_session(awaiting).pending_param is None
    assert to_legacy_user_session(completed).completed is True


def test_dump_session_syncs_legacy_fields_and_trims_processed_message_ids():
    session = ConversationSession(
        phase=ConversationPhase.completed,
        last_processed_message_ids=[f"msg-{i}" for i in range(25)],
    )

    dumped = json.loads(dump_session(session))

    assert dumped["mode"] == "skill"
    assert dumped["completed"] is True
    assert dumped["state"] == "idle"
    assert dumped["last_processed_message_ids"] == [f"msg-{i}" for i in range(5, 25)]


def test_dump_session_accepts_v1_user_session_and_upgrades_to_v2():
    raw = dump_session(UserSession(mode="skill", skill_name="xd-poster-gen"))
    dumped = json.loads(raw)

    assert dumped["schema_version"] == 2
    assert dumped["phase"] == "collecting"
    assert dumped["mode"] == "skill"


def test_conversation_session_trims_processed_message_ids_on_validation():
    session = ConversationSession(last_processed_message_ids=[f"msg-{i}" for i in range(25)])

    assert session.last_processed_message_ids == [f"msg-{i}" for i in range(5, 25)]


@pytest.mark.asyncio
async def test_session_store_v2_helpers_roundtrip(monkeypatch):
    redis = _MemoryRedis()
    store = SessionStore()
    monkeypatch.setattr(store, "_redis", redis)

    session = ConversationSession(phase=ConversationPhase.completed, skill_name="xd-poster-gen")

    await store.save_conversation("user-1", session)
    loaded = await store.get_conversation("user-1")

    assert loaded.phase == ConversationPhase.completed
    assert loaded.mode == "skill"
    assert loaded.completed is True


@pytest.mark.asyncio
async def test_session_store_save_accepts_conversation_session_and_syncs_legacy_fields(monkeypatch):
    redis = _MemoryRedis()
    store = SessionStore()
    monkeypatch.setattr(store, "_redis", redis)

    session = ConversationSession(phase=ConversationPhase.completed, skill_name="xd-poster-gen")

    await store.save("user-1", session)

    raw = json.loads(redis.data["session:user-1"])
    assert raw["schema_version"] == 2
    assert raw["phase"] == "completed"
    assert raw["mode"] == "skill"
    assert raw["completed"] is True
    assert raw["state"] == "idle"


class _MemoryRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
