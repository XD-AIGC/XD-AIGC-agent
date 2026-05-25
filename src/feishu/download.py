import httpx
import lark_oapi as lark
from lark_oapi.api.im.v1 import GetMessageResourceRequest


async def download_image(client: lark.Client, message_id: str, image_key: str) -> bytes:
    """从飞书消息下载图片字节（用 image_key）。"""
    req = GetMessageResourceRequest.builder() \
        .message_id(message_id) \
        .file_key(image_key) \
        .type("image") \
        .build()
    resp = await client.im.v1.message_resource.aget(req)
    if not resp.success():
        raise RuntimeError(f"image download failed: {resp.msg}")
    return resp.file.read()


async def download_url(url: str, timeout_sec: int = 30) -> bytes:
    """下载 backend 返回的结果 URL（如 poster-gen 的签名图片直链）。

    安全说明：这里不走 allowlist，因为 URL 来自我们刚调用的可信 backend
    返回值。LLM 不能直接构造 URL 让 bot 下载。如果将来 LLM 能直接输出
    URL 让 bot 下载，必须收回这个豁免。
    """
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
