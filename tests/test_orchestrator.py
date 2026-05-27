import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.orchestrator.schema import BotAction, UserSession
from src.orchestrator.llm import decide, skill_decide
from src.skill.schema import HttpBackend, Skill, SkillOutput


def _mock_response(action: str, **kwargs) -> MagicMock:
    parsed = BotAction(action=action, **kwargs)
    choice = MagicMock()
    choice.message.parsed = parsed
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_decide_select_skill_for_bg_removal():
    with patch("src.orchestrator.llm._client") as mock_client:
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_response("select_skill", skill_name="frame-bg-remover")
        )
        action = await decide("帮我去白底", "{}")
    assert action.action == "select_skill"
    assert action.skill_name == "frame-bg-remover"


@pytest.mark.asyncio
async def test_decide_out_of_scope_for_unrelated():
    with patch("src.orchestrator.llm._client") as mock_client:
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_response("out_of_scope")
        )
        action = await decide("帮我查同事的信息", "{}")
    assert action.action == "out_of_scope"


@pytest.mark.asyncio
async def test_decide_ask_param_when_missing_image():
    with patch("src.orchestrator.llm._client") as mock_client:
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_response("ask_param", param_name="image", message="请上传图片")
        )
        action = await decide("抠图", '{"state":"collecting","skill_name":"frame-bg-remover"}')
    assert action.action == "ask_param"
    assert action.param_name == "image"


@pytest.mark.asyncio
async def test_decide_returns_botaction_instance():
    with patch("src.orchestrator.llm._client") as mock_client:
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_response("reply", message="你好")
        )
        action = await decide("你好", "{}")
    assert isinstance(action, BotAction)


@pytest.mark.asyncio
async def test_skill_decide_does_not_duplicate_current_user_message():
    skill = Skill(
        name="test-skill",
        description="test",
        api=HttpBackend(endpoint_path="/api/test"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )
    session = UserSession(
        mode="skill",
        skill_name="test-skill",
        chat_history=[
            {"role": "assistant", "content": "1. 皑皑 (aiai)\n2. 比尔 (bill)"},
            {"role": "user", "content": "bill"},
        ],
    )

    with patch("src.orchestrator.llm._client") as mock_client:
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_response("reply", message="ok")
        )
        await skill_decide("bill", session, skill)

    messages = mock_client.beta.chat.completions.parse.await_args.kwargs["messages"]
    user_messages = [msg for msg in messages if msg["role"] == "user" and msg["content"] == "bill"]
    assert len(user_messages) == 1
