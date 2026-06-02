from unittest.mock import AsyncMock, patch

import httpx
import pytest

import src.mivo_mcp.client as mivo_client
from src.mivo_mcp.client import execute_mivo_mcp_action
from src.skill.actions import SkillActionError


def _resp(status: int, json_data=None, content: bytes = b"") -> httpx.Response:
    req = httpx.Request("POST", "https://aigc.xindong.com/")
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=req)
    return httpx.Response(status, content=content, request=req)


@pytest.fixture(autouse=True)
def _reset_mivo_state(monkeypatch):
    monkeypatch.setattr(mivo_client, "MIVO_USER_SUB", "mivo_user_sub_test")
    monkeypatch.setattr(
        mivo_client,
        "MIVO_MCP_ALLOWED_TOOLS",
        "list_tools,generate_image,submit_gen_image,submit_gen_3d_model,poll_result,poll_3d_result,convert_3d_model_format,segment_image,super_resolution_image,download_file",
    )
    mivo_client._chat_session_ids = {}
    mivo_client._session_token = None


@pytest.mark.asyncio
async def test_mivo_mcp_list_tools_uses_static_allowlist():
    obs = await execute_mivo_mcp_action("list_tools", {})

    assert obs.status == "success"
    names = [item["name"] for item in obs.data["tools"]]
    assert names == [
        "list_tools",
        "download_file",
        "submit_gen_image",
        "submit_gen_3d_model",
        "poll_result",
        "poll_3d_result",
        "convert_3d_model_format",
        "segment_image",
        "super_resolution_image",
        "generate_image",
    ]
    assert "submit_gen_video" in obs.data["discovered_unregistered_tools"]
    assert obs.data["image_input_mapping"]["feishu"].startswith("feishu://image/current")


@pytest.mark.asyncio
async def test_mivo_mcp_rejects_disallowed_tool(monkeypatch):
    monkeypatch.setattr(mivo_client, "MIVO_MCP_ALLOWED_TOOLS", "list_tools")

    with pytest.raises(SkillActionError, match="不在白名单"):
        await execute_mivo_mcp_action("submit_gen_image", {"arguments": {"prompt": "test"}})


@pytest.mark.asyncio
async def test_mivo_submit_gen_image_calls_action_mcp():
    with patch("src.mivo_mcp.client.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.post = AsyncMock(
            side_effect=[
                _resp(200, {"session": "session_token", "session_id": "session_1"}),
                _resp(200, {"object_id": "chat_1"}),
                _resp(200, {"object_id": "job_1"}),
            ]
        )
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_mivo_mcp_action(
            "submit_gen_image",
            {"arguments": {"prompt": "小镇野餐", "ratio": "3:2", "resolution": "2K"}},
        )

    assert obs.status == "success"
    assert obs.data == {"status": "submitted", "jobId": "job_1"}
    _, kwargs = async_cli.post.await_args
    body = kwargs["json"]
    assert body["action"] == "mcp"
    assert body["modelType"] == "NANOBANANA"
    assert body["payload"]["prompt"] == "小镇野餐"
    assert body["payload"]["imgRatio"] == "3:2"
    assert body["payload"]["provider"] == "genai"
    token_call = async_cli.post.await_args_list[0]
    assert token_call.kwargs["json"] == {"id": "", "sub": "mivo_user_sub_test", "name": ""}
    submit_call = async_cli.post.await_args_list[-1]
    assert submit_call.kwargs["headers"]["Authorization"] == "Bearer session_token"


@pytest.mark.asyncio
async def test_mivo_poll_result_completed_extracts_file_ids():
    mivo_client._session_token = {"session": "session_token", "expires_at": 9999999999}
    with patch("src.mivo_mcp.client.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.get = AsyncMock(
            return_value=_resp(
                200,
                {"content": {"status": "completed", "images": ["mivo://image/file_1"]}},
            )
        )
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_mivo_mcp_action("poll_result", {"arguments": {"jobId": "job_1"}})

    assert obs.status == "success"
    assert obs.data["fileIds"] == ["file_1"]
    assert obs.next_actions == ["download_file"]


@pytest.mark.asyncio
async def test_mivo_download_file_returns_image_bytes():
    mivo_client._session_token = {"session": "session_token", "expires_at": 9999999999}
    with patch("src.mivo_mcp.client.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.get = AsyncMock(return_value=_resp(200, content=b"PNG"))
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_mivo_mcp_action("download_file", {"arguments": {"fileId": "file_1"}})

    assert obs.status == "success"
    assert obs.content_bytes == b"PNG"
    assert obs.data["fileId"] == "file_1"


@pytest.mark.asyncio
async def test_mivo_upload_image_bytes_uses_file_endpoint():
    mivo_client._session_token = {"session": "session_token", "expires_at": 9999999999}
    with patch("src.mivo_mcp.client.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.post = AsyncMock(return_value=_resp(200, [{"object_id": "file_1"}]))
        mock_cli.return_value.__aenter__.return_value = async_cli

        file_id = await mivo_client.upload_image_bytes("input.png", b"PNG", "image/png")

    assert file_id == "file_1"
    _, kwargs = async_cli.post.await_args
    assert "files" in kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer session_token"


@pytest.mark.asyncio
async def test_mivo_segment_image_calls_tool_channel():
    mivo_client._session_token = {"session": "session_token", "expires_at": 9999999999}
    with patch("src.mivo_mcp.client.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.post = AsyncMock(
            side_effect=[
                _resp(200, {"object_id": "chat_tool"}),
                _resp(200, {"object_id": "job_1"}),
            ]
        )
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_mivo_mcp_action("segment_image", {"arguments": {"image": "mivo://image/file_1"}})

    assert obs.status == "success"
    submit_call = async_cli.post.await_args_list[-1]
    body = submit_call.kwargs["json"]
    assert body["messageType"] == "image"
    assert body["modelType"] == "ALICLOUD"
    assert body["action"] == "segment"
    assert body["payload"] == {"images": ["file_1"]}


@pytest.mark.asyncio
async def test_mivo_submit_3d_model_calls_model3d_channel():
    mivo_client._session_token = {"session": "session_token", "expires_at": 9999999999}
    with patch("src.mivo_mcp.client.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.post = AsyncMock(
            side_effect=[
                _resp(200, {"object_id": "chat_3d"}),
                _resp(200, {"object_id": "job_3d"}),
            ]
        )
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_mivo_mcp_action("submit_gen_3d_model", {"arguments": {"image": "file_1", "modelFormat": "glb"}})

    assert obs.status == "success"
    assert obs.data["targetFormat"] == "GLB"
    submit_call = async_cli.post.await_args_list[-1]
    body = submit_call.kwargs["json"]
    assert body["messageType"] == "model3d"
    assert body["modelType"] == "TRIPO3D"
    assert body["action"] == "generate_3d_model"
    assert body["payload"]["images"] == ["file_1"]
