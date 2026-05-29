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


def test_image_list_payload_uses_image_list_schema():
    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="variants loaded",
            data=[{"fileId": "a"}, {"fileId": "b"}],
        )
    )

    assert payload["data"] == {
        "schema_id": "image.list",
        "payload": {"items": [{"fileId": "a"}, {"fileId": "b"}]},
    }


def test_generic_list_payload_does_not_default_to_characters():
    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="styles loaded",
            data=[{"style": "comic"}],
        )
    )

    assert payload["data"] == {
        "schema_id": "unknown.raw",
        "payload": {"items": [{"style": "comic"}]},
    }


def test_character_list_requires_character_source_context():
    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="characters loaded",
            data=[{"key": "annie", "name": "安妮"}],
            source_name="lookup_characters",
        )
    )

    assert payload["data"] == {
        "schema_id": "lookup.characters",
        "payload": {"items": [{"key": "annie", "name": "安妮"}]},
    }


def test_scalar_string_payload_uses_text_plain_schema():
    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="text loaded",
            data="hello world",
        )
    )

    assert payload["data"] == {
        "schema_id": "text.plain",
        "payload": {"text": "hello world"},
    }


def test_large_dict_payload_preserves_later_top_level_lists():
    npc_characters = [
        {
            "key": f"npc-{idx}",
            "name": f"NPC {idx}",
            "refImage": f"artdam://asset/{idx}",
            "prompt": "x" * 1000,
        }
        for idx in range(20)
    ]
    scenes = [
        {"key": "flowerfield", "name": "花田", "refImage": "artdam://asset/2140"},
        {"key": "harbor", "name": "港口", "refImage": "artdam://asset/2142"},
    ]

    payload = _prompt_payload(
        SkillActionObservation(
            status="success",
            summary="artdam library loaded",
            data={"npcCharacters": npc_characters, "scenes": scenes},
            source_name="get_artdam_library",
        )
    )

    data = payload["data"]["payload"]
    assert data["_list_counts"]["npcCharacters"] == 20
    assert any(scene["key"] == "harbor" for scene in data["scenes"])
    assert len(json.dumps(payload, ensure_ascii=False)) < 9000
