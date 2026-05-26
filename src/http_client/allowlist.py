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

# 运行时由 registry 注册的额外前缀（来自 manifest 里 HttpResource 的 host+port）
_DYNAMIC_PREFIXES: set[str] = set()


def register_allowed_prefix(prefix: str) -> None:
    """注册一个动态白名单前缀。供 skill registry 在加载 HttpResource 时调用。"""
    _DYNAMIC_PREFIXES.add(_normalize(prefix))


def _url_allowed(url: str) -> bool:
    normalised = _normalize(url)
    if any(normalised.startswith(p) for p in _ALLOWED_PREFIXES):
        return True
    return any(normalised.startswith(p) for p in _DYNAMIC_PREFIXES)


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
