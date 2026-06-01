import pytest
from pydantic import ValidationError
from openai.lib._pydantic import to_strict_json_schema
from src.orchestrator.schema import BotAction, UserSession


def _assert_no_dynamic_additional_properties(schema):
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "additionalProperties":
                assert value is False
            else:
                _assert_no_dynamic_additional_properties(value)
    elif isinstance(schema, list):
        for item in schema:
            _assert_no_dynamic_additional_properties(item)


def test_router_response_schema_is_bedrock_strict():
    from src.orchestrator.schema import RouterAction

    _assert_no_dynamic_additional_properties(to_strict_json_schema(RouterAction))


def test_skill_response_schema_is_bedrock_strict():
    from src.skill.runtime import SkillRuntimeWireAction

    _assert_no_dynamic_additional_properties(to_strict_json_schema(SkillRuntimeWireAction))


def test_botaction_valid_actions():
    for action in ["select_skill", "lookup_characters", "lookup_options", "ask_param",
                   "call_skill_action", "await_confirmation", "submit", "exit_skill", "reply", "out_of_scope"]:
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
