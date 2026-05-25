import lark_oapi as lark
from lark_oapi.api.im.v1 import GetMessageResourceRequest


async def download_image(client: lark.Client, message_id: str, image_key: str) -> bytes:
    req = GetMessageResourceRequest.builder() \
        .message_id(message_id) \
        .file_key(image_key) \
        .type("image") \
        .build()
    resp = await client.im.v1.message_resource.aget(req)
    if not resp.success():
        raise RuntimeError(f"image download failed: {resp.msg}")
    return resp.file.read()
