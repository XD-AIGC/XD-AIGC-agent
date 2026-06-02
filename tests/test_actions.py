import json

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.skill.actions import build_action_catalog, execute_skill_action
from src.skill.schema import HttpBackend, PollBackend, Skill, SkillActionMetadata, SkillOutput


SKILL_MD = """
## Asset Discovery

```http
GET /api/characters?refresh=1
POST /api/generate-step1-only
GET /api/image/{fileId}
GET https://artdam.xindong.com/api/publish-space/assets/by-public-id/{public_id}/download
```
"""


def _skill() -> Skill:
    return Skill(
        name="poster",
        description="poster",
        api=PollBackend(
            type="poll",
            base_url="http://localhost:8090",
            submit_path="/api/generate-v2",
            poll_path_template="/api/poll-v2/{job_id}",
        ),
        params=[],
        output=SkillOutput(type="image_url", display_as="feishu_image"),
        system_prompt_core=SKILL_MD,
    )


def _skill_with_action_schema() -> Skill:
    return Skill(
        name="poster",
        description="poster",
        api=HttpBackend(
            type="http",
            base_url="http://localhost:8090",
            endpoint_path="/api/submit",
            method="POST",
            content_type="application/json",
        ),
        params=[],
        output=SkillOutput(type="text", display_as="feishu_text"),
        system_prompt_core="```http\nGET /api/styles\n```",
        actions=[SkillActionMetadata(name="get_styles", data_schema_id="poster.styles")],
    )


def _resp(status: int, json_data=None, content: bytes = b"", content_type: str = "application/json") -> httpx.Response:
    req = httpx.Request("GET", "http://localhost:8090/")
    headers = {"content-type": content_type}
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=req, headers=headers)
    return httpx.Response(status, content=content, request=req, headers=headers)


def test_build_action_catalog_extracts_relative_http_blocks_only():
    catalog = build_action_catalog(_skill())

    assert "list_characters" in catalog
    assert "generate_step1_only" in catalog
    assert "get_image" in catalog
    assert "manifest_submit" in catalog
    assert "manifest_poll" in catalog
    assert all("artdam" not in action.path_template for action in catalog.values())


def test_build_action_catalog_applies_manifest_data_schema_id():
    catalog = build_action_catalog(_skill_with_action_schema())

    assert catalog["get_styles"].data_schema_id == "poster.styles"


def test_build_action_catalog_warns_for_unknown_manifest_action(caplog):
    skill = _skill_with_action_schema().model_copy(
        update={"actions": [SkillActionMetadata(name="get_style", data_schema_id="poster.styles")]}
    )
    caplog.set_level("WARNING", logger="src.skill.actions")

    catalog = build_action_catalog(skill)

    assert catalog["get_styles"].data_schema_id is None
    assert (
        "[SKILL] manifest action 'get_style' not in SKILL.md HTTP blocks for skill=poster"
        in caplog.text
    )


@pytest.mark.asyncio
async def test_execute_skill_action_posts_json_to_allowed_action():
    mock_resp = _resp(200, json_data={"status": "completed", "fileId": "6a"})
    with patch("src.skill.actions.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=mock_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_skill_action(
            _skill(),
            "generate_step1_only",
            {"json": {"actionDesc": "读书", "characters": ["atara"]}},
        )

    assert obs.status == "success"
    assert obs.data == {"status": "completed", "fileId": "6a"}
    assert json.loads(obs.for_prompt())["data"]["schema_id"] == "image.fileId"
    async_cli.request.assert_awaited_once()
    args, kwargs = async_cli.request.await_args
    assert args[:2] == ("POST", "http://localhost:8090/api/generate-step1-only")
    assert kwargs["json"] == {"actionDesc": "读书", "characters": ["atara"]}


@pytest.mark.asyncio
async def test_execute_skill_action_renders_path_params_safely():
    mock_resp = _resp(200, content=b"PNG", content_type="image/png")
    with patch("src.skill.actions.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=mock_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_skill_action(_skill(), "get_image", {"path_params": {"fileId": "a/b"}})

    assert obs.status == "success"
    assert obs.content_bytes == b"PNG"
    assert obs.data_schema_id == "image.binary"
    args, _ = async_cli.request.await_args
    assert args[:2] == ("GET", "http://localhost:8090/api/image/a%2Fb")


@pytest.mark.asyncio
async def test_execute_skill_action_rejects_unknown_action():
    with pytest.raises(Exception, match="未知或未允许"):
        await execute_skill_action(_skill(), "curl_anything", {})


@pytest.mark.asyncio
async def test_execute_skill_action_uses_manifest_data_schema_id():
    mock_resp = _resp(200, json_data=[{"style": "comic"}])
    with patch("src.skill.actions.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=mock_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_skill_action(_skill_with_action_schema(), "get_styles", {})

    assert obs.data_schema_id == "poster.styles"
    assert json.loads(obs.for_prompt())["data"] == {
        "schema_id": "poster.styles",
        "payload": {"items": [{"style": "comic"}]},
    }


@pytest.mark.asyncio
async def test_execute_skill_action_treats_application_failure_as_error():
    mock_resp = _resp(200, json_data={"status": "failed", "error": "Mivo rate limit"})
    with patch("src.skill.actions.allowed_client") as mock_cli:
        async_cli = AsyncMock()
        async_cli.request = AsyncMock(return_value=mock_resp)
        mock_cli.return_value.__aenter__.return_value = async_cli

        obs = await execute_skill_action(
            _skill(),
            "generate_step1_only",
            {"json": {"actionDesc": "读书", "characters": ["atara"]}},
        )

    assert obs.status == "error"
    assert "失败" in obs.summary
    assert json.loads(obs.for_prompt())["stop_condition"] == "do not retry the same action without changed parameters"
