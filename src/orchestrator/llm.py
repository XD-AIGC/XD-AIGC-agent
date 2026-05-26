"""LLM 编排：双模式（router / skill）+ context engineering（lazy load）。

- router_decide：识别意图，选 skill；prompt 简短，只列 skill 名+描述
- skill_decide：进入特定 skill 的子上下文；prompt 注入 SKILL.md 核心 + 已 lazy load 资源

Prompt 文本存放在 `prompts/*.md`，模块加载时一次性读入，运行期不再 IO。
"""
import json
from pathlib import Path
from openai import AsyncOpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from src.orchestrator.schema import BotAction, UserSession
from src.skill.registry import get_registry
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
    parts = ["【已加载的资源（不要重复 lookup）】"]
    for name, content in loaded.items():
        parts.append(f"\n### {name}\n{content}\n")
    return "\n".join(parts)


async def router_decide(user_message: str, session: UserSession) -> BotAction:
    skills = get_registry()
    skill_list = _format_router_skills(skills)
    resp = await _client.beta.chat.completions.parse(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _ROUTER_SYSTEM.format(skills=skill_list)},
            {"role": "user", "content": user_message},
        ],
        response_format=BotAction,
    )
    return resp.choices[0].message.parsed


async def skill_decide(user_message: str, session: UserSession, skill: Skill) -> BotAction:
    sys_prompt = _SKILL_SYSTEM.format(
        skill_name=skill.name,
        skill_description=skill.description,
        skill_core=skill.system_prompt_core or "（无额外规则）",
        initial_intent=session.initial_intent or "（用户当前消息即首次请求）",
        collected_params=json.dumps(session.collected_params, ensure_ascii=False),
        pending_param=session.pending_param or "无",
        completed=session.completed,
        loaded_resources_block=_format_loaded_resources(session.loaded_resources),
        completed_block=_COMPLETED_GUIDE if session.completed else "",
    )
    # 多轮对话：system + 历史 + 当前 user，让 LLM 看到自己上轮 reply（如 ABC 候选）
    messages: list[dict] = [{"role": "system", "content": sys_prompt}]
    messages.extend(session.chat_history)
    messages.append({"role": "user", "content": user_message})
    resp = await _client.beta.chat.completions.parse(
        model=LLM_MODEL,
        messages=messages,
        response_format=BotAction,
    )
    return resp.choices[0].message.parsed


# 向后兼容旧测试
async def decide(user_message: str, session_context: str) -> BotAction:
    """Deprecated：旧 API，仅 test_orchestrator.py 现有测试在用。"""
    return await router_decide(user_message, UserSession())
