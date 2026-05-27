from unittest.mock import AsyncMock

import pytest

from src.main import (
    _strip_mentions,
    _normalize_message,
    _load_lazy_resource,
    _is_retry,
    _is_capability_question,
    _is_completed_skill_continuation,
    _resolve_numbered_character_reply,
)
from src.conversation.options import OptionItem, OptionSet
from src.skill.schema import Skill, HttpBackend, SkillOutput


def test_strip_single_mention():
    assert _strip_mentions("@_user_1 帮我去白底") == "帮我去白底"


def test_strip_multiple_mentions():
    assert _strip_mentions("@_user_1 @_user_2 抠个图") == "抠个图"


def test_strip_mentions_no_mention():
    assert _strip_mentions("帮我去白底") == "帮我去白底"


def test_strip_mentions_only_mention():
    assert _strip_mentions("@_user_1") == ""


def test_strip_mentions_trailing_whitespace():
    assert _strip_mentions("  @_user_1  你好  ") == "你好"


# ---- _normalize_message ----

def test_normalize_text():
    assert _normalize_message("text", {"text": "你好"}) == ("你好", None)


def test_normalize_text_with_mention():
    assert _normalize_message("text", {"text": "@_user_1 你好"}) == ("你好", None)


def test_normalize_image():
    assert _normalize_message("image", {"image_key": "img_xxx"}) == ("", "img_xxx")


def test_normalize_post_text_and_image():
    content = {
        "title": "",
        "content": [
            [
                {"tag": "at", "user_id": "@_user_1", "user_name": "AIGC bot"},
                {"tag": "text", "text": "  帮我去除背景"},
            ],
            [{"tag": "img", "image_key": "img_v3_xxx"}],
        ],
    }
    text, image_key = _normalize_message("post", content)
    assert text == "帮我去除背景"
    assert image_key == "img_v3_xxx"


def test_normalize_post_text_only():
    content = {"content": [[{"tag": "at", "user_id": "@_user_1"}, {"tag": "text", "text": " 抠图"}]]}
    assert _normalize_message("post", content) == ("抠图", None)


def test_normalize_post_image_only():
    content = {"content": [[{"tag": "img", "image_key": "img_x"}]]}
    assert _normalize_message("post", content) == ("", "img_x")


def test_normalize_post_first_image_wins():
    content = {
        "content": [
            [{"tag": "img", "image_key": "first"}],
            [{"tag": "img", "image_key": "second"}],
        ]
    }
    _, key = _normalize_message("post", content)
    assert key == "first"


# ---- _load_lazy_resource ----

from src.main import LazyResourceError


def _make_skill_with_lazy(lazy_map: dict) -> Skill:
    return Skill(
        name="t", description="d",
        api=HttpBackend(endpoint_path="/x"),
        params=[],
        output=SkillOutput(type="image_binary", display_as="feishu_image"),
        lazy_resources=lazy_map,
    )


async def test_lazy_resource_missing_config():
    s = _make_skill_with_lazy({})
    with pytest.raises(LazyResourceError, match="未在 manifest"):
        await _load_lazy_resource(s, "lookup_characters")


async def test_lazy_resource_file_not_exist():
    s = _make_skill_with_lazy({"lookup_characters": "non/existent/path.tsv"})
    with pytest.raises(LazyResourceError, match="不存在"):
        await _load_lazy_resource(s, "lookup_characters")


async def test_lazy_resource_loads_real_file(tmp_path):
    # registry 现在传绝对路径给 skill.lazy_resources，agent 直接 read
    demo = tmp_path / "demo.tsv"
    demo.write_text("a\tb\nc\td", encoding="utf-8")
    s = _make_skill_with_lazy({"lookup_characters": str(demo)})
    assert await _load_lazy_resource(s, "lookup_characters") == "a\tb\nc\td"


async def test_lazy_resource_http_type_calls_url(monkeypatch):
    """HTTP 类型的 lazy_resource：调 _fetch_http_resource，结果返回给调用方。"""
    from src.skill.schema import HttpResource
    from src import main as main_mod

    captured = {}

    async def fake_fetch(res):
        captured["url"] = res.url
        return '[{"key":"aiai","name":"皑皑"}]'

    monkeypatch.setattr(main_mod, "_fetch_http_resource", fake_fetch)
    http_res = HttpResource(type="http", url="http://localhost:8090/api/characters", cache_ttl_sec=0)
    s = _make_skill_with_lazy({"lookup_characters": http_res})
    result = await _load_lazy_resource(s, "lookup_characters")
    assert captured["url"] == "http://localhost:8090/api/characters"
    assert "皑皑" in result


def test_is_retry_exact_phrases():
    for p in ["再来一张", "再来", "再生成", "again", "Again", "重新生成"]:
        assert _is_retry(p), f"{p} should be retry"


def test_is_retry_with_punctuation():
    assert _is_retry("再来一张！")
    assert _is_retry("再来。")
    assert _is_retry("再来 ")


def test_is_retry_negative():
    for p in ["再来一张，但是改成竖版", "换标题", "好的", "不调整", ""]:
        assert not _is_retry(p), f"{p} should NOT be retry"


def test_is_capability_question():
    positives = ["你能做什么？", "好的，你还能做其它什么事情?", "还有哪些功能", "还可以做啥"]
    for p in positives:
        assert _is_capability_question(p), f"{p} should be capability question"


def test_is_capability_question_negative():
    negatives = ["还能做一张吗", "再来一张", "换成横版", "好的"]
    for p in negatives:
        assert not _is_capability_question(p), f"{p} should NOT be capability question"


def test_is_completed_skill_continuation():
    positives = ["再来一张", "换成横版", "主标题改成生活", "比例 3:2", "调整一下颜色"]
    for p in positives:
        assert _is_completed_skill_continuation(p), f"{p} should continue completed skill"


def test_is_completed_skill_continuation_negative():
    negatives = ["hello, 今天是周几啊", "好的", "谢谢", "你能做什么"]
    for p in negatives:
        assert not _is_completed_skill_continuation(p), f"{p} should NOT continue completed skill"


# --- enum options block ---
from src.main import _enum_options_block
from src.skill.schema import SkillParam


def _skill_with_enum(values: list[str], name: str = "fmt") -> Skill:
    return Skill(
        name="test",
        description="t",
        api=HttpBackend(endpoint_path="/x"),
        params=[SkillParam(name=name, type="enum", values=values, required=True, prompt_to_user="格式")],
        output=SkillOutput(type="image_binary", display_as="feishu_image"),
    )


def test_enum_options_block_appends():
    s = _skill_with_enum(["png", "jpg", "webp"])
    block = _enum_options_block(s, "fmt")
    assert "📋 格式 可选值" in block
    assert "- png" in block and "- jpg" in block and "- webp" in block


def test_enum_options_block_skips_non_enum():
    s = Skill(
        name="t", description="t",
        api=HttpBackend(endpoint_path="/x"),
        params=[SkillParam(name="txt", type="text", required=True, prompt_to_user="自由文本")],
        output=SkillOutput(type="text", display_as="feishu_text"),
    )
    assert _enum_options_block(s, "txt") == ""


def test_enum_options_block_unknown_param():
    s = _skill_with_enum(["a", "b"])
    assert _enum_options_block(s, "no_such_param") == ""


def test_enum_options_block_none_inputs():
    assert _enum_options_block(None, "fmt") == ""
    assert _enum_options_block(_skill_with_enum(["a"]), None) == ""


# --- friendly error mapping ---
from src.main import _friendly_skill_error
from src.skill.executor import SkillExecutionError


def test_friendly_error_timeout():
    msg = _friendly_skill_error(SkillExecutionError("任务 v2_xxx 轮询超时（300s）"))
    assert "⏰" in msg and "超时" in msg


def test_friendly_error_timeout_english():
    msg = _friendly_skill_error(Exception("connect timeout"))
    assert "⏰" in msg


def test_friendly_error_invalid_response():
    msg = _friendly_skill_error(SkillExecutionError("submit 成功但缺 job_id 字段 'jobId'"))
    assert "意外格式" in msg


def test_friendly_error_failed():
    msg = _friendly_skill_error(SkillExecutionError("任务失败：bad params"))
    assert "❌" in msg or "失败" in msg


def test_friendly_error_generic():
    msg = _friendly_skill_error(ConnectionError("Network unreachable"))
    assert "ConnectionError" in msg and "稍后再试" in msg


# --- chat history ---
from src.main import _append_history, _HISTORY_MAX_TURNS, _HISTORY_MAX_CHAR
from src.orchestrator.schema import UserSession as _US


def test_append_history_basic():
    s = _US()
    _append_history(s, "user", "hi")
    _append_history(s, "assistant", "hello")
    assert s.chat_history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_append_history_truncates_long_content():
    s = _US()
    long = "x" * (_HISTORY_MAX_CHAR + 100)
    _append_history(s, "assistant", long)
    assert s.chat_history[0]["content"].endswith("...(truncated)")
    assert len(s.chat_history[0]["content"]) <= _HISTORY_MAX_CHAR + 20


def test_append_history_rolling_window():
    s = _US()
    for i in range(_HISTORY_MAX_TURNS + 5):
        _append_history(s, "user", f"msg{i}")
    assert len(s.chat_history) == _HISTORY_MAX_TURNS
    # 最早 5 条被丢
    assert s.chat_history[0]["content"] == "msg5"
    assert s.chat_history[-1]["content"] == f"msg{_HISTORY_MAX_TURNS + 4}"


def test_append_history_empty_content_noop():
    s = _US()
    _append_history(s, "user", "")
    assert s.chat_history == []


def test_resolve_numbered_character_reply_maps_last_assistant_option():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        loaded_resources={
            "lookup_characters": (
                '[{"key":"aiai","name":"皑皑"},'
                '{"key":"albert","name":"阿尔伯特二世"},'
                '{"key":"andrew","name":"安德鲁"}]'
            )
        },
    )
    _append_history(s, "assistant", "1. 皑皑 (aiai)\n2. 阿尔伯特二世 (albert)\n3. 安德鲁 (andrew)")

    status, resolved = _resolve_numbered_character_reply("3", s)

    assert status == "resolved"
    assert s.collected_params["characters"] == ["andrew"]
    assert "编号 3" in resolved
    assert "andrew" in resolved


def test_resolve_numbered_character_reply_uses_name_when_key_missing():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        loaded_resources={'lookup_characters': '[{"key":"aiai","name":"皑皑"}]'},
    )
    _append_history(s, "assistant", "1. 皑皑 — 黑色短碎发+工装裤")

    status, _ = _resolve_numbered_character_reply("选1", s)

    assert status == "resolved"
    assert s.collected_params["characters"] == ["aiai"]


def test_resolve_numbered_character_reply_rejects_out_of_range_without_llm():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        loaded_resources={'lookup_characters': '[{"key":"aiai","name":"皑皑"},{"key":"andrew","name":"安德鲁"}]'},
    )
    _append_history(s, "assistant", "1. 皑皑 (aiai)\n2. 安德鲁 (andrew)")

    status, message = _resolve_numbered_character_reply("33", s)

    assert status == "error"
    assert "编号 33 超出范围" in message
    assert "1-2" in message


def test_resolve_numbered_character_reply_ignores_ratio_options():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        loaded_resources={'lookup_characters': '[{"key":"aiai","name":"皑皑"}]'},
    )
    _append_history(s, "assistant", "1. 2:3 竖版海报\n2. 9:16 手机竖版\n3. 1:1 方图\n4. 3:2 横版")

    assert _resolve_numbered_character_reply("4", s) is None
    assert "characters" not in s.collected_params


def test_resolve_numbered_character_reply_ignores_category_options():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        loaded_resources={'lookup_characters': '[{"key":"aiai","name":"皑皑"}]'},
    )
    _append_history(s, "assistant", "1. 赛季更新\n2. NPC角色\n3. NPC动物")

    assert _resolve_numbered_character_reply("1", s) is None
    assert "characters" not in s.collected_params


def test_resolve_numbered_character_reply_uses_structured_last_options_first():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        pending_param="ratio",
        last_options=OptionSet(
            id="ratio-1",
            param_name="ratio",
            source="enum",
            created_at=100.0,
            ttl_sec=9999999999,
            items=[
                OptionItem(index=1, label="2:3 竖版", value="2:3", param_name="ratio"),
                OptionItem(index=2, label="3:2 横版", value="3:2", param_name="ratio"),
            ],
        ).model_dump(),
    )
    _append_history(s, "assistant", "1. 皑皑 (aiai)\n2. 安德鲁 (andrew)")

    status, resolved = _resolve_numbered_character_reply("2", s)

    assert status == "resolved"
    assert s.collected_params["ratio"] == "3:2"
    assert s.pending_param is None
    assert s.last_options is None
    assert "ratio" in resolved


def test_resolve_numbered_character_reply_does_not_reuse_consumed_options_next_turn():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        pending_param="ratio",
        last_options=OptionSet(
            id="ratio-1",
            param_name="ratio",
            source="enum",
            created_at=100.0,
            ttl_sec=9999999999,
            items=[
                OptionItem(index=1, label="2:3 竖版", value="2:3", param_name="ratio"),
                OptionItem(index=2, label="3:2 横版", value="3:2", param_name="ratio"),
            ],
        ),
    )

    assert _resolve_numbered_character_reply("2", s)[0] == "resolved"
    assert _resolve_numbered_character_reply("1", s) is None
    assert s.collected_params["ratio"] == "3:2"


def test_resolve_numbered_character_reply_clears_expired_options_without_legacy_parse():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        pending_param="ratio",
        last_options=OptionSet(
            id="ratio-1",
            param_name="ratio",
            source="enum",
            created_at=100.0,
            ttl_sec=1,
            items=[
                OptionItem(index=1, label="2:3 竖版", value="2:3", param_name="ratio"),
                OptionItem(index=2, label="3:2 横版", value="3:2", param_name="ratio"),
            ],
        ),
    )
    _append_history(s, "assistant", "1. 2:3 竖版\n2. 3:2 横版")

    assert _resolve_numbered_character_reply("2", s) is None
    assert s.last_options is None
    assert "ratio" not in s.collected_params


def test_legacy_option_set_inference_does_not_persist_after_match():
    s = _US(mode="skill", skill_name="xd-poster-studio-v2", pending_param="ratio")
    _append_history(s, "assistant", "1. 2:3 竖版海报\n2. 3:2 横版")

    status, _ = _resolve_numbered_character_reply("2", s)

    assert status == "resolved"
    assert s.collected_params["ratio"] == "3:2"
    assert s.last_options is None


def test_legacy_option_set_inference_ignores_unknown_enum_param():
    s = _US(mode="skill", skill_name="xd-poster-studio-v2", pending_param="quality")
    _append_history(s, "assistant", "1. 超清\n2. 标准")

    assert _resolve_numbered_character_reply("1", s) is None
    assert s.last_options is None


def test_legacy_option_set_inference_ignores_plain_paragraph():
    s = _US(mode="skill", skill_name="xd-poster-studio-v2", pending_param="ratio")
    _append_history(s, "assistant", "请告诉我你想要什么比例")

    assert _resolve_numbered_character_reply("1", s) is None
    assert s.last_options is None


def test_legacy_option_set_inference_prioritizes_pending_ratio_over_characters():
    s = _US(
        mode="skill",
        skill_name="xd-poster-studio-v2",
        pending_param="ratio",
        loaded_resources={'lookup_characters': '[{"key":"aiai","name":"皑皑"}]'},
    )
    _append_history(s, "assistant", "1. 皑皑 (aiai)\n2. 3:2 横版")

    status, _ = _resolve_numbered_character_reply("2", s)

    assert status == "resolved"
    assert s.collected_params == {"ratio": "3:2"}


@pytest.mark.asyncio
async def test_completed_session_greeting_does_not_submit(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.executor import ExecuteResult
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="submit", submit_payload={"bad": "payload"}))
    execute = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="测试 skill",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
        completed=True,
    )

    await main_mod._agentic_loop("你好", session, "user-1", "msg-1")

    skill_decide.assert_not_called()
    execute.assert_not_called()
    reply_text.assert_called_once()
    sent = reply_text.call_args[0][2]
    assert "要继续这个任务" in sent
    assert store.saved[0] == "user-1"


@pytest.mark.asyncio
async def test_completed_session_capability_question_does_not_submit(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.executor import ExecuteResult
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="submit", submit_payload={"bad": "payload"}))
    execute = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
        completed=True,
    )

    await main_mod._agentic_loop("好的，你还能做其它什么事情?", session, "user-1", "msg-1")

    skill_decide.assert_not_called()
    execute.assert_not_called()
    reply_text.assert_called_once()
    sent = reply_text.call_args[0][2]
    assert "要继续这个任务" in sent
    assert "我目前可以帮你做这些事" in sent
    assert "生成海报" in sent
    assert store.saved[0] == "user-1"


@pytest.mark.asyncio
async def test_completed_session_unrelated_question_does_not_submit(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.executor import ExecuteResult
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="submit", submit_payload={"bad": "payload"}))
    execute = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
        completed=True,
    )

    await main_mod._agentic_loop("hello, 今天是周几啊", session, "user-1", "msg-1")

    skill_decide.assert_not_called()
    execute.assert_not_called()
    reply_text.assert_called_once()
    sent = reply_text.call_args[0][2]
    assert "AIGC 工具任务" in sent
    assert "要继续这个任务" in sent
    assert store.saved[0] == "user-1"


@pytest.mark.asyncio
async def test_completed_session_adjustment_still_reaches_skill_llm(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="reply", message="已收到修改"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
        completed=True,
    )

    await main_mod._agentic_loop("换成横版", session, "user-1", "msg-1")

    skill_decide.assert_awaited_once()
    reply_text.assert_called_once()
    assert reply_text.call_args[0][2] == "已收到修改"
    assert store.saved[0] == "user-1"


@pytest.mark.asyncio
async def test_active_skill_greeting_does_not_submit(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.executor import ExecuteResult
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="submit", submit_payload={"bad": "payload"}))
    execute = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="测试 skill",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["harry"], "actionDesc": "踢球"},
        completed=False,
    )

    await main_mod._agentic_loop("你好", session, "user-1", "msg-1")

    skill_decide.assert_not_called()
    execute.assert_not_called()
    reply_text.assert_called_once()
    sent = reply_text.call_args[0][2]
    assert "当前任务" in sent
    assert store.saved[0] == "user-1"


@pytest.mark.asyncio
async def test_ask_param_with_updated_value_continues_without_reasking(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = []

        async def save(self, user_id, session):
            self.saved.append((user_id, session.model_copy(deep=True)))

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(side_effect=[
        BotAction(action="ask_param", param_name="ratio", message="请确认比例", updated_params={"ratio": "3:2"}),
        BotAction(action="reply", message="继续下一步"),
    ])
    fake_skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(mode="skill", skill_name="xd-poster-gen", pending_param="ratio")

    await main_mod._agentic_loop("4", session, "user-1", "msg-1")

    assert skill_decide.await_count == 2
    reply_text.assert_called_once()
    assert reply_text.call_args[0][2] == "继续下一步"
    assert session.collected_params["ratio"] == "3:2"
    assert session.pending_param is None


@pytest.mark.asyncio
async def test_submit_sends_completion_followup(monkeypatch):
    from src import main as main_mod
    from src.orchestrator.schema import UserSession
    from src.orchestrator.schema import BotAction
    from src.skill.job_controller import JobController
    from src.skill.executor import ExecuteResult
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="submit", submit_payload={"topic": "coffee"}))
    execute = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})
    monkeypatch.setattr(
        main_mod,
        "_job_controller",
        JobController(redis=None, now=lambda: 100.0, job_id_factory=lambda: "job-1"),
    )

    session = UserSession(mode="skill", skill_name="xd-poster-gen")

    await main_mod._agentic_loop("生成海报", session, "user-1", "msg-1")

    sent = [call.args[2] for call in reply_text.call_args_list]
    assert sent == ["done", "已完成。要继续这个任务、调整哪里，还是换别的需求？"]
    assert store.saved[0] == "user-1"
    assert session.completed is True


@pytest.mark.asyncio
async def test_submit_duplicate_job_does_not_execute(monkeypatch):
    from src import main as main_mod
    from src.conversation.session import ActiveJob
    from src.orchestrator.schema import BotAction, UserSession
    from src.skill.executor import ExecuteResult
    from src.skill.job_controller import SubmitJobResult
    from src.skill.schema import Skill, HttpBackend, SkillOutput

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def save(self, user_id, session):
            self.saved = (user_id, session)

    class DuplicateJobController:
        async def begin_submit(self, *args, **kwargs):
            return SubmitJobResult(
                active_job=ActiveJob(
                    job_id="job-existing",
                    skill_name="xd-poster-gen",
                    action_name="submit",
                    payload={"topic": "coffee"},
                    source_message_id="msg-1",
                    status="running",
                    started_at=90.0,
                ),
                created=False,
                duplicate=True,
            )

    store = FakeStore()
    reply_text = AsyncMock()
    skill_decide = AsyncMock(return_value=BotAction(action="submit", submit_payload={"topic": "coffee"}))
    execute = AsyncMock(return_value=ExecuteResult(kind="text", text="done"))
    fake_skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "_job_controller", DuplicateJobController())
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "get_registry", lambda: {"xd-poster-gen": fake_skill})

    session = UserSession(mode="skill", skill_name="xd-poster-gen")

    await main_mod._agentic_loop("生成海报", session, "user-1", "msg-1")

    execute.assert_not_called()
    reply_text.assert_called_once()
    assert "不会重复生成" in reply_text.call_args[0][2]
    assert store.saved[0] == "user-1"
