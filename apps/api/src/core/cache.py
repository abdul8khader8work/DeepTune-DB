"""In-memory LRU + TTL cache (Patch 3, Task 2).

Option B: a single-user local capstone does not need Redis. ``cachetools``
provides a pure-Python ``TTLCache`` with no driver, no container, and no
connection-refused failure mode. ``init_cache()`` runs once in the FastAPI
lifespan; the decorator is safe to import and call before that (it simply
bypasses caching), which keeps unit tests and CLI use working.

The cache is process-local. That is deliberate: the API runs as one uvicorn
process in this deployment, and a per-process cache cannot leak data across
users because there is only one user.
"""

from __future__ import annotations

import hashlib
import inspect
import threading
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from cachetools import TTLCache

P = ParamSpec("P")
R = TypeVar("R")

#: ``None`` until ``init_cache()`` runs. Reads/writes are guarded because sync
#: callers may execute on a worker thread (``asyncio.to_thread``).
_cache: TTLCache[str, Any] | None = None
_lock = threading.RLock()


def init_cache(maxsize: int = 256, ttl: int = 300) -> None:
    """Create the process cache. Called once from the FastAPI lifespan."""
    global _cache
    with _lock:
        _cache = TTLCache(maxsize=max(1, maxsize), ttl=max(0, ttl))


def get_cache() -> TTLCache[str, Any]:
    """Return the live cache, or fail loudly if the lifespan never ran."""
    if _cache is None:
        raise RuntimeError("Cache not initialized. Call init_cache() in lifespan.")
    return _cache


def cached(
    namespace: str = "default",
    key_fn: Callable[..., str] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Cache an async or sync function's return value by namespace + arguments.

    Exceptions are never cached. When ``init_cache()`` has not run the wrapper
    calls straight through, so importing a decorated function in a test or a
    CLI does not require the API lifespan.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                cache = _cache
                if cache is None:
                    raw_res = await cast(Any, fn(*args, **kwargs))
                    return cast(R, raw_res)
                key = _build_key(namespace, fn.__name__, args, kwargs, key_fn)
                with _lock:
                    try:
                        return cast(R, cache[key])
                    except KeyError:
                        pass
                result = await cast(Any, fn(*args, **kwargs))
                with _lock:
                    cache[key] = result
                return cast(R, result)

            return cast(Callable[P, R], async_wrapper)

        @wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            cache = _cache
            if cache is None:
                return fn(*args, **kwargs)
            key = _build_key(namespace, fn.__name__, args, kwargs, key_fn)
            with _lock:
                try:
                    return cast(R, cache[key])
                except KeyError:
                    pass
            result = fn(*args, **kwargs)
            with _lock:
                cache[key] = result
            return result

        return cast(Callable[P, R], sync_wrapper)

    return decorator


def invalidate(namespace: str, fn_name: str, *args: Any, **kwargs: Any) -> None:
    """Remove one entry (no-op before ``init_cache``)."""
    if _cache is None:
        return
    key = _build_key(namespace, fn_name, args, kwargs, None)
    with _lock:
        _cache.pop(key, None)


def clear_all() -> None:
    """Wipe the cache (tests / hot reload). No-op before ``init_cache``."""
    if _cache is None:
        return
    with _lock:
        _cache.clear()


def _build_key(
    namespace: str,
    fn_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    key_fn: Callable[..., str] | None,
) -> str:
    raw = (
        key_fn(*args, **kwargs)
        if key_fn is not None
        else f"{args!r}:{sorted(kwargs.items())!r}"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{namespace}:{fn_name}:{digest}"


__all__ = ["cached", "clear_all", "get_cache", "init_cache", "invalidate"]
