"""Step1 角色图缓存：跳过 xd-poster-gen 的 step1（角色白底图生成），省 30-60s。

- key: `step1_cache:{user_id}:{characters_sorted_join}:{actionDesc_hash}`
- value: fileId（toolbox 返回的 characterActionFileId）
- TTL: 24h
- 用户隔离：每个 user 独立 cache（避免实验污染他人体验）
- 复用条件：同 user + 同 characters 集合 + 完全相同的 actionDesc
"""
import hashlib

import redis.asyncio as aioredis

from src.config import REDIS_URL

_TTL = 86400  # 24h


class Step1Cache:
    def __init__(self) -> None:
        self._redis = aioredis.from_url(REDIS_URL)

    @staticmethod
    def _key(user_id: str, characters: list[str], action_desc: str) -> str:
        chars = ",".join(sorted(characters))
        h = hashlib.sha256(action_desc.encode("utf-8")).hexdigest()[:16]
        return f"step1_cache:{user_id}:{chars}:{h}"

    async def get(self, user_id: str, characters: list[str], action_desc: str) -> str | None:
        if not user_id or not characters or not action_desc:
            return None
        val = await self._redis.get(self._key(user_id, characters, action_desc))
        return val.decode("utf-8") if val else None

    async def save(self, user_id: str, characters: list[str], action_desc: str, file_id: str) -> None:
        if not user_id or not characters or not action_desc or not file_id:
            return
        await self._redis.setex(self._key(user_id, characters, action_desc), _TTL, file_id)
