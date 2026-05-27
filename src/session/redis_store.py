import redis.asyncio as aioredis
from src.conversation.session import ConversationSession, dump_session, load_session
from src.config import REDIS_URL
from src.orchestrator.schema import UserSession

_TTL = 3600  # 1 hour


class SessionStore:
    def __init__(self) -> None:
        self._redis = aioredis.from_url(REDIS_URL)

    def _key(self, user_id: str) -> str:
        return f"session:{user_id}"

    async def get(self, user_id: str) -> UserSession:
        raw = await self._redis.get(self._key(user_id))
        if raw is None:
            return UserSession()
        return UserSession.model_validate_json(raw)

    async def save(self, user_id: str, session: UserSession) -> None:
        await self._redis.setex(self._key(user_id), _TTL, session.model_dump_json())

    async def get_conversation(self, user_id: str) -> ConversationSession:
        raw = await self._redis.get(self._key(user_id))
        return load_session(raw)

    async def save_conversation(self, user_id: str, session: ConversationSession) -> None:
        await self._redis.setex(self._key(user_id), _TTL, dump_session(session))

    async def clear(self, user_id: str) -> None:
        await self._redis.delete(self._key(user_id))
