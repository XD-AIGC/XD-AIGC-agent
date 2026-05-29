import json
import logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

log = logging.getLogger(__name__)

# 飞书 text 消息长度限制：5000 字符（实际限制是 byte，留余量）
_MAX_TEXT_LEN = 3000


async def reply_text(client: lark.Client, message_id: str, text: str) -> bool:
    if len(text) > _MAX_TEXT_LEN:
        log.warning(f"reply text 过长 ({len(text)} 字符)，截断到 {_MAX_TEXT_LEN}")
        text = text[:_MAX_TEXT_LEN] + "\n...(过长已截断)"
    body = ReplyMessageRequestBody.builder() \
        .msg_type("text") \
        .content(json.dumps({"text": text}, ensure_ascii=False)) \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = await client.im.v1.message.areply(req)
    if not resp.success():
        log.error(f"reply_text failed: code={resp.code} msg={resp.msg} text_len={len(text)} text_preview={text[:200]!r}")
        return False
    return True


async def reply_image(client: lark.Client, message_id: str, image_key: str) -> bool:
    body = ReplyMessageRequestBody.builder() \
        .msg_type("image") \
        .content(json.dumps({"image_key": image_key})) \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    resp = await client.im.v1.message.areply(req)
    if not resp.success():
        log.error(f"reply_image failed: code={resp.code} msg={resp.msg} image_key={image_key[:80]!r}")
        return False
    return True
