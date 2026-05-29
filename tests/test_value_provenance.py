import json

from src.orchestrator.schema import BotAction, UserSession
from src.skill.schema import HttpBackend, Skill, SkillOutput, SkillParam


def _skill(params: list[SkillParam]) -> Skill:
    return Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=params,
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )


def test_provenance_rejects_existing_structured_value_mutation():
    from src.skill.provenance import filter_updated_params

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["bill"]},
    )
    skill = _skill([SkillParam(name="characters", type="json", prompt_to_user="角色")])
    action = BotAction(action="ask_param", updated_params={"characters": ["billbill"]})

    accepted, rejected = filter_updated_params(action.updated_params, session=session, skill=skill, user_text="bill")

    assert accepted == {}
    assert rejected == {"characters": "existing_structured_value_changed_without_provenance"}


def test_provenance_allows_exact_existing_structured_value():
    from src.skill.provenance import filter_updated_params

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"characters": ["bill"]},
    )
    skill = _skill([SkillParam(name="characters", type="json", prompt_to_user="角色")])

    accepted, rejected = filter_updated_params(
        {"characters": ["bill"]},
        session=session,
        skill=skill,
        user_text="bill",
    )

    assert accepted == {"characters": ["bill"]}
    assert rejected == {}


def test_provenance_allows_enum_value_declared_by_skill():
    from src.skill.provenance import filter_updated_params

    session = UserSession(
        mode="skill",
        skill_name="xd-poster-gen",
        collected_params={"ratio": "2:3"},
    )
    skill = _skill([SkillParam(name="ratio", type="enum", values=["2:3", "3:2"], prompt_to_user="比例")])

    accepted, rejected = filter_updated_params(
        {"ratio": "3:2"},
        session=session,
        skill=skill,
        user_text="换成横版",
    )

    assert accepted == {"ratio": "3:2"}
    assert rejected == {}


def test_provenance_rejects_unknown_param_key_even_with_text_match():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-poster-gen")
    skill = _skill([SkillParam(name="actionDesc", type="text", prompt_to_user="动作")])

    accepted, rejected = filter_updated_params(
        {"unknownField": "赛季更新"},
        session=session,
        skill=skill,
        user_text="赛季更新",
    )

    assert accepted == {}
    assert rejected == {"unknownField": "unknown_param"}


def test_provenance_allows_action_artifact_id_from_trusted_text():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-poster-gen")
    skill = _skill([SkillParam(name="actionDesc", type="text", prompt_to_user="动作")])

    accepted, rejected = filter_updated_params(
        {"fileId": "6a"},
        session=session,
        skill=skill,
        user_text="继续",
        trusted_text='{"data":{"schema_id":"image.fileId","payload":{"fileId":"6a"}}}',
    )

    assert accepted == {"fileId": "6a"}
    assert rejected == {}


def test_provenance_allows_json_character_key_from_trusted_text():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-town-studio")
    skill = _skill([SkillParam(name="characters", type="json", prompt_to_user="角色")])

    accepted, rejected = filter_updated_params(
        {"characters": ["artdam_0528_2156"]},
        session=session,
        skill=skill,
        user_text="4，港口，一起野餐，默认",
        trusted_text='{"characters":[{"key":"artdam_0528_2156","name":"金砂流影·先知"}]}',
    )

    assert accepted == {"characters": ["artdam_0528_2156"]}
    assert rejected == {}


def test_provenance_allows_json_character_object_from_trusted_text():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-town-studio")
    skill = _skill([SkillParam(name="characters", type="json", prompt_to_user="角色")])
    character = {
        "key": "artdam_0528_2156",
        "name": "金砂流影·先知",
        "refImage": "artdam://asset/2156?public_id=a_Vf52f1KbMFuE&resize=4k",
        "fusionDesc": "0528 套装角色「金砂流影·先知」",
    }

    accepted, rejected = filter_updated_params(
        {"characters": [character]},
        session=session,
        skill=skill,
        user_text="4，港口，一起野餐，默认",
        trusted_text=json.dumps({"characters": [character]}, ensure_ascii=False),
    )

    assert accepted == {"characters": [character]}
    assert rejected == {}


def test_provenance_rejects_action_artifact_id_without_trusted_text():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-poster-gen")
    skill = _skill([SkillParam(name="actionDesc", type="text", prompt_to_user="动作")])

    accepted, rejected = filter_updated_params(
        {"fileId": "6a"},
        session=session,
        skill=skill,
        user_text="继续",
    )

    assert accepted == {}
    assert rejected == {"fileId": "unknown_param"}


def test_provenance_rejects_new_free_text_without_user_text_match():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-poster-gen")
    skill = _skill([SkillParam(name="actionDesc", type="text", prompt_to_user="动作")])

    accepted, rejected = filter_updated_params(
        {"actionDesc": "慢悠悠生活"},
        session=session,
        skill=skill,
        user_text="帮我做一张海报",
    )

    assert accepted == {}
    assert rejected == {"actionDesc": "value_without_provenance"}


def test_provenance_allows_new_free_text_from_user_text():
    from src.skill.provenance import filter_updated_params

    session = UserSession(mode="skill", skill_name="xd-poster-gen")
    skill = _skill([SkillParam(name="actionDesc", type="text", prompt_to_user="动作")])

    accepted, rejected = filter_updated_params(
        {"actionDesc": "赛季更新"},
        session=session,
        skill=skill,
        user_text="做一个赛季更新海报",
    )

    assert accepted == {"actionDesc": "赛季更新"}
    assert rejected == {}
