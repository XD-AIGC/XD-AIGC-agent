from openai import AsyncOpenAI
from src.config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
from src.orchestrator.schema import BotAction
from src.skill.registry import get_registry

_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

_SYSTEM = """\
你是 AIGC bot，只能调用以下工具：

{skills}

规则：
1. 永远用中文回复
2. 不在工具范围内的请求 → out_of_scope
3. 用户描述意图但未提供参数 → select_skill（系统会自动按 skill 定义提示用户上传/输入）
4. param_name 必须严格使用 skill 定义里的字段名，不要自创
5. 图片类型 (type: image) 的参数只能通过用户**直接上传图片**获得，绝对不要让用户提供 URL / 链接
6. 收齐所有 required 参数前不要 call_api
"""


def _format_skills(skills) -> str:
    lines = []
    for s in skills.values():
        lines.append(f"## {s.name}")
        lines.append(f"用途: {s.description}")
        lines.append("参数:")
        for p in s.params:
            req = "必填" if p.required else "可选"
            lines.append(f"  - {p.name} (type={p.type}, {req}): {p.prompt_to_user}")
        lines.append("")
    return "\n".join(lines)


async def decide(user_message: str, session_context: str) -> BotAction:
    skills = get_registry()
    skill_text = _format_skills(skills)

    resp = await _client.beta.chat.completions.parse(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM.format(skills=skill_text)},
            {"role": "user", "content": f"[当前会话状态: {session_context}]\n用户消息: {user_message}"},
        ],
        response_format=BotAction,
    )
    return resp.choices[0].message.parsed
