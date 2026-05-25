import json
import lark_oapi as lark
from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody


async def reply_text(client: lark.Client, message_id: str, text: str) -> None:
    body = ReplyMessageRequestBody.builder() \
        .msg_type("text") \
        .content(json.dumps({"text": text}, ensure_ascii=False)) \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    await client.im.v1.message.areply(req)


async def reply_image(client: lark.Client, message_id: str, image_key: str) -> None:
    body = ReplyMessageRequestBody.builder() \
        .msg_type("image") \
        .content(json.dumps({"image_key": image_key})) \
        .build()
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(body) \
        .build()
    await client.im.v1.message.areply(req)
