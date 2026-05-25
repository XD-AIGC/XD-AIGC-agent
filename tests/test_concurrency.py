"""验证 session 隔离：多个 user_id 并发交错操作，互不污染。"""
import asyncio
import pytest

from src.orchestrator.schema import UserSession
from src.session.redis_store import SessionStore


@pytest.fixture
def store():
    return SessionStore()


@pytest.mark.asyncio
async def test_5_users_concurrent_session_writes(store):
    user_ids = [f"test-concurrent-user-{i}" for i in range(5)]

    async def write(uid: str, skill: str) -> None:
        s = UserSession(state="collecting", skill_name=skill, pending_param="image")
        await store.save(uid, s)

    await asyncio.gather(*(write(uid, f"skill-{i}") for i, uid in enumerate(user_ids)))

    sessions = await asyncio.gather(*(store.get(uid) for uid in user_ids))
    for i, s in enumerate(sessions):
        assert s.state == "collecting"
        assert s.skill_name == f"skill-{i}", f"user {user_ids[i]} got skill_name={s.skill_name}"

    await asyncio.gather(*(store.clear(uid) for uid in user_ids))


@pytest.mark.asyncio
async def test_interleaved_read_write_isolated(store):
    """A 在 collecting 中，B idle，A 不应被 B 的 idle 状态污染。"""
    a, b = "test-iso-A", "test-iso-B"

    await store.save(a, UserSession(state="collecting", skill_name="frame-bg-remover", pending_param="image"))
    await store.save(b, UserSession())

    async def read_a() -> UserSession:
        await asyncio.sleep(0.001)
        return await store.get(a)

    async def read_b() -> UserSession:
        return await store.get(b)

    results = await asyncio.gather(read_a(), read_b(), read_a(), read_b())
    assert results[0].state == "collecting"
    assert results[1].state == "idle"
    assert results[2].state == "collecting"
    assert results[3].state == "idle"

    await store.clear(a)
    await store.clear(b)


@pytest.mark.asyncio
async def test_clear_one_user_doesnt_affect_other(store):
    a, b = "test-clear-A", "test-clear-B"
    await store.save(a, UserSession(state="collecting", skill_name="frame-bg-remover"))
    await store.save(b, UserSession(state="collecting", skill_name="frame-bg-remover"))

    await store.clear(a)

    sa = await store.get(a)
    sb = await store.get(b)
    assert sa.state == "idle"
    assert sb.state == "collecting"
    await store.clear(b)


@pytest.mark.asyncio
async def test_high_concurrency_20_users(store):
    """20 个用户并发读写，最后每个人状态都正确。"""
    n = 20
    user_ids = [f"test-load-user-{i}" for i in range(n)]

    async def cycle(i: int) -> None:
        uid = user_ids[i]
        await store.save(uid, UserSession(state="collecting", skill_name=f"s{i}"))
        await asyncio.sleep(0)  # yield
        s = await store.get(uid)
        assert s.skill_name == f"s{i}", f"{uid} corrupted: got {s.skill_name}"
        await store.clear(uid)

    await asyncio.gather(*(cycle(i) for i in range(n)))
