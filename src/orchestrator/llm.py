"""LLM 编排：双模式（router / skill）+ context engineering（lazy load）。

- router_decide：识别意图，选 skill；prompt 简短，只列 skill 名+描述
- skill_decide：进入特定 skill 的子上下文；prompt 注入 SKILL.md 核心 + 已 lazy load 资源
"""
import json
from openai import AsyncOpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from src.orchestrator.schema import BotAction, UserSession
from src.skill.registry import get_registry
from src.skill.schema import Skill

_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


_ROUTER_SYSTEM = """\
你是 AIGC bot 的路由层（Router Mode）。职责：识别用户意图，决定走哪个工具。

可用工具：
{skills}

规则：
1. 永远用中文回复
2. 用户描述了具体意图（如「帮我去白底」「画张海报」）且匹配上面某个工具 → action=select_skill, skill_name=<工具 name>
3. 用户在打招呼/闲聊/问你能做什么 → action=reply, message=<友好回复>
4. 用户请求超出工具范围（如「帮我订机票」） → action=out_of_scope
5. 不要自己回答用户「具体怎么做」的问题，那是工具的工作；你的工作是路由
"""


_SKILL_SYSTEM = """\
你是 AIGC bot 的 Skill Mode，当前激活的 skill 是：{skill_name}
{skill_description}

【SKILL 核心规则】
{skill_core}

【当前 session 状态】
- 已收集参数（collected_params）: {collected_params}
- 上一轮待确认参数（pending_param）: {pending_param}

{loaded_resources_block}

【你可输出的 action】
- `ask_param`: 需要继续问用户某个 brief 字段（一次只问一个），message=问句，param_name=对应字段名
- `lookup_characters`: 需要查角色清单时输出（系统会自动加载并回喂你，不要再追问用户）
- `lookup_options`: 需要查排版/比例选项时输出（同上）
- `submit`: 所有必填 brief 已齐，输出 submit_payload=完整的 API JSON payload（按 SKILL.md Step 2 字段映射规则构造）
- `exit_skill`: 用户明确说不做了/换需求 → 退出本 skill 回 Router
- `reply`: 自由回复（澄清/确认/感谢），不切状态

【重要】
- 一次 ask_param 只问一个字段，不要一次问多个
- 如果用户答了你上一轮 pending_param，把答案放进 updated_params: {{"<param_name>": "<value>"}}
- submit 前必须确保 SKILL.md 里的所有 required 字段都在 collected_params 里
- 永远用中文回复
"""


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
        collected_params=json.dumps(session.collected_params, ensure_ascii=False),
        pending_param=session.pending_param or "无",
        loaded_resources_block=_format_loaded_resources(session.loaded_resources),
    )
    resp = await _client.beta.chat.completions.parse(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_message},
        ],
        response_format=BotAction,
    )
    return resp.choices[0].message.parsed


# 向后兼容旧测试
async def decide(user_message: str, session_context: str) -> BotAction:
    """Deprecated：旧 API，仅 test_orchestrator.py 现有测试在用。"""
    return await router_decide(user_message, UserSession())
