import httpx
from src.config import TOOLBOX_BASE_URL

def _normalize(url: str) -> str:
    # httpx drops default port 80 from http:// URLs; normalise for consistent comparison
    return url.rstrip("/").replace(":80/", "/").replace(":80", "")


_ALLOWED_PREFIXES = (
    _normalize(TOOLBOX_BASE_URL),
    "https://open.feishu.cn",
    "https://llm-proxy.tapsvc.com",
)


def _url_allowed(url: str) -> bool:
    normalised = _normalize(url)
    return any(normalised.startswith(prefix) for prefix in _ALLOWED_PREFIXES)


class AllowlistTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if not _url_allowed(url):
            raise PermissionError(f"Blocked outbound request to: {url}")
        return await self._inner.handle_async_request(request)


def allowed_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=AllowlistTransport())
