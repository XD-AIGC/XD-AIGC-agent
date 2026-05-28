"""E2E 流程测试 — mock 飞书 / LLM / toolbox，测端到端业务流。

入口：_process_locked(message_id, msg_type, content, user_id)
- 跳过 lark dispatcher 的 data 对象解析
- 直接驱动 _agentic_loop / _execute_image_skill 等业务逻辑

mock 策略：
- LLM (router_decide / skill_decide) → 返回预设 BotAction
- Skill execute → 返回 ExecuteResult
- reply_text / reply_image / upload_image / download_url → 记录调用
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import src.main as main_mod
from src.orchestrator.schema import BotAction, UserSession
from src.skill.executor import ExecuteResult
from src.skill.schema import PollBackend, Skill, SkillOutput, SkillParam


# ---------- 工具：构造干净 session + mock 集 ----------

@pytest.fixture(autouse=True)
def _rebind_redis_clients_to_current_loop():
    """模块级 _store / _step1_cache 的 aioredis client 绑死了首次创建的 loop。
    每个 test 重建一遍让它绑当前 loop，避免 'Future attached to different loop'。"""
    import redis.asyncio as aioredis
    from src.config import REDIS_URL
    main_mod._store._redis = aioredis.from_url(REDIS_URL)
    main_mod._step1_cache._redis = aioredis.from_url(REDIS_URL)
    yield


@pytest.fixture
async def clean_session():
    """每个 e2e 用例隔离 user_id + 清干净 session。"""
    user_id = f"e2e-{asyncio.get_event_loop().time()}"
    await main_mod._store.clear(user_id)
    yield user_id
    await main_mod._store.clear(user_id)


@pytest.fixture
def mock_io():
    """把所有外部 I/O 都 mock 掉，留下断言入口。"""
    with patch.object(main_mod, "reply_text", new=AsyncMock()) as rt, \
         patch.object(main_mod, "reply_image", new=AsyncMock()) as ri, \
         patch.object(main_mod, "upload_image", new=AsyncMock(return_value="img_key_xx")) as ui, \
         patch.object(main_mod, "download_url", new=AsyncMock(return_value=b"img_bytes")) as du, \
         patch.object(main_mod, "execute", new=AsyncMock()) as ex, \
         patch.object(main_mod, "submit_poll_job", new=AsyncMock(return_value="backend-job")) as sp, \
         patch.object(main_mod, "poll_existing_job", new=AsyncMock()) as pe, \
         patch.object(main_mod, "router_decide", new=AsyncMock()) as rd, \
         patch.object(main_mod, "skill_decide", new=AsyncMock()) as sd, \
         patch.object(main_mod, "_maybe_save_cached_step1", new=AsyncMock()) as sc, \
         patch.object(main_mod, "get_registry", new=lambda: _fake_registry()):
        yield {"reply_text": rt, "reply_image": ri, "upload_image": ui,
               "download_url": du, "execute": ex,
               "submit_poll_job": sp, "poll_existing_job": pe,
               "router_decide": rd, "skill_decide": sd,
               "save_cached_step1": sc}


def _fake_registry() -> dict[str, Skill]:
    skill = Skill(
        name="xd-poster-gen",
        description="poster",
        api=PollBackend(
            type="poll",
            submit_path="/api/generate-v2",
            poll_path_template="/api/poll-v2/{job_id}",
        ),
        params=[
            SkillParam(
                name="compositionType",
                type="enum",
                required=False,
                values=["default", "center", "diagonal"],
                prompt_to_user="排版构图",
            )
        ],
        output=SkillOutput(type="image_url", display_as="feishu_image"),
        system_prompt_core="core",
    )
    return {"xd-poster-gen": skill}


def _text_msg(text: str) -> dict:
    return {"text": text}


async def _drain_background_tasks() -> None:
    tasks = list(main_mod._background_tasks.values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


# ---------- 场景 1：Router → Skill → submit → 出图（happy path）----------

@pytest.mark.asyncio
async def test_e2e_happy_path_submit_to_image(clean_session, mock_io):
    uid = clean_session
    mock_io["router_decide"].return_value = BotAction(
        action="select_skill", skill_name="xd-poster-gen"
    )
    mock_io["skill_decide"].return_value = BotAction(
        action="submit",
        submit_payload={"characters": ["harry"], "actionDesc": "踢球", "compositionType": "default"},
    )
    mock_io["poll_existing_job"].return_value = ExecuteResult(
        kind="url",
        result_url="https://example.com/img.png",
        metadata={"intermediateImages": {"characterActionFileId": "fid_step1_xxx"}},
    )

    await main_mod._process_locked("msg_1", "text", _text_msg("画一张哈瑞踢球的海报"), uid)
    await _drain_background_tasks()

    assert mock_io["router_decide"].call_count == 1
    assert mock_io["skill_decide"].call_count == 1
    mock_io["execute"].assert_not_called()
    mock_io["submit_poll_job"].assert_called_once()
    mock_io["poll_existing_job"].assert_called_once()
    mock_io["download_url"].assert_called_once_with("https://example.com/img.png")
    mock_io["upload_image"].assert_called_once()
    mock_io["reply_image"].assert_called_once()
    sess = await main_mod._store.get(uid)
    assert sess.completed is True
    assert sess.mode == "skill"
    assert sess.skill_name == "xd-poster-gen"


# ---------- 场景 2：Retry 快路径（不进 LLM）----------

@pytest.mark.asyncio
async def test_e2e_retry_fast_path_skips_llm(clean_session, mock_io):
    uid = clean_session
    await main_mod._store.save(uid, UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
        completed=True,
    ))
    mock_io["poll_existing_job"].return_value = ExecuteResult(
        kind="url", result_url="https://example.com/2.png", metadata={}
    )

    await main_mod._process_locked("msg_retry", "text", _text_msg("再来一张"), uid)
    await _drain_background_tasks()

    mock_io["router_decide"].assert_not_called()
    mock_io["skill_decide"].assert_not_called()
    mock_io["execute"].assert_not_called()
    mock_io["submit_poll_job"].assert_called_once()
    mock_io["poll_existing_job"].assert_called_once()
    mock_io["reply_image"].assert_called_once()


# ---------- 场景 3：Enum 兜底（ask_param compositionType 自动追加选项）----------

@pytest.mark.asyncio
async def test_e2e_enum_options_appended_to_ask_param(clean_session, mock_io):
    uid = clean_session
    await main_mod._store.save(uid, UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"]},
    ))
    mock_io["skill_decide"].return_value = BotAction(
        action="ask_param",
        param_name="compositionType",
        message="选个构图吧",
    )

    await main_mod._process_locked("msg_ask", "text", _text_msg("继续"), uid)

    mock_io["reply_text"].assert_called_once()
    sent_msg = mock_io["reply_text"].call_args[0][2]
    assert "选个构图吧" in sent_msg
    assert "📋" in sent_msg
    assert "排版构图 可选值" in sent_msg
    assert "default" in sent_msg
    assert "diagonal" in sent_msg


# ---------- 场景 4：LLM 失败兜底 ----------

@pytest.mark.asyncio
async def test_e2e_llm_failure_friendly_reply(clean_session, mock_io):
    uid = clean_session
    mock_io["router_decide"].side_effect = ConnectionError("LLM 挂了")

    await main_mod._process_locked("msg_fail", "text", _text_msg("hi"), uid)

    mock_io["reply_text"].assert_called_once()
    sent_msg = mock_io["reply_text"].call_args[0][2]
    assert "AI 暂时不可用" in sent_msg
    assert "ConnectionError" in sent_msg


# ---------- 场景 5：submit 失败保留 session ----------

@pytest.mark.asyncio
async def test_e2e_submit_failure_preserves_session(clean_session, mock_io):
    uid = clean_session
    from src.skill.executor import SkillExecutionError

    await main_mod._store.save(uid, UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
    ))
    mock_io["skill_decide"].return_value = BotAction(
        action="submit",
        submit_payload={"characters": ["harry"], "actionDesc": "踢球"},
    )
    mock_io["poll_existing_job"].side_effect = SkillExecutionError("任务 v2_xxx 轮询超时(300s)")

    await main_mod._process_locked("msg_submit_fail", "text", _text_msg("提交"), uid)
    await _drain_background_tasks()

    sent_msgs = [c[0][2] for c in mock_io["reply_text"].call_args_list]
    assert any("生成还没完成" in m and "继续等待" in m for m in sent_msgs)
    sess = await main_mod._store.get(uid)
    assert sess.skill_name == "xd-poster-gen"
    assert sess.collected_params.get("characters") == ["harry"]


# ---------- 场景 6：Per-user lock 串行化 ----------

class _FakeData:
    """模拟 lark dispatcher 传给 on_message 的 data shape。"""
    class _SId:
        def __init__(self, oid): self.open_id = oid

    class _Sender:
        def __init__(self, oid): self.sender_id = _FakeData._SId(oid)

    class _Msg:
        def __init__(self, mid, mtype, content):
            import json
            self.message_id = mid
            self.message_type = mtype
            self.chat_id = "test_chat"
            self.chat_type = "p2p"
            self.content = json.dumps(content)

    class _Event:
        def __init__(self, mid, mtype, content, uid):
            self.message = _FakeData._Msg(mid, mtype, content)
            self.sender = _FakeData._Sender(uid)

    def __init__(self, mid, mtype, content, uid):
        self.event = self._Event(mid, mtype, content, uid)


@pytest.mark.asyncio
async def test_e2e_per_user_lock_serializes(clean_session, mock_io):
    uid = clean_session
    call_order: list[str] = []

    async def slow_router(*args, **kwargs):
        call_order.append("router_start")
        await asyncio.sleep(0.1)
        call_order.append("router_end")
        return BotAction(action="reply", message="hi")

    mock_io["router_decide"].side_effect = slow_router

    await asyncio.gather(
        main_mod._process(_FakeData("msg_a", "text", _text_msg("a"), uid)),
        main_mod._process(_FakeData("msg_b", "text", _text_msg("b"), uid)),
    )

    assert call_order == ["router_start", "router_end", "router_start", "router_end"]
