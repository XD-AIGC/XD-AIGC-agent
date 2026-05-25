import asyncio
import json
import logging
import re
import lark_oapi as lark

from src.feishu.adapter import build_client, build_event_handler
from src.feishu.reply import reply_text, reply_image
from src.feishu.upload import upload_image
from src.feishu.download import download_image
from src.orchestrator.llm import decide
from src.session.redis_store import SessionStore
from src.skill.executor import execute
from src.skill.registry import get_registry
from src.config import FEISHU_APP_ID, FEISHU_APP_SECRET

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_store = SessionStore()
_client = build_client()

_OUT_OF_SCOPE = "我只能帮你：去除图片背景（抠图）。请告诉我你想做什么。"

# 飞书群里 @mention 在 content.text 里渲染为 "@_user_N" 占位符
_MENTION_PLACEHOLDER = re.compile(r"@_user_\d+\s*")


def _strip_mentions(text: str) -> str:
    """去掉群里 @mention 占位符（@_user_1 / @_user_2 ...），便于 LLM 理解纯意图。"""
    return _MENTION_PLACEHOLDER.sub("", text).strip()


def _normalize_message(msg_type: str, content: dict) -> tuple[str, str | None]:
    """归一化飞书消息为 (text, image_key)。post 类型会自动提取文字 + 第一张图。"""
    if msg_type == "text":
        return _strip_mentions(content.get("text", "")), None
    if msg_type == "image":
        return "", content.get("image_key")
    if msg_type == "post":
        text_parts: list[str] = []
        image_key: str | None = None
        for line in content.get("content", []):
            for tag in line:
                tag_type = tag.get("tag")
                if tag_type == "text":
                    text_parts.append(tag.get("text", ""))
                elif tag_type == "img" and image_key is None:
                    image_key = tag.get("image_key")
                # 'at' tag 直接忽略（在群聊里就是 @bot 本身）
        return " ".join(text_parts).strip(), image_key
    return "", None


async def _execute_image_skill(skill_name: str, image_key: str, message_id: str, user_id: str) -> None:
    """下载图片 → 调 skill → 上传结果 → 回图。统一的 image-skill 执行路径。"""
    skill = get_registry().get(skill_name)
    if skill is None:
        await reply_text(_client, message_id, f"未知 skill: {skill_name}")
        return
    image_param = next((p for p in skill.params if p.type == "image"), None)
    if image_param is None:
        await reply_text(_client, message_id, f"skill {skill_name} 不接受图片输入")
        return
    try:
        image_bytes = await download_image(_client, message_id, image_key)
        params = {image_param.name: ("frame.png", image_bytes, "image/png")}
        result = await execute(skill, params)
        if result.kind == "binary":
            uploaded_key = await upload_image(_client, result.content_bytes)
            await reply_image(_client, message_id, uploaded_key)
        elif result.kind == "url":
            # A4 阶段实现：从 URL 下载图片再上传飞书
            await reply_text(_client, message_id, f"完成（URL 返回未实现）：{result.result_url}")
        else:
            await reply_text(_client, message_id, result.text or "完成")
    except Exception as e:
        log.exception("image skill execution failed")
        await reply_text(_client, message_id, f"处理失败：{e}")
    finally:
        await _store.clear(user_id)


def _single_image_skill() -> str | None:
    """如果只有一个接受 image 输入的 skill，返回它的名字；否则 None。"""
    skills = [s for s in get_registry().values() if any(p.type == "image" for p in s.params)]
    return skills[0].name if len(skills) == 1 else None


def on_message(data) -> None:
    """lark-oapi dispatcher 是同步的，把 async 任务挂到已运行的事件循环上。"""
    try:
        asyncio.ensure_future(_process(data))
    except Exception:
        log.exception("on_message scheduling failed")


async def _process(data) -> None:
    msg = data.event.message
    message_id = msg.message_id
    msg_type = msg.message_type
    chat_id = msg.chat_id
    chat_type = getattr(msg, "chat_type", "p2p")
    user_id = data.event.sender.sender_id.open_id
    content = json.loads(msg.content)
    log.info(f"[MSG] chat={chat_id} type={chat_type}/{msg_type} user={user_id} content={content}")

    text, image_key = _normalize_message(msg_type, content)
    session = await _store.get(user_id)

    # 智能路径 1：用户一次性给了 text + image（典型场景：群里 @bot 配图说意图）
    if text and image_key:
        action = await decide(text, session.model_dump_json())
        log.info(f"[ACT] {action}")
        if action.action == "select_skill" and action.skill_name:
            await _execute_image_skill(action.skill_name, image_key, message_id, user_id)
            return
        # text 不构成 select_skill，回退到纯 image 自动路由
        single = _single_image_skill()
        if single:
            await _execute_image_skill(single, image_key, message_id, user_id)
            return

    # 智能路径 2：多轮对话中正在收图（state=collecting 且 pending=image）
    if image_key and session.state == "collecting" and session.pending_param:
        await _execute_image_skill(session.skill_name, image_key, message_id, user_id)
        return

    # 智能路径 3：用户裸发一张图，session 是 idle —— 若只有 1 个 image skill，直接执行
    if image_key:
        single = _single_image_skill()
        if single:
            await _execute_image_skill(single, image_key, message_id, user_id)
            return
        await reply_text(_client, message_id, "你想用这张图做什么？请告诉我。")
        return

    # 纯文字路径
    if not text:
        await reply_text(_client, message_id, "请告诉我你想做什么，比如「帮我去白底」。")
        return

    action = await decide(text, session.model_dump_json())
    log.info(f"[ACT] {action}")

    if action.action == "out_of_scope":
        await reply_text(_client, message_id, _OUT_OF_SCOPE)
        await _store.clear(user_id)

    elif action.action == "select_skill":
        session.state = "collecting"
        session.skill_name = action.skill_name
        skill = get_registry()[action.skill_name]
        first_param = next((p for p in skill.params if p.required), None)
        if first_param:
            session.pending_param = first_param.name
            await reply_text(_client, message_id, first_param.prompt_to_user)
            await _store.save(user_id, session)
        else:
            result = await execute(skill, {})
            if result.kind == "binary":
                uploaded_key = await upload_image(_client, result.content_bytes)
                await reply_image(_client, message_id, uploaded_key)
            else:
                await reply_text(_client, message_id, result.text or str(result.result_url or "完成"))
            await _store.clear(user_id)

    elif action.action in ("ask_param", "reply"):
        await reply_text(_client, message_id, action.message or "")
        await _store.save(user_id, session)


def main() -> None:
    get_registry()
    handler = build_event_handler(on_message)
    ws = lark.ws.Client(
        FEISHU_APP_ID,
        FEISHU_APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    log.info("starting WebSocket client")
    ws.start()


if __name__ == "__main__":
    main()
