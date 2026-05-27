"""Skill executor 按 backend type 分发。

返回值统一：`ExecuteResult`
  - kind="binary"  → content_bytes 是图像字节（HttpBackend 返图）
  - kind="url"     → result_url 是图像 URL（PollBackend 返结果 URL）
  - kind="text"    → text 是文本结果
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.config import TOOLBOX_BASE_URL
from src.http_client.allowlist import allowed_client
from src.skill.schema import HttpBackend, PollBackend, Skill

log = logging.getLogger(__name__)


@dataclass
class ExecuteResult:
    kind: str  # "binary" | "url" | "text"
    content_bytes: Optional[bytes] = None
    result_url: Optional[str] = None
    text: Optional[str] = None
    # poll backend 完成时塞完整 poll_data，供调用方提取 intermediateImages 等额外字段
    metadata: dict = field(default_factory=dict)


class SkillExecutionError(Exception):
    """Skill 执行失败时抛，message 适合直接回给用户。"""


# ---- 通用工具 ----

def _full_url(api, path: str) -> str:
    """优先用 backend 自带的 base_url（每个 skill 独立后端），回退 TOOLBOX_BASE_URL。"""
    base = getattr(api, "base_url", None) or TOOLBOX_BASE_URL
    return base.rstrip("/") + path


_PATH_SEG_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _extract_by_path(data: Any, path: str) -> Any:
    """从 nested dict/list 按 'images[0].url' 风格路径取值。"""
    cur = data
    for key_match, idx_match in _PATH_SEG_RE.findall(path):
        if idx_match:
            cur = cur[int(idx_match)]
        else:
            cur = cur[key_match]
    return cur


# ---- HTTP 单次调用 ----

async def _execute_http(skill: Skill, params: dict) -> ExecuteResult:
    api: HttpBackend = skill.api  # type: ignore[assignment]
    url = _full_url(api, api.endpoint_path)
    async with allowed_client() as client:
        if api.content_type == "multipart/form-data":
            resp = await client.request(api.method, url, files=params)
        else:
            resp = await client.request(api.method, url, json=params)
        resp.raise_for_status()
        return ExecuteResult(kind="binary", content_bytes=resp.content)


# ---- Poll 异步任务 ----

async def _poll_existing(api: PollBackend, job_id: str) -> ExecuteResult:
    deadline = asyncio.get_event_loop().time() + api.poll_timeout_sec
    poll_url = _full_url(api, api.poll_path_template.format(job_id=job_id))

    async with allowed_client() as client:
        while True:
            if asyncio.get_event_loop().time() > deadline:
                raise SkillExecutionError(f"任务 {job_id} 轮询超时（{api.poll_timeout_sec}s）")
            await asyncio.sleep(api.poll_interval_sec)
            poll_resp = await client.get(poll_url)
            poll_resp.raise_for_status()
            poll_data = poll_resp.json()
            status = poll_data.get(api.status_field)
            log.info(f"[POLL] {job_id} status={status}")
            if status == api.failed_value:
                err = poll_data.get(api.error_field, "未知错误")
                raise SkillExecutionError(f"任务失败：{err}")
            if status == api.done_value:
                try:
                    result_url = _extract_by_path(poll_data, api.result_path)
                except (KeyError, IndexError, TypeError) as e:
                    raise SkillExecutionError(f"完成但取结果失败 (path={api.result_path}): {e}")
                return ExecuteResult(kind="url", result_url=result_url, metadata=poll_data)


async def _execute_poll(skill: Skill, params: dict) -> ExecuteResult:
    api: PollBackend = skill.api  # type: ignore[assignment]
    submit_url = _full_url(api, api.submit_path)
    async with allowed_client() as client:
        if api.submit_content_type == "multipart/form-data":
            submit_resp = await client.request(api.submit_method, submit_url, files=params)
        else:
            submit_resp = await client.request(api.submit_method, submit_url, json=params)
        submit_resp.raise_for_status()
        submit_data = submit_resp.json()
    job_id = submit_data.get(api.job_id_field)
    if not job_id:
        raise SkillExecutionError(f"submit 成功但缺 job_id 字段 '{api.job_id_field}'")
    log.info(f"[POLL] submitted, job_id={job_id}")
    return await _poll_existing(api, job_id)


async def poll_existing_job(skill: Skill, job_id: str) -> ExecuteResult:
    if not isinstance(skill.api, PollBackend):
        raise SkillExecutionError(f"skill {skill.name} 不是 poll backend")
    return await _poll_existing(skill.api, job_id)


# ---- 公共入口 ----

async def execute(skill: Skill, params: dict) -> ExecuteResult:
    if isinstance(skill.api, HttpBackend):
        return await _execute_http(skill, params)
    if isinstance(skill.api, PollBackend):
        return await _execute_poll(skill, params)
    raise SkillExecutionError(f"unknown backend type: {type(skill.api).__name__}")
