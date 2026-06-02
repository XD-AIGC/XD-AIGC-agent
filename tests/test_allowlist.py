import pytest
import httpx
from unittest.mock import AsyncMock, patch
from src.http_client.allowlist import AllowlistTransport, allowed_client


@pytest.mark.asyncio
async def test_blocks_external_url():
    transport = AllowlistTransport()
    request = httpx.Request("GET", "https://evil.com/steal")
    with pytest.raises(PermissionError, match="Blocked outbound request"):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_allows_toolbox_url():
    transport = AllowlistTransport()
    request = httpx.Request("POST", "http://localhost:8080/api/shared/frame-bg-remover/process")
    mock_response = httpx.Response(200, content=b"fake-image")
    with patch.object(transport._inner, "handle_async_request", return_value=mock_response):
        resp = await transport.handle_async_request(request)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_allows_feishu_url():
    transport = AllowlistTransport()
    request = httpx.Request("POST", "https://open.feishu.cn/open-apis/im/v1/messages")
    mock_response = httpx.Response(200, content=b"{}")
    with patch.object(transport._inner, "handle_async_request", return_value=mock_response):
        resp = await transport.handle_async_request(request)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_allows_mivo_mcp_url():
    transport = AllowlistTransport()
    request = httpx.Request("POST", "https://aigc.xindong.com/api/v1/message")
    mock_response = httpx.Response(200, content=b"{}")
    with patch.object(transport._inner, "handle_async_request", return_value=mock_response):
        resp = await transport.handle_async_request(request)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_allows_mivo_download_redirect_url():
    transport = AllowlistTransport()
    request = httpx.Request("GET", "https://oa-ai-middle.oss-accelerate.aliyuncs.com/path/output.png?sig=1")
    mock_response = httpx.Response(200, content=b"image")
    with patch.object(transport._inner, "handle_async_request", return_value=mock_response):
        resp = await transport.handle_async_request(request)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_blocks_non_whitelisted_internal():
    transport = AllowlistTransport()
    request = httpx.Request("GET", "http://10.102.80.15:8080/admin")
    with pytest.raises(PermissionError):
        await transport.handle_async_request(request)
