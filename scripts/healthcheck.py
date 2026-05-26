#!/usr/bin/env python
"""启动前/运行中健康检查 — 验证 LLM / toolbox / Redis 可达。

退出码：
  0  全部通过
  1  任一失败

用法：
  python -m scripts.healthcheck          # 一次性检查
  docker exec ... python -m scripts.healthcheck  # Docker HEALTHCHECK / systemd ExecStartPre 使用
"""
import asyncio
import sys

import httpx
import redis.asyncio as aioredis

from src.config import LLM_BASE_URL, REDIS_URL, TOOLBOX_BASE_URL


async def _check_redis() -> tuple[bool, str]:
    try:
        r = aioredis.from_url(REDIS_URL, socket_timeout=3.0)
        pong = await r.ping()
        await r.aclose()
        return bool(pong), f"redis {REDIS_URL}"
    except Exception as e:
        return False, f"redis {REDIS_URL}: {e!s}"


async def _check_http(url: str, label: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        # 任何 < 500 都算可达（4xx 说明服务在线只是路径/auth 问题）
        ok = resp.status_code < 500
        return ok, f"{label} {url} → {resp.status_code}"
    except Exception as e:
        return False, f"{label} {url}: {e!s}"


async def main() -> int:
    checks = await asyncio.gather(
        _check_redis(),
        _check_http(LLM_BASE_URL, "llm"),
        _check_http(TOOLBOX_BASE_URL, "toolbox"),
    )
    all_ok = all(ok for ok, _ in checks)
    for ok, msg in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
