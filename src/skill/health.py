"""Skill 后端健康检查（启动时一次性，借鉴 Hermes verification 思路）。

为什么需要：
manifest.yaml 写错端口（如 base_url 指 8080 但实际服务在 8090），
旧行为是用户发消息才发现 405/连接拒绝。

健康检查在 agent 启动时对每个 skill 的 base_url ping 一下，
失败的 skill 仍加载（不影响其他 skill），但日志醒目报警便于排查。
"""
import asyncio
import logging
from urllib.parse import urlparse

import httpx

from src.skill.schema import HttpBackend, PollBackend, Skill

log = logging.getLogger(__name__)

_HEALTH_TIMEOUT_SEC = 3.0


async def _ping_url(url: str) -> tuple[bool, str]:
    """GET base URL（不带具体 path），任何 1xx-5xx 都算服务在跑。

    返回 (ok, message)。ok=True 表示服务可达；False 表示连接被拒/超时/DNS 失败。
    """
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_SEC) as client:
            resp = await client.get(url)
            return True, f"HTTP {resp.status_code}"
    except httpx.ConnectError as e:
        return False, f"ConnectError: {e}"
    except httpx.TimeoutException:
        return False, f"timeout > {_HEALTH_TIMEOUT_SEC}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _backend_base_url(skill: Skill) -> str | None:
    """从 skill backend 提取 base_url，若没显式声明返回 None。"""
    api = skill.api
    if isinstance(api, (HttpBackend, PollBackend)):
        return api.base_url
    return None


async def health_check_skills(skills: dict[str, Skill]) -> None:
    """对所有 skill 的 base_url + lazy_resources HTTP url 做 ping。

    结果只 log，不阻断启动——skill 仍照常注册，调用时失败由 _friendly_skill_error 报。
    """
    if not skills:
        return

    targets: set[str] = set()
    for skill in skills.values():
        base = _backend_base_url(skill)
        if base:
            parsed = urlparse(base)
            if parsed.scheme and parsed.netloc:
                targets.add(f"{parsed.scheme}://{parsed.netloc}/")
        for res in skill.lazy_resources.values():
            if hasattr(res, "url"):
                parsed = urlparse(res.url)
                if parsed.scheme and parsed.netloc:
                    targets.add(f"{parsed.scheme}://{parsed.netloc}/")

    if not targets:
        log.info("[HEALTH] 无需检查（所有 skill 都用默认 TOOLBOX_BASE_URL 或本地文件）")
        return

    log.info(f"[HEALTH] checking {len(targets)} skill backend(s)...")
    results = await asyncio.gather(*(_ping_url(u) for u in targets), return_exceptions=False)
    for url, (ok, msg) in zip(sorted(targets), results):
        icon = "✓" if ok else "✗"
        log_fn = log.info if ok else log.warning
        log_fn(f"[HEALTH] {icon} {url} → {msg}")
