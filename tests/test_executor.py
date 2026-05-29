"""测试 SkillBackend executor 分发 + path 提取。"""
import pytest
from unittest.mock import AsyncMock, patch
import httpx

from src.skill.executor import _extract_by_path, _execute_http, _execute_poll, poll_existing_job, SkillExecutionError, execute
from src.skill.schema import Skill, HttpBackend, PollBackend, SkillOutput


def _resp(status: int, content: bytes = b"", json_data=None) -> httpx.Response:
    """构造带 request 的 mock Response，避免 raise_for_status 报错。"""
    req = httpx.Request("GET", "http://test/")
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=req)
    return httpx.Response(status, content=content, request=req)


# ---- _extract_by_path ----

def test_path_simple_key():
    assert _extract_by_path({"a": 1}, "a") == 1


def test_path_nested_dict():
    assert _extract_by_path({"a": {"b": 2}}, "a.b") == 2


def test_path_array_index():
    assert _extract_by_path({"images": [{"url": "x"}, {"url": "y"}]}, "images[0].url") == "x"
    assert _extract_by_path({"images": [{"url": "x"}, {"url": "y"}]}, "images[1].url") == "y"


def test_path_deep():
    assert _extract_by_path({"a": [{"b": [10, 20]}]}, "a[0].b[1]") == 20


# ---- HTTP backend ----

def _http_skill() -> Skill:
    return Skill(
        name="t", description="d",
        api=HttpBackend(type="http", endpoint_path="/x", method="POST", content_type="application/json"),
        params=[],
        output=SkillOutput(type="image_binary", display_as="feishu_image"),
    )


@pytest.mark.asyncio
async def test_http_backend_returns_binary():
    mock_resp = _resp(200, content=b"PNG_BYTES")
    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=mock_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli
        result = await _execute_http(_http_skill(), {"k": "v"})
    assert result.kind == "binary"
    assert result.content_bytes == b"PNG_BYTES"


# ---- Poll backend ----

def _poll_skill() -> Skill:
    return Skill(
        name="t", description="d",
        api=PollBackend(
            type="poll",
            submit_path="/submit",
            poll_path_template="/poll/{job_id}",
            poll_interval_sec=0,
            poll_timeout_sec=5,
        ),
        params=[],
        output=SkillOutput(type="image_url", display_as="feishu_image"),
    )


@pytest.mark.asyncio
async def test_poll_backend_success_first_try():
    submit_resp = _resp(200, json_data={"v2JobId": "abc"})
    poll_resp = _resp(200, json_data={"status": "completed", "images": [{"url": "http://x/result.png"}]})

    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=submit_resp)
        async_cli.get = AsyncMock(return_value=poll_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli
        result = await _execute_poll(_poll_skill(), {"k": "v"})
    assert result.kind == "url"
    assert result.result_url == "http://x/result.png"


@pytest.mark.asyncio
async def test_poll_existing_job_skips_submit():
    poll_resp = _resp(200, json_data={"status": "completed", "images": [{"url": "http://x/result.png"}]})

    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.get = AsyncMock(return_value=poll_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli
        result = await poll_existing_job(_poll_skill(), "abc")
    assert result.kind == "url"
    assert result.result_url == "http://x/result.png"
    async_cli.get.assert_awaited_once()
    assert str(async_cli.get.await_args.args[0]).endswith("/poll/abc")


@pytest.mark.asyncio
async def test_poll_existing_job_treats_read_timeout_as_pending():
    poll_resp = _resp(200, json_data={"status": "completed", "images": [{"url": "http://x/result.png"}]})

    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.get = AsyncMock(side_effect=[
            httpx.ReadTimeout("slow poll response"),
            poll_resp,
        ])
        mock_cli.return_value.__aenter__.return_value = async_cli
        result = await poll_existing_job(_poll_skill(), "abc")
    assert result.kind == "url"
    assert result.result_url == "http://x/result.png"
    assert async_cli.get.await_count == 2


@pytest.mark.asyncio
async def test_poll_existing_job_does_not_hide_non_read_timeouts():
    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.get = AsyncMock(side_effect=httpx.ConnectTimeout("cannot connect"))
        mock_cli.return_value.__aenter__.return_value = async_cli
        with pytest.raises(httpx.ConnectTimeout):
            await poll_existing_job(_poll_skill(), "abc")


@pytest.mark.asyncio
async def test_poll_backend_failed_status():
    submit_resp = _resp(200, json_data={"v2JobId": "abc"})
    poll_resp = _resp(200, json_data={"status": "failed", "error": "Mivo rate limit"})

    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=submit_resp)
        async_cli.get = AsyncMock(return_value=poll_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli
        with pytest.raises(SkillExecutionError, match="任务失败.*Mivo"):
            await _execute_poll(_poll_skill(), {"k": "v"})


@pytest.mark.asyncio
async def test_poll_backend_missing_job_id():
    submit_resp = _resp(200, json_data={"oops": "no job id"})

    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=submit_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli
        with pytest.raises(SkillExecutionError, match="缺 job_id"):
            await _execute_poll(_poll_skill(), {"k": "v"})


# ---- 公共入口分发 ----

@pytest.mark.asyncio
async def test_execute_dispatches_to_http_for_HttpBackend():
    mock_resp = _resp(200, content=b"X")
    with patch("src.skill.executor.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=mock_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli
        result = await execute(_http_skill(), {})
    assert result.kind == "binary"
