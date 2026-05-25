import asyncio
import json
import logging
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
    user_id = data.event.sender.sender_id.open_id
    content = json.loads(msg.content)
    log.info(f"[MSG] user={user_id} type={msg_type} content={content}")

    session = await _store.get(user_id)

    if msg_type == "image" and session.state == "collecting" and session.pending_param:
        image_key = content.get("image_key", "")
        image_bytes = await download_image(_client, message_id, image_key)
        skill = get_registry()[session.skill_name]
        params = dict(session.collected_params)
        params[session.pending_param] = ("frame.png", image_bytes, "image/png")
        try:
            result_bytes = await execute(skill, params)
            uploaded_key = await upload_image(_client, result_bytes)
            await reply_image(_client, message_id, uploaded_key)
        except Exception as e:
            log.exception("skill execution failed")
            await reply_text(_client, message_id, f"处理失败：{e}")
        await _store.clear(user_id)
        return

    if msg_type != "text":
        await reply_text(_client, message_id, "请发送文字描述你想做什么，或上传图片。")
        return

    text = content.get("text", "").strip()
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
            result_bytes = await execute(skill, {})
            uploaded_key = await upload_image(_client, result_bytes)
            await reply_image(_client, message_id, uploaded_key)
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
