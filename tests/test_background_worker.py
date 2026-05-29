import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.conversation.session import ActiveJob, CompletedResult, ConversationPhase, ConversationSession
from src.conversation.response import ResponseComposer
from src.skill.executor import ExecuteResult, SkillExecutionError
from src.skill.schema import HttpBackend, PollBackend, Skill, SkillOutput


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


def _http_skill() -> Skill:
    return Skill(
        name="frame-bg-remover",
        description="去背景",
        api=HttpBackend(type="http", endpoint_path="/api/remove-bg"),
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


def _active_job(status: str = "running") -> ActiveJob:
    return ActiveJob(
        job_id="backend-job",
        skill_name="xd-poster-gen",
        action_name="submit",
        payload={"topic": "coffee"},
        source_message_id="msg-source",
        status=status,
        started_at=90.0,
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


@pytest.mark.asyncio
async def test_running_job_cancel_acknowledges_cancel_intent(monkeypatch):
    from src import main as main_mod

    session = _session(_active_job("running"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)

    await main_mod._agentic_loop("取消", session, "user-1", "msg-current")

    sent = reply_text.await_args_list[-1].args[2]
    assert sent == ResponseComposer().local_cancel()
    assert store.session.phase == ConversationPhase.completed
    assert store.session.completed is True
    assert store.session.active_job.cancelled_locally is True
    assert store.session.active_job.status == "cancelled"
    start_worker.assert_not_called()


@pytest.mark.asyncio
async def test_background_poll_discards_cancelled_local_job_result(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running")
    cancelled = active_job.model_copy(update={"status": "cancelled", "cancelled_locally": True})
    store = _FakeStore(_session(cancelled))
    poll_existing_job = AsyncMock(return_value=ExecuteResult(kind="text", text="late result"))
    reply_text = AsyncMock()
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "poll_existing_job", poll_existing_job)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "record_metric", record_metric)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})

    await main_mod._background_poll("user-1", active_job, "msg-source")

    poll_existing_job.assert_awaited_once()
    reply_text.assert_not_called()
    assert store.session.active_job.cancelled_locally is True
    record_metric.assert_called_once_with(
        "running_job_anomaly",
        stage="complete",
        reason="active_job_mismatch",
        skill_name="xd-poster-gen",
        job_status="running",
        user_key="u_c6c289e49e9c",
    )


@pytest.mark.asyncio
async def test_complete_background_job_records_delayed_reply_failure(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running")
    store = _FakeStore(_session(active_job))
    reply_text = AsyncMock(return_value=False)
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "record_metric", record_metric)

    await main_mod._complete_background_job(
        "user-1",
        active_job,
        "msg-source",
        _skill(),
        ExecuteResult(kind="text", text="done"),
    )

    assert reply_text.await_count == 2
    record_metric.assert_any_call(
        "delayed_reply_failure",
        stage="send_result",
        skill_name="xd-poster-gen",
        job_status="running",
        result_kind="text",
        reply_channel="text",
        user_key="u_c6c289e49e9c",
    )


@pytest.mark.asyncio
async def test_complete_background_job_records_text_reply_failure_without_stubbing_send(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running")
    store = _FakeStore(_session(active_job))
    reply_text = AsyncMock(return_value=False)
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())
    monkeypatch.setattr(main_mod, "record_metric", record_metric)

    await main_mod._complete_background_job(
        "user-1",
        active_job,
        "msg-source",
        _skill(),
        ExecuteResult(kind="text", text="done"),
    )

    record_metric.assert_any_call(
        "delayed_reply_failure",
        stage="send_result",
        skill_name="xd-poster-gen",
        job_status="running",
        result_kind="text",
        reply_channel="text",
        user_key="u_c6c289e49e9c",
    )


@pytest.mark.asyncio
async def test_complete_background_job_records_image_reply_channel(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running")
    store = _FakeStore(_session(active_job))
    upload_image = AsyncMock(return_value="img-key")
    reply_image = AsyncMock(return_value=False)
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "upload_image", upload_image)
    monkeypatch.setattr(main_mod, "reply_image", reply_image)
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())
    monkeypatch.setattr(main_mod, "record_metric", record_metric)

    await main_mod._complete_background_job(
        "user-1",
        active_job,
        "msg-source",
        _skill(),
        ExecuteResult(kind="binary", content_bytes=b"png"),
    )

    upload_image.assert_awaited_once()
    assert reply_image.await_count == 2
    record_metric.assert_any_call(
        "delayed_reply_failure",
        stage="send_result",
        skill_name="xd-poster-gen",
        job_status="running",
        result_kind="binary",
        reply_channel="image",
        user_key="u_c6c289e49e9c",
    )


@pytest.mark.asyncio
async def test_complete_background_job_retries_result_reply_before_completion(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running")
    store = _FakeStore(_session(active_job))
    reply_text = AsyncMock(side_effect=[False, True, True])
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "record_metric", record_metric)

    await main_mod._complete_background_job(
        "user-1",
        active_job,
        "msg-source",
        _skill(),
        ExecuteResult(kind="text", text="done"),
    )

    assert reply_text.await_count == 3
    assert store.session.phase == ConversationPhase.completed
    assert store.session.completed is True
    assert store.session.active_job.status == "completed"
    delayed_failures = [
        call for call in record_metric.call_args_list
        if call.args and call.args[0] == "delayed_reply_failure"
    ]
    assert delayed_failures == []


@pytest.mark.asyncio
async def test_complete_background_job_keeps_running_when_result_reply_fails_after_retry(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running")
    store = _FakeStore(_session(active_job))
    reply_text = AsyncMock(return_value=False)
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "record_metric", record_metric)

    await main_mod._complete_background_job(
        "user-1",
        active_job,
        "msg-source",
        _skill(),
        ExecuteResult(kind="text", text="done"),
    )

    assert reply_text.await_count == 2
    assert store.session.phase == ConversationPhase.running_job
    assert store.session.completed is False
    assert store.session.completed_result is None
    assert store.session.active_job.status == "running"
    assert store.session.active_job.job_id == "backend-job"
    assert store.session.active_job.last_observation == {
        "reply_failed": True,
        "result_kind": "text",
    }
    record_metric.assert_any_call(
        "delayed_reply_failure",
        stage="send_result",
        skill_name="xd-poster-gen",
        job_status="running",
        result_kind="text",
        reply_channel="text",
        user_key="u_c6c289e49e9c",
    )


@pytest.mark.asyncio
async def test_complete_background_job_marks_http_skill_failed_when_result_reply_fails(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("running").model_copy(update={"skill_name": "frame-bg-remover"})
    store = _FakeStore(_session(active_job))
    reply_text = AsyncMock(return_value=False)
    record_metric = Mock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())
    monkeypatch.setattr(main_mod, "record_metric", record_metric)

    await main_mod._complete_background_job(
        "user-1",
        active_job,
        "msg-source",
        _http_skill(),
        ExecuteResult(kind="text", text="done"),
    )

    assert reply_text.await_count == 2
    assert store.session.phase == ConversationPhase.failed
    assert store.session.completed is False
    assert store.session.completed_result is None
    assert store.session.active_job.status == "failed"
    assert store.session.active_job.last_observation == {
        "reply_failed": True,
        "result_kind": "text",
    }


@pytest.mark.asyncio
async def test_send_execute_result_retry_does_not_upload_binary_twice(monkeypatch):
    from src import main as main_mod

    upload_image = AsyncMock(return_value="img-key")
    reply_image = AsyncMock(side_effect=[False, True])

    monkeypatch.setattr(main_mod, "upload_image", upload_image)
    monkeypatch.setattr(main_mod, "reply_image", reply_image)

    sent = await main_mod._send_execute_result_with_retry(
        "msg-source",
        ExecuteResult(kind="binary", content_bytes=b"png"),
        _skill(),
    )

    assert sent is True
    upload_image.assert_awaited_once()
    assert reply_image.await_count == 2
    assert [call.args[2] for call in reply_image.await_args_list] == ["img-key", "img-key"]


@pytest.mark.asyncio
async def test_send_execute_result_retry_does_not_download_url_twice(monkeypatch):
    from src import main as main_mod

    download_url = AsyncMock(return_value=b"png")
    upload_image = AsyncMock(return_value="img-key")
    reply_image = AsyncMock(side_effect=[False, True])

    monkeypatch.setattr(main_mod, "download_url", download_url)
    monkeypatch.setattr(main_mod, "upload_image", upload_image)
    monkeypatch.setattr(main_mod, "reply_image", reply_image)

    sent = await main_mod._send_execute_result_with_retry(
        "msg-source",
        ExecuteResult(kind="url", result_url="https://example.test/result.png"),
        _skill(),
    )

    assert sent is True
    download_url.assert_awaited_once_with("https://example.test/result.png")
    upload_image.assert_awaited_once()
    assert reply_image.await_count == 2


@pytest.mark.asyncio
async def test_background_poll_final_send_waits_for_user_lock_and_honors_cancel(monkeypatch):
    from src import main as main_mod

    user_id = "race-user"
    main_mod._user_locks.pop(user_id, None)
    active_job = _active_job("running")
    store = _FakeStore(_session(active_job))
    polled = asyncio.Event()
    send_started = asyncio.Event()

    async def poll_existing_job(*_args):
        polled.set()
        return ExecuteResult(kind="text", text="late result")

    async def send_execute_result(*_args):
        send_started.set()
        return True

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "poll_existing_job", poll_existing_job)
    monkeypatch.setattr(main_mod, "_send_execute_result", send_execute_result)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})
    monkeypatch.setattr(main_mod, "_maybe_save_cached_step1", AsyncMock())

    lock = main_mod._get_user_lock(user_id)
    async with lock:
        task = asyncio.create_task(main_mod._background_poll(user_id, active_job, "msg-source"))
        await asyncio.wait_for(polled.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not send_started.is_set()

        cancelled_session = store.session.model_copy(deep=True)
        cancelled_session.active_job = active_job.model_copy(update={
            "status": "cancelled",
            "cancelled_locally": True,
        })
        cancelled_session.phase = ConversationPhase.completed
        cancelled_session.completed = True
        await store.save_conversation(user_id, cancelled_session)

    await asyncio.wait_for(task, timeout=1)

    assert not send_started.is_set()
    assert store.session.active_job.cancelled_locally is True


@pytest.mark.asyncio
async def test_running_job_chitchat_uses_chitchat_reply(monkeypatch):
    from src import main as main_mod

    session = _session(_active_job("running"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)

    await main_mod._agentic_loop("谢谢", session, "user-1", "msg-current")

    sent = reply_text.await_args_list[-1].args[2]
    assert "我还在当前任务里" in sent
    assert "继续帮你等待" not in sent
    start_worker.assert_called_once()


@pytest.mark.asyncio
async def test_timeout_running_job_does_not_restart_worker(monkeypatch):
    from src import main as main_mod

    session = _session(_active_job("timeout"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)

    await main_mod._agentic_loop("还没好吗？", session, "user-1", "msg-current")

    start_worker.assert_not_called()
    sent = reply_text.await_args_list[-1].args[2]
    assert "生成还没完成" in sent
    assert "1. 继续等待" in sent


@pytest.mark.asyncio
async def test_timeout_option_1_continue_wait_restarts_worker(monkeypatch):
    from src import main as main_mod

    session = _session(_active_job("timeout"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)

    await main_mod._agentic_loop("1", session, "user-1", "msg-current")

    sent = reply_text.await_args_list[-1].args[2]
    assert "继续帮你等待" in sent
    assert store.session.phase == ConversationPhase.running_job
    assert store.session.active_job.status == "running"
    start_worker.assert_called_once()


@pytest.mark.asyncio
async def test_timeout_option_2_retry_resubmits_active_payload(monkeypatch):
    from src import main as main_mod

    new_job = _active_job("submitted").model_copy(update={"source_message_id": "msg-current"})
    session = _session(_active_job("timeout"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    begin_submit = AsyncMock(return_value=SimpleNamespace(active_job=new_job))
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_begin_submit_job", begin_submit)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)
    monkeypatch.setattr(main_mod, "_maybe_inject_cached_step1", AsyncMock(side_effect=lambda payload, _user_id: payload))
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})

    await main_mod._agentic_loop("2", session, "user-1", "msg-current")

    assert begin_submit.await_args.args[4] == {"topic": "coffee"}
    assert begin_submit.await_args.args[5] == "retry"
    sent = reply_text.await_args_list[-1].args[2]
    assert "已开始重新生成" in sent
    start_worker.assert_called_once_with("user-1", new_job, "msg-current")


@pytest.mark.asyncio
async def test_timeout_option_3_modify_moves_back_to_collecting(monkeypatch):
    from src import main as main_mod

    session = _session(_active_job("timeout"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)

    await main_mod._agentic_loop("3", session, "user-1", "msg-current")

    sent = reply_text.await_args_list[-1].args[2]
    assert "想修改哪里" in sent
    assert store.session.phase == ConversationPhase.collecting
    assert store.session.completed is False
    assert store.session.active_job is None
    start_worker.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_option_4_cancel_marks_local_cancel(monkeypatch):
    from src import main as main_mod

    session = _session(_active_job("timeout"))
    store = _FakeStore(session)
    reply_text = AsyncMock()
    start_worker = Mock(return_value=True)

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_start_background_worker", start_worker)

    await main_mod._agentic_loop("4", session, "user-1", "msg-current")

    sent = reply_text.await_args_list[-1].args[2]
    assert sent == ResponseComposer().local_cancel()
    assert store.session.phase == ConversationPhase.completed
    assert store.session.completed is True
    assert store.session.active_job.cancelled_locally is True
    assert store.session.active_job.status == "cancelled"
    start_worker.assert_not_called()


@pytest.mark.asyncio
async def test_retry_uses_completed_result_submitted_payload(monkeypatch):
    from src import main as main_mod

    active_job = _active_job("submitted")
    session = ConversationSession(
        phase=ConversationPhase.completed,
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"topic": "modified"},
        completed=True,
        completed_result=CompletedResult(
            submitted_payload={"topic": "original"},
            artifacts={},
            completed_at=100.0,
            source_message_id="msg-old",
        ),
    )
    store = _FakeStore(session)
    reply_text = AsyncMock()
    begin_submit = AsyncMock(return_value=SimpleNamespace(active_job=active_job))

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "_begin_submit_job", begin_submit)
    monkeypatch.setattr(main_mod, "_start_background_worker", Mock(return_value=True))
    monkeypatch.setattr(main_mod, "_maybe_inject_cached_step1", AsyncMock(side_effect=lambda payload, _user_id: payload))
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _skill()})

    await main_mod._agentic_loop("再来一张", session, "user-1", "msg-current")

    assert begin_submit.await_args.args[4] == {"topic": "original"}
