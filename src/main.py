import asyncio
import json
import logging
import time
import lark_oapi as lark
from lark_oapi.api.im.v1 import ListMessageRequest

from src.feishu.adapter import build_client
from src.feishu.reply import reply_text, reply_image
from src.feishu.upload import upload_image
from src.feishu.download import download_image
from src.orchestrator.llm import decide
from src.session.redis_store import SessionStore
from src.skill.executor import execute
from src.skill.registry import get_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# v0.1: hardcoded chat list (Feishu event routing 异常的临时方案)
# 后续加 im:chat:readonly 权限后改成自动发现
KNOWN_CHATS = ["oc_9162da5534b0d4ab07b6cd180cfc7c69"]
BOT_OPEN_ID = "ou_4cbc742010b166c20560ca6c792b7b1c"
POLL_INTERVAL = 2.0

_store = SessionStore()
_client = build_client()
_last_seen_ms: dict[str, int] = {}

_OUT_OF_SCOPE = "我只能帮你：去除图片背景（抠图）。请告诉我你想做什么。"


async def _fetch_new(chat_id: str) -> list:
    req = ListMessageRequest.builder() \
        .container_id_type("chat") \
        .container_id(chat_id) \
        .sort_type("ByCreateTimeDesc") \
        .page_size(10) \
        .build()
    resp = await _client.im.v1.message.alist(req)
    if not resp.success():
        log.error(f"poll {chat_id} failed: {resp.msg}")
        return []
    items = resp.data.items or []
    threshold = _last_seen_ms.get(chat_id, int(time.time() * 1000))
    new = []
    newest_seen = threshold
    for m in items:
        ts = int(m.create_time)
        newest_seen = max(newest_seen, ts)
        if ts <= threshold:
            break
        # 严格只处理 user 发的消息：bot/app 自己的消息会触发死循环
        if not m.sender or m.sender.sender_type != "user":
            continue
        new.append(m)
    _last_seen_ms[chat_id] = newest_seen
    return list(reversed(new))


async def _process(msg) -> None:
    message_id = msg.message_id
    msg_type = msg.msg_type
    user_id = msg.sender.id
    content = json.loads(msg.body.content)
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


async def _poll_loop() -> None:
    now_ms = int(time.time() * 1000)
    for chat_id in KNOWN_CHATS:
        _last_seen_ms[chat_id] = now_ms
    log.info(f"polling started: chats={KNOWN_CHATS} interval={POLL_INTERVAL}s")

    while True:
        for chat_id in KNOWN_CHATS:
            try:
                for msg in await _fetch_new(chat_id):
                    try:
                        await _process(msg)
                    except Exception:
                        log.exception(f"process failed for {msg.message_id}")
            except Exception:
                log.exception(f"poll failed for {chat_id}")
        await asyncio.sleep(POLL_INTERVAL)


def main() -> None:
    get_registry()
    asyncio.run(_poll_loop())


if __name__ == "__main__":
    main()
