from src.conversation.option_resolver import build_enum_option_set
from src.conversation.response import ResponseComposer
from src.skill.schema import HttpBackend, Skill, SkillOutput


def _skill(name: str, description: str) -> Skill:
    return Skill(
        name=name,
        description=description,
        api=HttpBackend(endpoint_path="/api/test"),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
    )


def test_completed_capability_lists_available_skills():
    composer = ResponseComposer(lambda: [_skill("poster", "生成海报")])

    message = composer.completed_capability()

    assert "要继续这个任务" in message
    assert "我目前可以帮你做这些事" in message
    assert "生成海报" in message


def test_boundary_message_is_tool_scoped():
    message = ResponseComposer(lambda: []).completed_boundary()

    assert "AIGC 工具任务" in message
    assert "要继续这个任务" in message


def test_skill_chitchat_differs_for_active_and_completed_sessions():
    composer = ResponseComposer(lambda: [])

    assert "当前任务" in composer.skill_chitchat(completed=False)
    assert "上一个任务" in composer.skill_chitchat(completed=True)


def test_local_cancel_message_does_not_claim_backend_cancelled():
    message = ResponseComposer(lambda: []).local_cancel()

    assert "停止等待" in message
    assert "已取消生成" not in message


def test_render_option_set_uses_shared_option_renderer():
    option_set = build_enum_option_set("ratio", ["2:3", "3:2"], now=100.0)

    assert ResponseComposer(lambda: []).render_options(option_set) == "1. 2:3\n2. 3:2"
