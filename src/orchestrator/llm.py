"""LLM 编排：双模式（router / skill）+ context engineering（lazy load）。

- router_decide：识别意图，选 skill；prompt 简短，只列 skill 名+描述
- skill_decide：进入特定 skill 的子上下文；prompt 注入 SKILL.md 核心 + 已 lazy load 资源

Prompt 文本存放在 `prompts/*.md`，模块加载时一次性读入，运行期不再 IO。

注意：不使用 beta.chat.completions.parse() 的 strict json_schema 模式，因为
LiteLLM → Bedrock 后端不支持 outputConfig strict 参数（BadRequestError）。
改用 chat.completions.create() + response_format json_object + 手动 Pydantic 验证。
"""
import json
import re
from pathlib import Path
from openai import AsyncOpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from src.mivo_mcp.client import format_mivo_mcp_catalog
from src.orchestrator.schema import BotAction, RouterAction, UserSession
from src.skill.actions import format_action_catalog
from src.skill.registry import get_registry
from src.skill.runtime import SkillRuntimeAction, SkillRuntimeWireAction
from src.skill.schema import Skill

_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


_ROUTER_SYSTEM = _load_prompt("router_system")
_SKILL_SYSTEM = _load_prompt("skill_system")
_COMPLETED_GUIDE = _load_prompt("completed_guide")


def _format_router_skills(skills: dict[str, Skill]) -> str:
    return "\n".join(f"- {s.name}: {s.description}" for s in skills.values())


def _format_loaded_resources(loaded: dict[str, str]) -> str:
    if not loaded:
        return ""
    parts = ["【已加载的资源 / skill action 结果（不要重复 lookup 或 call_skill_action）】"]
    for name, content in loaded.items():
        parts.append(f"\n### {name}\n{content}\n")
    return "\n".join(parts)


def _format_chat_history(chat_history: list) -> list[dict]:
    messages: list[dict] = []
    for message in chat_history:
        if isinstance(message, dict):
            messages.append(message)
        elif hasattr(message, "model_dump"):
            messages.append(message.model_dump())
    return messages


def _message_field(message, field: str):
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def _extract_json(content: str) -> str:
    """Strip markdown code fences and extract the first JSON object/array."""
    text = content.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _router_schema_hint() -> str:
    action_values = RouterAction.model_fields["action"].annotation
    # Extract enum values from the Literal type
    try:
        enum_vals = list(action_values.__args__)
    except AttributeError:
        enum_vals = ["select_skill", "call_mivo_mcp", "ask_param", "reply", "out_of_scope"]
    return (
        "\n【输出格式】必须输出纯 JSON（不加 Markdown 代码块），字段：\n"
        f'- action（必填，枚举值之一：{", ".join(enum_vals)}）\n'
        '- skill_name（字符串，select_skill 时填）\n'
        '- action_name（字符串，call_mivo_mcp 时填）\n'
        '- action_params（数组，call_mivo_mcp 时填，格式：[{"key":"arguments","value_json":"{...}"}]）\n'
        '- message（字符串，reply/ask_param 时填）\n'
        '- param_name（字符串，ask_param 时填）'
    )


def _skill_schema_hint() -> str:
    action_values = SkillRuntimeWireAction.model_fields["action"].annotation
    try:
        enum_vals = list(action_values.__args__)
    except AttributeError:
        enum_vals = ["call_skill_action", "call_mivo_mcp", "ask_param", "submit", "reply", "exit_skill"]
    return (
        "\n【输出格式】必须输出纯 JSON（不加 Markdown 代码块），字段：\n"
        f'- action（必填，枚举值之一：{", ".join(enum_vals)}）\n'
        '- action_name（字符串）\n'
        '- action_params（数组，格式：[{"key":"K","value_json":"V"}]）\n'
        '- updated_params（数组，同格式）\n'
        '- submit_payload（数组，同格式）\n'
        '- message（字符串）\n'
        '- param_name（字符串）\n'
        '- param_value（字符串）'
    )


async def router_decide(user_message: str, session: UserSession) -> BotAction:
    skills = get_registry()
    skill_list = _format_router_skills(skills)
    system_content = _ROUTER_SYSTEM.format(
        skills=skill_list,
        mivo_mcp_catalog_block=format_mivo_mcp_catalog(),
    ) + _router_schema_hint()
    resp = await _client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
    )
    content = _extract_json(resp.choices[0].message.content or "")
    return RouterAction.model_validate_json(content).to_bot_action()


async def skill_decide(user_message: str, session: UserSession, skill: Skill) -> SkillRuntimeAction:
    sys_prompt = _SKILL_SYSTEM.format(
        skill_name=skill.name,
        skill_description=skill.description,
        skill_core=skill.system_prompt_core or "（无额外规则）",
        initial_intent=session.initial_intent or "（用户当前消息即首次请求）",
        collected_params=json.dumps(session.collected_params, ensure_ascii=False),
        pending_param=session.pending_param or "无",
        completed=session.completed,
        loaded_resources_block=_format_loaded_resources(session.loaded_resources),
        action_catalog_block=format_action_catalog(skill),
        mivo_mcp_catalog_block=format_mivo_mcp_catalog(),
        completed_block=_COMPLETED_GUIDE if session.completed else "",
    ) + _skill_schema_hint()
    # 多轮对话：system + 历史 + 当前 user，让 LLM 看到自己上轮 reply（如 ABC 候选）
    messages: list[dict] = [{"role": "system", "content": sys_prompt}]
    messages.extend(_format_chat_history(session.chat_history))
    # _agentic_loop persists the current user turn before calling skill_decide.
    # Avoid sending the same user message twice; duplicates like "3", "3" make
    # models infer malformed values such as "33" or "billbill".
    if not (
        session.chat_history
        and _message_field(session.chat_history[-1], "role") == "user"
        and _message_field(session.chat_history[-1], "content") == user_message
    ):
        messages.append({"role": "user", "content": user_message})
    resp = await _client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = _extract_json(resp.choices[0].message.content or "")
    return SkillRuntimeWireAction.model_validate_json(content).to_runtime_action()


# 向后兼容旧测试
async def decide(user_message: str, session_context: str) -> BotAction:
    """Deprecated：旧 API，仅 test_orchestrator.py 现有测试在用。"""
    return await router_decide(user_message, UserSession())
