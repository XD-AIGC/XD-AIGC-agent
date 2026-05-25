"""Step1 cache 单元测试。

需要本地 Redis 跑在 REDIS_URL 上。
"""
import pytest

from src.session.step1_cache import Step1Cache, _TTL


def test_key_stable_sorted():
    k1 = Step1Cache._key("u1", ["a", "b"], "doing X")
    k2 = Step1Cache._key("u1", ["b", "a"], "doing X")
    assert k1 == k2  # 角色顺序不影响 key


def test_key_user_isolation():
    k1 = Step1Cache._key("u1", ["a"], "X")
    k2 = Step1Cache._key("u2", ["a"], "X")
    assert k1 != k2


def test_key_actiondesc_change():
    k1 = Step1Cache._key("u1", ["a"], "X")
    k2 = Step1Cache._key("u1", ["a"], "Y")
    assert k1 != k2


@pytest.mark.asyncio
async def test_save_and_get_roundtrip():
    c = Step1Cache()
    await c.save("test-user-A6", ["harry"], "playing basketball", "v2_test_fileid_123")
    got = await c.get("test-user-A6", ["harry"], "playing basketball")
    assert got == "v2_test_fileid_123"


@pytest.mark.asyncio
async def test_get_miss_returns_none():
    c = Step1Cache()
    got = await c.get("test-user-A6", ["nobody-xyz-unique"], "nothing-xyz-unique")
    assert got is None


@pytest.mark.asyncio
async def test_get_empty_inputs_returns_none():
    c = Step1Cache()
    assert await c.get("", ["harry"], "X") is None
    assert await c.get("u1", [], "X") is None
    assert await c.get("u1", ["harry"], "") is None


@pytest.mark.asyncio
async def test_save_empty_inputs_noop():
    c = Step1Cache()
    # 不应抛错
    await c.save("", ["harry"], "X", "fid")
    await c.save("u1", [], "X", "fid")
    await c.save("u1", ["harry"], "", "fid")
    await c.save("u1", ["harry"], "X", "")


def test_ttl_constant():
    assert _TTL == 86400  # 24h
