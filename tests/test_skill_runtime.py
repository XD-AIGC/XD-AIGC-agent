import pytest
from pydantic import ValidationError


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


@pytest.mark.asyncio
async def test_skill_decide_uses_skill_runtime_action_schema(monkeypatch):
    from src.orchestrator import llm as llm_mod
    from src.orchestrator.schema import UserSession
    from src.skill.runtime import SkillRuntimeAction
    from src.skill.schema import HttpBackend, Skill, SkillOutput

    captured = {}

    class _Message:
        parsed = SkillRuntimeAction(action="reply", message="ok")

    class _Choice:
        message = _Message()

    class _Completions:
        async def parse(self, **kwargs):
            captured["response_format"] = kwargs["response_format"]
            return type("Resp", (), {"choices": [_Choice()]})()

    class _Chat:
        completions = _Completions()

    class _Beta:
        chat = _Chat()

    class _Client:
        beta = _Beta()

    skill = Skill(
        name="xd-poster-gen",
        description="生成海报",
        api=HttpBackend(endpoint_path="/api/test", content_type="application/json"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="test",
    )

    monkeypatch.setattr(llm_mod, "_client", _Client())

    action = await llm_mod.skill_decide("继续", UserSession(mode="skill"), skill)

    assert captured["response_format"] is SkillRuntimeAction
    assert isinstance(action, SkillRuntimeAction)
