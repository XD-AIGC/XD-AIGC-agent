"""Restricted direct client for Mivo MCP 0.6.0.

This module mirrors the registered tools from mivo-mcp 0.6.0 while keeping the
agent on a narrow allowlist instead of exposing arbitrary MCP passthrough.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.config import MIVO_ENDPOINT, MIVO_MCP_ALLOWED_TOOLS, MIVO_USER_SUB
from src.http_client.allowlist import allowed_client
from src.skill.actions import SkillActionError, SkillActionObservation

_MESSAGE_PATH = "/api/v1/message"
_MESSAGE_CHAT_PATH = "/api/v1/message/chat"
_STATE_TOKEN_PATH = "/api/v1/state/token"
_FILE_UPLOAD_PATH = "/api/v1/file/"
_FILE_DOWNLOAD_PATH = "/api/v1/file/download/{file_id}"
_EXPORT_MODEL_PATH = "/api/v1/file/export-model"
_EXPORT_MODEL_TASK_PATH = "/api/v1/file/export-model/tasks/{task_id}"

_DEFAULT_IMAGE_MODEL_VERSION = "gemini-3-pro-image-preview"
_DEFAULT_RATIO = "1:1"
_DEFAULT_RESOLUTION = "1K"
_DEFAULT_3D_MODEL_TYPE = "TRIPO3D"
_DEFAULT_3D_MODEL_VERSION = "P1"

_MIVO_PACKAGE_VERSION = "mivo-mcp-0.6.0"

MIVO_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_tools": {
        "source": "agent_catalog",
        "description": "列出 agent 当前允许调用的 Mivo MCP 0.6.0 工具和 schema 映射。",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {"tools": "array", "image_input_mapping": "object"}},
    },
    "download_file": {
        "source": "mivo-mcp-0.6.0",
        "description": "从 Mivo 平台下载文件。图片会直接回传飞书；非图片目前只返回 fileId/contentType/byteCount。",
        "input_schema": {
            "type": "object",
            "required": ["fileId"],
            "properties": {
                "fileId": {"type": "string", "description": "Mivo 24 位文件 ObjectId"},
                "filename": {"type": "string", "optional": True},
                "savePath": {"type": "string", "optional": True},
            },
        },
        "output_schema": {"type": "object", "properties": {"fileId": "string", "contentType": "string"}},
    },
    "submit_gen_image": {
        "source": "mivo-mcp-0.6.0",
        "description": "提交图片生成任务。支持文生图和参考图生图。",
        "input_schema": {
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string"},
                "images": {
                    "type": "array",
                    "items": "string",
                    "optional": True,
                    "description": "Mivo fileId/mivo://image/{fileId}/Mivo URL；飞书图用 feishu://image/current",
                },
                "ratio": {
                    "type": "string",
                    "default": "1:1",
                    "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2", "4:5", "5:4", "1:4", "4:1", "1:8", "8:1", "21:9"],
                },
                "resolution": {"type": "string", "default": "1K", "enum": ["512", "1K", "2K", "4K"]},
                "quality": {"type": "string", "default": "auto", "enum": ["auto", "low", "medium", "high"]},
                "modelVersion": {
                    "type": "string",
                    "default": _DEFAULT_IMAGE_MODEL_VERSION,
                    "description": "gemini-3-pro-image-preview / gemini-3.1-flash-image-preview / gpt-image-2 aliases",
                },
            },
        },
        "output_schema": {"type": "object", "required": ["jobId"], "properties": {"jobId": "string"}},
    },
    "submit_gen_3d_model": {
        "source": "mivo-mcp-0.6.0",
        "description": "提交图生 3D 或文生 3D 任务，支持 TRIPO3D 和 ARK Seed3D。",
        "input_schema": {
            "type": "object",
            "oneOf": ["image", "referenceImages", "prompt"],
            "properties": {
                "modelType": {"type": "string", "default": "TRIPO3D", "enum": ["TRIPO3D", "ARK"]},
                "image": {"type": "string", "optional": True, "description": "单图输入；飞书图用 feishu://image/current"},
                "referenceImages": {
                    "type": "object",
                    "optional": True,
                    "required_when_used": ["front", "back"],
                    "properties": {"front": "string", "back": "string", "left": "string", "right": "string"},
                },
                "prompt": {"type": "string", "optional": True},
                "generateType": {"type": "string", "default": "PBR", "enum": ["PBR", "WHITE"]},
                "modelVersion": {"type": "string", "default": "P1", "description": "TRIPO3D P1/V3.1 或 ARK Seed3D_2_0 aliases"},
                "pbr": {"type": "boolean", "default": False},
                "quad": {"type": ["boolean", "string"], "optional": True},
                "modelFormat": {"type": "string", "optional": True, "enum": ["glb", "obj", "fbx"]},
                "fileformat": {"type": "string", "optional": True, "enum": ["glb", "obj", "usd", "usdz"]},
                "subdivisionlevel": {"type": "string", "optional": True, "enum": ["low", "medium", "high"]},
                "faceCount": {"type": ["number", "string"], "optional": True},
            },
        },
        "output_schema": {"type": "object", "required": ["jobId", "targetFormat"], "properties": {"jobId": "string", "targetFormat": "string"}},
    },
    "poll_result": {
        "source": "mivo-mcp-0.6.0",
        "description": "轮询图片/图像工具任务结果。",
        "input_schema": {
            "type": "object",
            "required": ["jobId"],
            "properties": {
                "jobId": {"type": "string"},
                "timeout": {"type": "number", "default": 30},
                "mode": {"type": "string", "default": "default", "enum": ["default", "gpt_wait"]},
            },
        },
        "output_schema": {"type": "object", "properties": {"jobId": "string", "status": "string", "images": "array", "message": "string"}},
    },
    "poll_3d_result": {
        "source": "mivo-mcp-0.6.0",
        "description": "轮询 3D 生成任务，完成后返回模型文件 fileId 列表。",
        "input_schema": {"type": "object", "required": ["jobId"], "properties": {"jobId": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"jobId": "string", "status": "string", "modelFiles": "array", "message": "string"}},
    },
    "convert_3d_model_format": {
        "source": "mivo-mcp-0.6.0",
        "description": "把 3D 模型任务结果转换为 GLB/OBJ/FBX。",
        "input_schema": {
            "type": "object",
            "required": ["originalModelTaskId", "format"],
            "properties": {
                "originalModelTaskId": {"type": "string"},
                "format": {"type": "string", "enum": ["GLB", "OBJ", "FBX"]},
                "wait": {"type": "boolean", "default": True},
                "timeoutSec": {"type": "number", "default": 180},
                "pollIntervalMs": {"type": "number", "default": 1500},
                "texture_size": {"type": "number", "optional": True},
                "pivot_to_center_bottom": {"type": "boolean", "optional": True},
                "fbx_preset": {"type": "string", "optional": True, "enum": ["blender", "3dsmax", "mixamo"]},
            },
        },
        "output_schema": {"type": "object", "properties": {"taskId": "string", "fileId": "string", "downloadUrl": "string", "status": "string"}},
    },
    "segment_image": {
        "source": "mivo-mcp-0.6.0",
        "description": "图片去背景/抠图。",
        "input_schema": {"type": "object", "required": ["image"], "properties": {"image": {"type": "string", "description": "Mivo fileId/mivo URI；飞书图用 feishu://image/current"}}},
        "output_schema": {"type": "object", "required": ["jobId"], "properties": {"jobId": "string"}},
    },
    "super_resolution_image": {
        "source": "mivo-mcp-0.6.0",
        "description": "图片超分辨率/放大，固定 scale=2。",
        "input_schema": {"type": "object", "required": ["image"], "properties": {"image": {"type": "string", "description": "Mivo fileId/mivo URI；飞书图用 feishu://image/current"}}},
        "output_schema": {"type": "object", "required": ["jobId"], "properties": {"jobId": "string"}},
    },
    "generate_image": {
        "source": "agent_macro",
        "description": "agent 宏工具：submit_gen_image -> poll_result -> download_file，直接把第一张图回传飞书。",
        "input_schema": "same_as submit_gen_image plus optional timeoutSec",
        "output_schema": {"type": "object", "properties": {"jobId": "string", "fileId": "string"}},
    },
}

MIVO_DISCOVERED_UNREGISTERED_TOOLS = [
    "submit_gen_video",
    "poll_video_result",
    "poll_export_model_result",
    "get_tapsvc_credential",
    "save_tapsvc_credential",
]

_chat_session_ids: dict[str, str] = {}
_session_token: dict[str, Any] | None = None


def format_mivo_mcp_catalog() -> str:
    allowed = sorted(_allowed_tool_patterns())
    registered = [
        name
        for name, schema in MIVO_TOOL_SCHEMAS.items()
        if schema.get("source") == "mivo-mcp-0.6.0"
    ]
    status = "已配置 MIVO_USER_SUB/state-token" if MIVO_USER_SUB else "未配置 MIVO_USER_SUB"
    return "\n".join(
        [
            "【Mivo MCP 全局工具】",
            f"- 运行配置：npx --package mivo-mcp@0.6.0 风格；endpoint={MIVO_ENDPOINT or '未配置'}；{status}。",
            "- 只能用 action=call_mivo_mcp 调白名单工具，不允许任意 URL / 任意 method。",
            f"- 0.6.0 注册工具：{', '.join(registered)}。",
            f"- agent 额外宏工具：generate_image（submit/poll/download 一步完成）。",
            f"- 当前白名单：{', '.join(allowed) or '无'}。",
            "- 飞书消息上传的图片可在 image/images/referenceImages 中用 feishu://image/current；系统会先上传到 Mivo 后替换为 fileId。",
            "- action_params 推荐格式：[{\"key\":\"arguments\",\"value_json\":\"{...}\"}]。",
        ]
    )


async def execute_mivo_mcp_action(
    action_name: str | None,
    action_params: dict[str, Any] | None,
) -> SkillActionObservation:
    if not action_name:
        raise SkillActionError("Mivo MCP action_name 不能为空")
    if not _tool_allowed(action_name):
        raise SkillActionError(f"Mivo MCP 工具不在白名单: {action_name}")

    if action_name == "list_tools":
        return _list_tools_observation()

    _ensure_configured()
    args = _extract_arguments(action_params or {})
    if action_name == "generate_image":
        return await _generate_image(args)
    if action_name == "submit_gen_image":
        return await _submit_gen_image(args)
    if action_name == "submit_gen_3d_model":
        return await _submit_gen_3d_model(args)
    if action_name == "poll_result":
        return await _poll_result(args)
    if action_name == "poll_3d_result":
        return await _poll_3d_result(args)
    if action_name == "convert_3d_model_format":
        return await _convert_3d_model_format(args)
    if action_name == "segment_image":
        return await _submit_image_tool(args, action="segment", source_name="segment_image")
    if action_name == "super_resolution_image":
        return await _submit_image_tool(args, action="super_resolution", source_name="super_resolution_image")
    if action_name == "download_file":
        return await _download_file(args)
    raise SkillActionError(f"未知 Mivo MCP 工具: {action_name}")


async def upload_image_bytes(filename: str, image_bytes: bytes, mime_type: str = "image/png") -> str:
    """Upload a Feishu image to Mivo and return its file ObjectId."""
    _ensure_configured()
    token = await _get_auth_token()
    safe_name = filename or "feishu-image.png"
    async with allowed_client() as client:
        resp = await client.post(
            _url(_FILE_UPLOAD_PATH),
            headers=_auth_headers(token),
            files={"file": (safe_name, image_bytes, mime_type)},
            timeout=60.0,
        )
    resp.raise_for_status()
    data = resp.json()
    meta = data[0] if isinstance(data, list) and data else data
    if not isinstance(meta, dict):
        raise SkillActionError(f"Mivo 上传响应格式异常: {str(data)[:300]}")
    file_id = meta.get("object_id") or meta.get("_id") or meta.get("fileId") or meta.get("id")
    if not isinstance(file_id, str) or not file_id:
        raise SkillActionError(f"Mivo 上传响应缺少 fileId: {str(data)[:300]}")
    return file_id


def _list_tools_observation() -> SkillActionObservation:
    tools = [
        {"name": name, **schema}
        for name, schema in MIVO_TOOL_SCHEMAS.items()
        if _tool_allowed(name)
    ]
    return SkillActionObservation(
        status="success",
        summary="Mivo MCP 0.6.0 工具目录已加载",
        data={
            "package": _MIVO_PACKAGE_VERSION,
            "tools": tools,
            "discovered_unregistered_tools": MIVO_DISCOVERED_UNREGISTERED_TOOLS,
            "image_input_mapping": {
                "feishu": "feishu://image/current -> upload /api/v1/file/ -> Mivo fileId",
                "mivo": "mivo://image/{fileId} / Mivo file URL / bare fileId",
            },
        },
        data_schema_id="mivo_mcp.tools",
        source_name="mivo_mcp:list_tools",
    )


async def _generate_image(args: dict[str, Any]) -> SkillActionObservation:
    submit_obs = await _submit_gen_image(args)
    if submit_obs.status != "success":
        return submit_obs
    job_id = str((submit_obs.data or {}).get("jobId") or "")
    poll_obs = await _poll_result({"jobId": job_id, "timeout": args.get("timeoutSec", 180)})
    if poll_obs.status != "success":
        return poll_obs
    file_id = _first_file_id(poll_obs.data)
    if not file_id:
        return SkillActionObservation(
            status="error",
            summary="Mivo 任务完成但没有返回图片 fileId",
            data=poll_obs.data,
            source_name="mivo_mcp:generate_image",
        )
    image_obs = await _download_file({"fileId": file_id})
    image_obs.summary = f"generate_image 生成完成并返回图片 fileId={file_id}"
    image_obs.data = {"jobId": job_id, "fileId": file_id}
    image_obs.source_name = "mivo_mcp:generate_image"
    return image_obs


async def _submit_gen_image(args: dict[str, Any]) -> SkillActionObservation:
    prompt = _required_str(args, "prompt")
    model_version = _normalize_image_model_version(args.get("modelVersion"))
    model_type = "GPT" if model_version == "gpt-image-2" else "NANOBANANA"
    payload = _build_generation_payload(prompt, args, model_version)
    job_id = await _create_message(
        payload=payload,
        chat_type="freeform",
        message_type="image",
        model_type=model_type,
        action="mcp",
        model_version=model_version,
    )
    return SkillActionObservation(
        status="success",
        summary=f"submit_gen_image 已提交 jobId={job_id}",
        data={"status": "submitted", "jobId": job_id},
        data_schema_id="mivo_mcp.job",
        source_name="mivo_mcp:submit_gen_image",
        next_actions=["poll_result"],
    )


async def _submit_image_tool(args: dict[str, Any], *, action: str, source_name: str) -> SkillActionObservation:
    image = _required_str(args, "image")
    file_ids = _normalize_images([image])
    if not file_ids:
        raise SkillActionError("Mivo 图片工具缺少 image")
    payload: dict[str, Any] = {"images": file_ids}
    if action == "super_resolution":
        payload["scale"] = 2
    job_id = await _create_message(
        payload=payload,
        chat_type="tool",
        message_type="image",
        model_type="ALICLOUD",
        action=action,
    )
    return SkillActionObservation(
        status="success",
        summary=f"{source_name} 已提交 jobId={job_id}",
        data={"status": "submitted", "jobId": job_id},
        data_schema_id="mivo_mcp.job",
        source_name=f"mivo_mcp:{source_name}",
        next_actions=["poll_result"],
    )


async def _submit_gen_3d_model(args: dict[str, Any]) -> SkillActionObservation:
    payload, model_type, model_version, target_format = _build_3d_payload(args)
    job_id = await _create_message(
        payload=payload,
        chat_type="model3d",
        message_type="model3d",
        model_type=model_type,
        action="generate_3d_model",
        model_version=model_version,
    )
    return SkillActionObservation(
        status="success",
        summary=f"submit_gen_3d_model 已提交 jobId={job_id} targetFormat={target_format}",
        data={"status": "submitted", "jobId": job_id, "targetFormat": target_format},
        data_schema_id="mivo_mcp.3d_job",
        source_name="mivo_mcp:submit_gen_3d_model",
        next_actions=["poll_3d_result"],
    )


async def _poll_result(args: dict[str, Any]) -> SkillActionObservation:
    job_id = _required_str(args, "jobId")
    timeout_sec = int(args.get("timeout") or args.get("timeoutSec") or 0)
    deadline = time.monotonic() + timeout_sec
    token = await _get_auth_token()
    while True:
        data = await _get_message(token, job_id)
        status = _message_status(data)
        if status == "completed":
            return _completed_poll_observation(job_id, data)
        if status == "failed":
            return SkillActionObservation(
                status="error",
                summary=f"poll_result 任务失败 jobId={job_id}",
                data=_poll_result_payload(job_id, data),
                source_name="mivo_mcp:poll_result",
            )
        if timeout_sec <= 0 or time.monotonic() >= deadline:
            return SkillActionObservation(
                status="warning",
                summary=f"poll_result 仍在处理中 jobId={job_id}",
                data={"status": status or "processing", "jobId": job_id},
                data_schema_id="mivo_mcp.job",
                source_name="mivo_mcp:poll_result",
                next_actions=["poll_result"],
            )
        await asyncio.sleep(3)


async def _poll_3d_result(args: dict[str, Any]) -> SkillActionObservation:
    job_id = _required_str(args, "jobId")
    token = await _get_auth_token()
    data = await _get_message(token, job_id)
    status = _message_status(data) or "processing"
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    model_files = _extract_file_ids(content.get("model_files", []))
    summary_status = "任务完成" if status == "completed" else f"任务状态 {status}"
    return SkillActionObservation(
        status="success" if status == "completed" else ("error" if status == "failed" else "warning"),
        summary=f"poll_3d_result {summary_status} jobId={job_id}",
        data={"jobId": job_id, "status": status, "modelFiles": model_files, "raw": data},
        data_schema_id="mivo_mcp.3d_result",
        source_name="mivo_mcp:poll_3d_result",
        next_actions=["download_file"] if status == "completed" and model_files else ["poll_3d_result"],
    )


async def _convert_3d_model_format(args: dict[str, Any]) -> SkillActionObservation:
    original_task_id = _required_str(args, "originalModelTaskId")
    fmt = _required_str(args, "format").upper()
    if fmt not in {"GLB", "OBJ", "FBX"}:
        raise SkillActionError("convert_3d_model_format format 只支持 GLB/OBJ/FBX")
    wait = bool(args.get("wait", True))
    timeout_sec = int(args.get("timeoutSec") or 180)
    interval_ms = int(args.get("pollIntervalMs") or 1500)
    token = await _get_auth_token()
    submit_payload = {"originalModelTaskId": original_task_id, "format": fmt}
    for key in ("texture_size", "pivot_to_center_bottom", "fbx_preset"):
        if key in args:
            submit_payload[key] = args[key]
    async with allowed_client() as client:
        resp = await client.post(_url(_EXPORT_MODEL_PATH), headers=_json_headers(token), json=submit_payload, timeout=30.0)
    resp.raise_for_status()
    submit_data = resp.json()
    task_id = submit_data.get("taskId") or submit_data.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise SkillActionError(f"Mivo export-model 响应缺少 taskId: {str(submit_data)[:300]}")
    if not wait:
        return SkillActionObservation(
            status="warning",
            summary=f"convert_3d_model_format 已提交 taskId={task_id}",
            data={"taskId": task_id, "status": "pending"},
            data_schema_id="mivo_mcp.export_model",
            source_name="mivo_mcp:convert_3d_model_format",
            next_actions=["convert_3d_model_format"],
        )
    deadline = time.monotonic() + timeout_sec
    data: dict[str, Any] = {"taskId": task_id, "status": "pending"}
    while time.monotonic() <= deadline:
        async with allowed_client() as client:
            poll = await client.get(_url(_EXPORT_MODEL_TASK_PATH.format(task_id=task_id)), headers=_auth_headers(token), timeout=30.0)
        poll.raise_for_status()
        data = poll.json()
        status = data.get("status")
        if status == "completed":
            return SkillActionObservation(
                status="success",
                summary=f"convert_3d_model_format 完成 taskId={task_id}",
                data={"taskId": task_id, **data},
                data_schema_id="mivo_mcp.export_model",
                source_name="mivo_mcp:convert_3d_model_format",
                next_actions=["download_file"] if data.get("fileId") else [],
            )
        if status == "failed":
            return SkillActionObservation(
                status="error",
                summary=f"convert_3d_model_format 失败 taskId={task_id}",
                data={"taskId": task_id, **data},
                source_name="mivo_mcp:convert_3d_model_format",
            )
        await asyncio.sleep(interval_ms / 1000)
    return SkillActionObservation(
        status="warning",
        summary=f"convert_3d_model_format 仍在处理中 taskId={task_id}",
        data={"taskId": task_id, **data},
        source_name="mivo_mcp:convert_3d_model_format",
        next_actions=["convert_3d_model_format"],
    )


async def _download_file(args: dict[str, Any]) -> SkillActionObservation:
    file_id = _required_str(args, "fileId")
    token = await _get_auth_token()
    async with allowed_client() as client:
        resp = await client.get(_url(_FILE_DOWNLOAD_PATH.format(file_id=file_id)), headers=_auth_headers(token), timeout=60.0)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    data = {"fileId": file_id, "contentType": content_type, "byteCount": len(resp.content)}
    if not content_type or content_type.startswith("image/"):
        return SkillActionObservation(
            status="success",
            summary=f"download_file 返回图片 fileId={file_id} ({len(resp.content)} bytes)",
            data=data,
            data_schema_id="image.binary",
            source_name="mivo_mcp:download_file",
            artifact={"kind": "image_binary", "source": "mivo_mcp"},
            content_bytes=resp.content,
        )
    return SkillActionObservation(
        status="success",
        summary=f"download_file 已下载非图片文件 fileId={file_id} contentType={content_type}",
        data=data,
        data_schema_id="mivo_mcp.file",
        source_name="mivo_mcp:download_file",
    )


async def _create_message(
    *,
    payload: dict[str, Any],
    chat_type: str,
    message_type: str,
    model_type: str,
    action: str,
    model_version: str | None = None,
) -> str:
    token = await _get_auth_token()
    session_id = await _get_chat_session(token, chat_type)
    body: dict[str, Any] = {
        "chatSessionId": session_id,
        "messageType": message_type,
        "modelType": model_type,
        "action": action,
        "payload": payload,
    }
    if model_version:
        body["modelFormat"] = {"version": model_version}
    async with allowed_client() as client:
        resp = await client.post(_url(_MESSAGE_PATH), headers=_json_headers(token), json=body, timeout=30.0)
    resp.raise_for_status()
    job_id = resp.json().get("object_id")
    if not isinstance(job_id, str) or not job_id:
        raise SkillActionError(f"Mivo submit 响应缺少 object_id: {resp.text[:300]}")
    return job_id


async def _get_message(token: str, job_id: str) -> dict[str, Any]:
    async with allowed_client() as client:
        resp = await client.get(_url(f"{_MESSAGE_PATH}/{job_id}"), headers=_auth_headers(token), timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def _completed_poll_observation(job_id: str, data: dict[str, Any]) -> SkillActionObservation:
    file_ids = _extract_file_ids(data.get("content", {}).get("images", []))
    image_uris = [f"mivo://image/{file_id}" for file_id in file_ids]
    return SkillActionObservation(
        status="success",
        summary=f"poll_result 任务完成 jobId={job_id}",
        data={"status": "completed", "jobId": job_id, "images": image_uris, "fileIds": file_ids, "raw": data},
        data_schema_id="mivo_mcp.result",
        source_name="mivo_mcp:poll_result",
        next_actions=["download_file"] if file_ids else [],
    )


def _poll_result_payload(job_id: str, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    return {"jobId": job_id, "status": content.get("status"), "message": data.get("error") or content.get("error") or "", "raw": data}


def _build_generation_payload(prompt: str, args: dict[str, Any], model_version: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": prompt,
        "imgRatio": args.get("ratio") or args.get("imgRatio") or _DEFAULT_RATIO,
        "modelVersion": model_version,
        "n": 1,
    }
    images = _normalize_images(args.get("images") or args.get("fileIds") or [])
    if images:
        payload["images"] = images
    if model_version == "gpt-image-2":
        payload["quality"] = _normalize_quality(args.get("quality") or "auto")
        return payload
    payload["resolution"] = args.get("resolution") or _DEFAULT_RESOLUTION
    payload["provider"] = "genai"
    return payload


def _build_3d_payload(args: dict[str, Any]) -> tuple[dict[str, Any], str, str, str]:
    model_type, model_version = _normalize_3d_model_route(args)
    target_format = _detect_3d_target_format(args, model_type)
    generate_type = str(args.get("generateType") or "PBR").upper()
    if generate_type not in {"PBR", "WHITE"}:
        raise SkillActionError("submit_gen_3d_model generateType 只支持 PBR/WHITE")
    pbr = bool(args.get("pbr", False)) if generate_type != "WHITE" else False
    payload: dict[str, Any] = {"generateType": generate_type, "pbr": pbr, "resolution": "high"}
    if "quad" in args:
        payload["quad"] = args["quad"]
    if "faceCount" in args:
        payload["faceCount"] = args["faceCount"]
    if model_type == "ARK":
        image = _required_str(args, "image")
        payload = {"images": _normalize_images([image])}
        for key in ("fileformat", "subdivisionlevel", "faceCount"):
            if key in args:
                payload["faceCount" if key == "subdivisionlevel" else key] = args[key]
        return payload, model_type, model_version, target_format
    if isinstance(args.get("prompt"), str) and args["prompt"].strip():
        payload["prompt"] = args["prompt"].strip()
    elif isinstance(args.get("referenceImages"), dict):
        ref = args["referenceImages"]
        front = _required_ref_image(ref, "front")
        back = _required_ref_image(ref, "back")
        ordered = [front, ref.get("left") or "", back, ref.get("right") or ""]
        parsed = _normalize_images([item for item in ordered if item])
        values = list(parsed)
        payload["images"] = [values.pop(0) if item else "" for item in ordered]
    elif isinstance(args.get("image"), str) and args["image"].strip():
        payload["images"] = _normalize_images([args["image"]])
    else:
        raise SkillActionError("submit_gen_3d_model 必须提供 image、referenceImages 或 prompt")
    if "modelFormat" in args:
        payload["modelFormat"] = args["modelFormat"]
    return payload, model_type, model_version, target_format


def _normalize_images(raw: Any) -> list[str]:
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    images: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        value = value.strip()
        if value.startswith("feishu://"):
            raise SkillActionError("feishu:// 图片必须先由 agent 上传到 Mivo 后再调用工具")
        if value.startswith(("http://", "https://")) and not _is_mivo_url(value):
            raise SkillActionError("Mivo MCP 不接受非 Mivo 直链；请先上传为 Mivo fileId 再传 images")
        images.append(_extract_file_id(value))
    return images


def _normalize_image_model_version(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return _DEFAULT_IMAGE_MODEL_VERSION
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"gpt", "gpt2", "gpt-2", "gpt 2", "gpt 2.0", "gpt-image-2", "gpt-image-2.0"}:
        return "gpt-image-2"
    if normalized in {"gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"}:
        return normalized
    raise SkillActionError(f"不支持的 Mivo 图片 modelVersion: {value}")


def _normalize_quality(value: Any) -> str:
    if not isinstance(value, str):
        return "auto"
    normalized = value.strip().lower()
    aliases = {"高": "high", "高清": "high", "中": "medium", "低": "low", "自动": "auto"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"auto", "low", "medium", "high"}:
        raise SkillActionError("gpt-image-2 quality 只支持 auto/low/medium/high")
    return normalized


def _normalize_3d_model_route(args: dict[str, Any]) -> tuple[str, str]:
    model_type = str(args.get("modelType") or _DEFAULT_3D_MODEL_TYPE).strip()
    model_version = str(args.get("modelVersion") or _DEFAULT_3D_MODEL_VERSION).strip()
    normalized_alias = (model_type + " " + model_version).lower().replace(" ", "").replace("_", "").replace("-", "")
    if "seed3d" in normalized_alias or "即梦3d" in normalized_alias:
        return "ARK", "Seed3D_2_0"
    model_type_upper = model_type.upper()
    if model_type_upper == "ARK":
        return "ARK", "Seed3D_2_0"
    if model_type_upper != "TRIPO3D":
        raise SkillActionError("submit_gen_3d_model modelType 只支持 TRIPO3D/ARK")
    normalized_version = model_version.lower()
    if normalized_version in {"p1"}:
        return "TRIPO3D", "P1"
    if normalized_version in {"3.1", "v3.1", "v3_1"}:
        return "TRIPO3D", "V3.1"
    raise SkillActionError("TRIPO3D modelVersion 只支持 P1/V3.1")


def _detect_3d_target_format(args: dict[str, Any], model_type: str) -> str:
    key = "fileformat" if model_type == "ARK" else "modelFormat"
    value = str(args.get(key) or "glb").upper()
    if value == "USDZ":
        return "USDZ"
    if value == "USD":
        return "USD"
    if value == "OBJ":
        return "OBJ"
    if value == "FBX":
        return "FBX"
    return "GLB"


def _required_ref_image(ref: dict[str, Any], key: str) -> str:
    value = ref.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillActionError(f"referenceImages.{key} 必填")
    return value.strip()


async def _get_auth_token() -> str:
    return await _get_state_token()


async def _get_state_token(force: bool = False) -> str:
    global _session_token
    if (
        not force
        and _session_token
        and isinstance(_session_token.get("session"), str)
        and time.time() < float(_session_token.get("expires_at", 0))
    ):
        return str(_session_token["session"])

    async with allowed_client() as client:
        resp = await client.post(
            _url(_STATE_TOKEN_PATH),
            headers={"Content-Type": "application/json"},
            json={"id": "", "sub": MIVO_USER_SUB, "name": ""},
            timeout=15.0,
        )
    resp.raise_for_status()
    data = resp.json()
    session = data.get("session")
    if not isinstance(session, str) or not session:
        raise SkillActionError("Mivo state/token 响应缺少 session")
    _session_token = {
        "session": session,
        "session_id": data.get("session_id"),
        "expires_at": time.time() + 29 * 24 * 3600,
    }
    return session


async def _get_chat_session(token: str, chat_type: str) -> str:
    if chat_type in _chat_session_ids:
        return _chat_session_ids[chat_type]
    async with allowed_client() as client:
        resp = await client.post(_url(_MESSAGE_CHAT_PATH), headers=_json_headers(token), json={"type": chat_type}, timeout=15.0)
    resp.raise_for_status()
    chat_session_id = resp.json().get("object_id")
    if not isinstance(chat_session_id, str) or not chat_session_id:
        raise SkillActionError("Mivo chat 响应缺少 object_id")
    _chat_session_ids[chat_type] = chat_session_id
    return chat_session_id


def _message_status(data: dict[str, Any]) -> str | None:
    content = data.get("content")
    if isinstance(content, dict):
        status = content.get("status")
        if isinstance(status, str):
            return status
    return None


def _extract_file_ids(images: Any) -> list[str]:
    if not isinstance(images, list):
        return []
    file_ids: list[str] = []
    for item in images:
        if isinstance(item, str):
            file_ids.append(_extract_file_id(item))
        elif isinstance(item, dict):
            file_ids.append(str(item.get("object_id") or item.get("_id") or item.get("fileId") or ""))
    return [item for item in file_ids if item]


def _extract_file_id(value: str) -> str:
    if value.startswith("mivo://image/"):
        return value.removeprefix("mivo://image/")
    if "/" in value:
        return value.rstrip("/").split("/")[-1]
    return value


def _first_file_id(data: Any) -> str | None:
    if isinstance(data, dict):
        values = data.get("fileIds")
        if isinstance(values, list) and values:
            return str(values[0])
        images = data.get("images")
        if isinstance(images, list) and images:
            return _extract_file_id(str(images[0]))
        value = data.get("fileId")
        if isinstance(value, str) and value:
            return value
    return None


def _extract_arguments(params: dict[str, Any]) -> dict[str, Any]:
    arguments = params.get("arguments")
    if arguments is None:
        arguments = params
    if not isinstance(arguments, dict):
        raise SkillActionError("Mivo MCP arguments 必须是对象")
    return arguments


def _required_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillActionError(f"Mivo MCP 缺少必填参数: {key}")
    return value.strip()


def _ensure_configured() -> None:
    if not MIVO_ENDPOINT:
        raise SkillActionError("Mivo MCP 未配置 MIVO_ENDPOINT")
    if not MIVO_USER_SUB:
        raise SkillActionError("Mivo MCP 未配置 MIVO_USER_SUB")


def _tool_allowed(name: str) -> bool:
    return name in _allowed_tool_patterns()


def _allowed_tool_patterns() -> set[str]:
    return {item.strip() for item in (MIVO_MCP_ALLOWED_TOOLS or "").split(",") if item.strip()}


def _is_mivo_url(value: str) -> bool:
    endpoint = MIVO_ENDPOINT.rstrip("/")
    return value.startswith(endpoint) or value.startswith("https://aigc.xindong.com/")


def _url(path: str) -> str:
    return MIVO_ENDPOINT.rstrip("/") + path


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _json_headers(token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", **_auth_headers(token)}
