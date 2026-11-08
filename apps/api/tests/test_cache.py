"""Patch 3, Task 2: the in-memory cache stores hits, misses, and TTL expiry."""

from __future__ import annotations

import pytest

from src.core.cache import cached, clear_all, get_cache, init_cache
from src.services.hypothetical import to_hypopg_sql


@pytest.fixture(autouse=True)
def reset_cache():
    init_cache(maxsize=8, ttl=60)
    yield
    clear_all()


async def test_cached_returns_same_object() -> None:
    calls = 0

    @cached(namespace="test")
    async def expensive(x: int) -> int:
        nonlocal calls
        calls += 1
        return x * 2

    first = await expensive(5)
    second = await expensive(5)

    assert first == second == 10
    assert calls == 1


async def test_different_args_are_not_cached_together() -> None:
    calls = 0

    @cached(namespace="test")
    async def add(a: int, b: int) -> int:
        nonlocal calls
        calls += 1
        return a + b

    assert await add(1, 2) == 3
    assert await add(3, 4) == 7
    assert calls == 2


def test_ttl_expiry_and_sync_functions() -> None:
    init_cache(maxsize=8, ttl=0)  # every entry expires immediately
    get_cache()["k"] = "v"
    assert "k" not in get_cache()

    calls = 0

    @cached(namespace="sync")
    def double(x: int) -> int:
        nonlocal calls
        calls += 1
        return x * 2

    init_cache(maxsize=8, ttl=60)
    assert double(4) == 8
    assert double(4) == 8
    assert calls == 1


def test_hypopg_translation_is_cached() -> None:
    """The cache is attached to a real pure path, not only to test doubles."""
    sql = 'CREATE INDEX CONCURRENTLY "idx_orders_status" ON "public"."orders" ("status")'
    first = to_hypopg_sql(sql)
    second = to_hypopg_sql(sql)

    assert first == second
    assert "CONCURRENTLY" not in first
    assert len(get_cache()) == 1


def test_cache_is_bypassed_before_init() -> None:
    """Unit tests and CLI code import decorated functions without a lifespan."""
    clear_all()
    import src.core.cache as cache_module

    cache_module._cache = None  # noqa: SLF001 - explicit "not initialised" state
    assert to_hypopg_sql(
        'CREATE INDEX CONCURRENTLY "idx" ON "public"."orders" ("status")'
    ).startswith("CREATE INDEX")
