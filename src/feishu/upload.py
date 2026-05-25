import io
import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody


async def upload_image(client: lark.Client, image_bytes: bytes) -> str:
    body = CreateImageRequestBody.builder() \
        .image_type("message") \
        .image(io.BytesIO(image_bytes)) \
        .build()
    req = CreateImageRequest.builder().request_body(body).build()
    resp = await client.im.v1.image.acreate(req)
    if not resp.success():
        raise RuntimeError(f"Image upload failed: {resp.msg}")
    return resp.data.image_key
