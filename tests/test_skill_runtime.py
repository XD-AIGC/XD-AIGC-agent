import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError


def _fake_skill():
    from src.skill.schema import HttpBackend, Skill, SkillOutput

    return Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )


def _option_set():
    from src.conversation.options import OptionItem, OptionSet

    return OptionSet(
        id="ratio",
        param_name="ratio",
        source="enum",
        items=[OptionItem(index=1, label="2:3", value="2:3", param_name="ratio")],
    )


def test_skill_runtime_action_rejects_router_only_actions():
    from src.skill.runtime import SkillRuntimeAction

    for action in ("select_skill", "out_of_scope"):
        with pytest.raises(ValidationError):
            SkillRuntimeAction(action=action)


def test_skill_runtime_action_accepts_complete_and_exit_skill():
    from src.skill.runtime import SkillRuntimeAction

    complete = SkillRuntimeAction(action="complete", message="已完成")
    exit_skill = SkillRuntimeAction(action="exit_skill", message="好的")

    assert complete.action == "complete"
    assert exit_skill.action == "exit_skill"


def test_skill_runtime_action_rejects_unknown_action():
    from src.skill.runtime import SkillRuntimeAction

    with pytest.raises(ValidationError):
        SkillRuntimeAction(action="do_evil")


def test_skill_runtime_wire_action_decodes_json_entries():
    from src.orchestrator.schema import JsonEntry
    from src.skill.runtime import SkillRuntimeWireAction

    wire = SkillRuntimeWireAction(
        action="call_skill_action",
        action_name="generate",
        action_params=[
            JsonEntry(key="json", value_json='{"characters": ["annie"], "ratio": "3:2"}'),
        ],
        updated_params=[
            JsonEntry(key="characters", value_json='["annie"]'),
            JsonEntry(key="ratio", value_json='"3:2"'),
        ],
    )

    action = wire.to_runtime_action()

    assert action.action == "call_skill_action"
    assert action.action_params == {"json": {"characters": ["annie"], "ratio": "3:2"}}
    assert action.updated_params == {"characters": ["annie"], "ratio": "3:2"}


@pytest.mark.asyncio
async def test_skill_decide_uses_skill_runtime_action_schema(monkeypatch):
    import json as _json
    from src.orchestrator import llm as llm_mod
    from src.orchestrator.schema import UserSession
    from src.skill.runtime import SkillRuntimeAction, SkillRuntimeWireAction

    captured = {}
    _wire = SkillRuntimeWireAction(action="reply", message="ok")

    class _Message:
        content = _json.dumps(_wire.model_dump(exclude_none=True))

    class _Choice:
        message = _Message()

    class _Completions:
        async def create(self, **kwargs):
            captured["response_format"] = kwargs.get("response_format")
            return type("Resp", (), {"choices": [_Choice()]})()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(llm_mod, "_client", _Client())

    action = await llm_mod.skill_decide("继续", UserSession(mode="skill"), _fake_skill())

    assert captured["response_format"] == {"type": "json_object"}
    assert isinstance(action, SkillRuntimeAction)


@pytest.mark.asyncio
async def test_skill_decide_dedupes_current_message_with_v2_history(monkeypatch):
    from src.conversation.session import ConversationSession, Message
    from src.orchestrator import llm as llm_mod
    from src.skill.runtime import SkillRuntimeWireAction

    captured = {}
    _wire = SkillRuntimeWireAction(action="reply", message="ok")

    class _Message:
        content = json.dumps(_wire.model_dump(exclude_none=True))

    class _Choice:
        message = _Message()

    class _Completions:
        async def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return type("Resp", (), {"choices": [_Choice()]})()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(llm_mod, "_client", _Client())
    session = ConversationSession(
        skill_name="xd-town-studio",
        chat_history=[Message(role="user", content="继续")],
    )

    await llm_mod.skill_decide("继续", session, _fake_skill())

    user_messages = [msg for msg in captured["messages"] if msg["role"] == "user"]
    assert [msg["content"] for msg in user_messages] == ["继续"]


@pytest.mark.asyncio
async def test_complete_action_retains_skill_context(monkeypatch):
    from src import main as main_mod
    from src.conversation.session import ConversationPhase, ConversationSession
    from src.skill.runtime import SkillRuntimeAction

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session.model_copy(deep=True))

    store = FakeStore()
    reply_text = AsyncMock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod.time, "time", lambda: 1234.0)
    monkeypatch.setattr(
        main_mod,
        "skill_decide",
        AsyncMock(return_value=SkillRuntimeAction(action="complete", message="已完成")),
    )
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _fake_skill()})

    session = ConversationSession(
        phase=ConversationPhase.collecting,
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"topic": "coffee"},
        last_options=_option_set(),
    )

    await main_mod._agentic_loop("完成了", session, "user-1", "msg-1")

    assert reply_text.call_args.args[2] == "已完成"
    assert store.saved[0] == "user-1"
    saved = store.saved[1]
    assert saved.phase == ConversationPhase.completed
    assert saved.completed is True
    assert saved.skill_name == "xd-poster-gen"
    assert saved.collected_params == {"topic": "coffee"}
    assert saved.last_options is None
    assert saved.completed_result is not None
    assert saved.completed_result.submitted_payload == {"topic": "coffee"}
    assert saved.completed_result.artifacts == {}
    assert saved.completed_result.completed_at == 1234.0
    assert saved.completed_result.source_message_id == "msg-1"


@pytest.mark.asyncio
async def test_exit_skill_action_clears_skill_context(monkeypatch):
    from src import main as main_mod
    from src.conversation.session import ConversationPhase, ConversationSession, Message
    from src.skill.runtime import SkillRuntimeAction

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session.model_copy(deep=True))

        async def clear(self, user_id):
            raise AssertionError("exit_skill must preserve chat_history")

    store = FakeStore()
    reply_text = AsyncMock()

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(
        main_mod,
        "skill_decide",
        AsyncMock(return_value=SkillRuntimeAction(action="exit_skill", message="已退出")),
    )
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _fake_skill()})

    session = ConversationSession(
        phase=ConversationPhase.collecting,
        mode="skill",
        skill_name="xd-poster-gen",
        initial_intent="做海报",
        collected_params={"topic": "coffee"},
        pending_param="topic",
        loaded_resources={"lookup_options": "cached"},
        last_options=_option_set(),
        artifacts={"file_id": "6a"},
        chat_history=[Message(role="assistant", content="请提供主题")],
    )

    await main_mod._agentic_loop("不做了", session, "user-1", "msg-1")

    assert reply_text.call_args.args[2] == "已退出"
    assert store.saved[0] == "user-1"
    saved = store.saved[1]
    assert saved.phase == ConversationPhase.idle
    assert saved.mode == "router"
    assert saved.completed is False
    assert saved.skill_name is None
    assert saved.initial_intent is None
    assert saved.collected_params == {}
    assert saved.pending_param is None
    assert saved.loaded_resources == {}
    assert saved.last_options is None
    assert saved.artifacts == {}
    assert [msg.content for msg in saved.chat_history] == ["请提供主题", "不做了", "已退出"]


@pytest.mark.asyncio
async def test_skill_runtime_action_log_uses_session_skill_name(monkeypatch, caplog):
    import logging

    from src import main as main_mod
    from src.conversation.session import ConversationPhase, ConversationSession
    from src.skill.runtime import SkillRuntimeAction

    class FakeStore:
        async def save(self, user_id, session):
            pass

    monkeypatch.setattr(main_mod, "_store", FakeStore())
    monkeypatch.setattr(main_mod, "reply_text", AsyncMock())
    monkeypatch.setattr(
        main_mod,
        "skill_decide",
        AsyncMock(return_value=SkillRuntimeAction(action="reply", message="ok")),
    )
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": _fake_skill()})
    caplog.set_level(logging.INFO, logger=main_mod.__name__)

    session = ConversationSession(
        phase=ConversationPhase.collecting,
        mode="skill",
        skill_name="xd-poster-gen",
    )

    await main_mod._agentic_loop("继续", session, "user-1", "msg-1")

    assert "[ACT mode=skill] reply skill=xd-poster-gen" in caplog.text
