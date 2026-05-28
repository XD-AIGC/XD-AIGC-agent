from unittest.mock import AsyncMock

import pytest

from src.conversation.session import ActiveJob, ConversationPhase, ConversationSession
from src.skill.executor import ExecuteResult, SkillExecutionError
from src.skill.schema import PollBackend, Skill, SkillOutput


class _FakeStore:
    def __init__(self, session: ConversationSession) -> None:
        self.session = session
        self.saved: list[ConversationSession] = []

    async def get_conversation(self, _user_id: str) -> ConversationSession:
        return self.session.model_copy(deep=True)

    async def save_conversation(self, _user_id: str, session: ConversationSession) -> None:
        self.session = session.model_copy(deep=True)
        self.saved.append(self.session)

    async def save(self, user_id: str, session: ConversationSession) -> None:
        await self.save_conversation(user_id, session)


def _skill() -> Skill:
    return Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=PollBackend(type="poll", submit_path="/api/jobs", poll_path_template="/api/jobs/{job_id}"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )


def _session(active_job: ActiveJob) -> ConversationSession:
    return ConversationSession(
        phase=ConversationPhase.running_job,
        mode="skill",
        skill_name="xd-poster-gen",
        active_job=active_job,
    )


@pytest.mark.asyncio
async def test_background_poll_submits_poll_job_sends_result_and_marks_completed(monkeypatch):
    from src import main as main_mod

    active_job = ActiveJob(
        job_id="agent-job",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-source",
        status="submitted",
        started_at=90.0,
    )
    store = _FakeStore(_session(active_job))
    submit_poll_job = AsyncMock(return_value="backend-job")
    poll_existing_job = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    reply_text = AsyncMock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "submit_poll_job", submit_poll_job)
    monkeypatch.setattr(main_mod, "poll_existing_job", poll_existing_job)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())

    await main_mod._background_poll("user-1", active_job, "msg-source")

    submit_poll_job.assert_awaited_once()
    poll_existing_job.assert_awaited_once()
    assert poll_existing_job.await_args.args[1] == "backend-job"
    sent = [call.args[2] for call in reply_text.await_args_list]
    assert sent == ["done", "已完成。要继续这个任务、调整哪里，还是换别的需求？"]
    assert store.session.phase == ConversationPhase.completed
    assert store.session.completed is True
    assert store.session.active_job.status == "completed"
    assert store.session.active_job.job_id == "backend-job"


@pytest.mark.asyncio
async def test_background_poll_recovers_existing_running_job_to_current_message(monkeypatch):
    from src import main as main_mod

    active_job = ActiveJob(
        job_id="backend-job",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-source",
        status="running",
        started_at=90.0,
    )
    store = _FakeStore(_session(active_job))
    submit_poll_job = AsyncMock(return_value="should-not-submit")
    poll_existing_job = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    reply_text = AsyncMock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "submit_poll_job", submit_poll_job)
    monkeypatch.setattr(main_mod, "poll_existing_job", poll_existing_job)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())

    await main_mod._background_poll("user-1", active_job, "msg-current")

    submit_poll_job.assert_not_called()
    poll_existing_job.assert_awaited_once()
    assert reply_text.await_args_list[0].args[1] == "msg-current"
    assert store.session.phase == ConversationPhase.completed


@pytest.mark.asyncio
async def test_background_poll_timeout_keeps_running_job_and_offers_system_options(monkeypatch):
    from src import main as main_mod

    active_job = ActiveJob(
        job_id="backend-job",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-source",
        status="running",
        started_at=90.0,
    )
    store = _FakeStore(_session(active_job))
    poll_existing_job = AsyncMock(side_effect=SkillExecutionError("任务 backend-job 轮询超时（300s）"))
    reply_text = AsyncMock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "poll_existing_job", poll_existing_job)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})

    await main_mod._background_poll("user-1", active_job, "msg-current")

    assert store.session.phase == ConversationPhase.running_job
    assert store.session.active_job.status == "timeout"
    sent = reply_text.await_args_list[-1].args[2]
    assert "生成还没完成" in sent
    assert "继续等待" in sent
    assert "重试" in sent
    assert "修改信息" in sent
    assert "取消" in sent
