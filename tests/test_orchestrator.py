import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.orchestrator.schema import BotAction
from src.orchestrator.llm import decide


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
