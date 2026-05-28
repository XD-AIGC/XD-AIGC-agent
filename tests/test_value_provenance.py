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
