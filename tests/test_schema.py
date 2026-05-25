import pytest
from pydantic import ValidationError
from src.orchestrator.schema import BotAction, UserSession


def test_botaction_valid_actions():
    for action in ["select_skill", "lookup_characters", "lookup_options", "ask_param",
                   "submit", "exit_skill", "reply", "out_of_scope"]:
        b = BotAction(action=action)
        assert b.action == action


def test_botaction_rejects_unknown_action():
    with pytest.raises(ValidationError):
        BotAction(action="do_evil")


def test_botaction_optional_fields_default_none():
    b = BotAction(action="reply", message="hi")
    assert b.skill_name is None
    assert b.param_name is None


def test_usersession_defaults():
    s = UserSession()
    assert s.state == "idle"
    assert s.skill_name is None
    assert s.collected_params == {}
    assert s.pending_param is None


def test_usersession_roundtrip():
    s = UserSession(state="collecting", skill_name="frame-bg-remover", pending_param="image")
    s2 = UserSession.model_validate_json(s.model_dump_json())
    assert s2.state == "collecting"
    assert s2.skill_name == "frame-bg-remover"
    assert s2.pending_param == "image"
