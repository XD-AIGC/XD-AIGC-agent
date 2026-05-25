import pytest
from src.orchestrator.schema import UserSession
from src.session.redis_store import SessionStore


@pytest.fixture
def store():
    return SessionStore()


@pytest.mark.asyncio
async def test_get_returns_default_when_missing(store):
    session = await store.get("test-user-new-99999")
    assert session.state == "idle"
    assert session.skill_name is None


@pytest.mark.asyncio
async def test_save_and_get_roundtrip(store):
    user_id = "test-user-roundtrip"
    s = UserSession(state="collecting", skill_name="frame-bg-remover", pending_param="image")
    await store.save(user_id, s)
    loaded = await store.get(user_id)
    assert loaded.state == "collecting"
    assert loaded.skill_name == "frame-bg-remover"
    assert loaded.pending_param == "image"
    await store.clear(user_id)


@pytest.mark.asyncio
async def test_clear_resets_to_default(store):
    user_id = "test-user-clear"
    s = UserSession(state="collecting", skill_name="frame-bg-remover")
    await store.save(user_id, s)
    await store.clear(user_id)
    loaded = await store.get(user_id)
    assert loaded.state == "idle"


@pytest.mark.asyncio
async def test_different_users_isolated(store):
    await store.save("user-A", UserSession(state="collecting", skill_name="frame-bg-remover"))
    await store.save("user-B", UserSession(state="idle"))
    a = await store.get("user-A")
    b = await store.get("user-B")
    assert a.state == "collecting"
    assert b.state == "idle"
    await store.clear("user-A")
    await store.clear("user-B")
