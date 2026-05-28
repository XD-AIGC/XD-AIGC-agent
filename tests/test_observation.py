import json

from src.skill.actions import SkillActionObservation


def _prompt_payload(obs: SkillActionObservation) -> dict:
    return json.loads(obs.for_prompt())


def test_skill_action_observation_for_prompt_uses_two_layer_envelope():
    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="generate_step1_only completed",
            data={"fileId": "6a"},
            artifact={"sent_to_user": True},
        )
    )

    assert payload["status"] == "success"
    assert payload["summary"] == "generate_step1_only completed"
    assert payload["data"] == {
        "schema_id": "image.fileId",
        "payload": {"fileId": "6a"},
    }
    assert payload["artifacts"] == {"sent_to_user": True}
    assert payload["next_actions"] == []
    assert payload["stop_condition"] is None
    assert "artifact" not in payload


def test_error_observation_for_prompt_includes_recovery_contract():
    payload = _prompt_payload(
        SkillActionObservation(
            status="error",
            summary="generate_step1_only 调用失败: HTTPStatusError: 500",
        )
    )

    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["next_actions"] == ["check_action_params", "retry_or_exit_skill"]
    assert payload["stop_condition"] == "do not retry the same action without changed parameters"


def test_explicit_schema_id_wraps_unknown_skill_payload():
    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="custom action completed",
            data={"foo": "bar"},
            data_schema_id="poster.custom_result",
        )
    )

    assert payload["data"] == {
        "schema_id": "poster.custom_result",
        "payload": {"foo": "bar"},
    }
