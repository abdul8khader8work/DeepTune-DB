# PATCHFILE 3: DEMO-STABILITY FIXES
## Task 1: WebSocket Zombie Cleanup
- Add `ping_interval=30` and `ping_timeout=10` to FastAPI WebSocket
- Implement `on_disconnect()` handler to remove connection from active pool
- Add test: 10 rapid connect/disconnect cycles → no memory leak {{# Task 1: WebSocket Zombie Cleanup — Micro-Step Execution Plan
Before I give you the steps, you need to understand one **critical correction** that will save you from a hallucinated implementation:
> **FastAPI/Starlette WebSocket does NOT have `ping_interval` or `ping_timeout` parameters.** Those belong to the `websockets` library. If your AI agent tries to write `WebSocket(ping_interval=30)`, it will hallucinate a parameter that doesn't exist and crash. The correct approach is either (a) configure it at the **uvicorn server level**, or (b) implement a **manual heartbeat loop** inside the WebSocket handler.
Here is the exact, micro-step breakdown of what the AI must do, file by file.
---
## STEP 1: Configure Uvicorn Server-Level Heartbeat
**File:** `apps/api/src/main.py` (or wherever the uvicorn app is launched)
**What the AI does:**
1. Opens `main.py`.
2. Finds the uvicorn startup configuration (either `uvicorn.run(...)` or the `Dockerfile` CMD / `docker-compose.yml` command).
3. Adds two server flags:
   ```python
   uvicorn.run(
       app,
       host="0.0.0.0",
       port=8000,
       ws_ping_interval=30.0,   # Server sends ping every 30s
       ws_ping_timeout=10.0,    # If no pong in 10s, connection is killed
   )
   ```
4. **OR** in `docker-compose.yml`, modifies the API service command:
   ```yaml
   command: uvicorn src.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 30 --ws-ping-timeout 10
   ```
**Why this matters:** This is the *first line of defense*. If the client vanishes (browser tab closed, network drops), uvicorn will detect the missing pong within 40 seconds and forcibly close the socket. Without this, the connection hangs forever.
**Verification the AI must do:** Run `grep -r "ws.ping" apps/api/` and confirm the flag exists in either `main.py` or `docker-compose.yml`.
---
## STEP 2: Create the Connection Registry
**File:** `apps/api/src/services/ws_registry.py` (NEW FILE)
**What the AI does:**
1. Creates a new file `ws_registry.py`.
2. Defines a module-level dictionary to track active WebSocket connections:
   ```python
   from __future__ import annotations
   import asyncio
   from dataclasses import dataclass, field
   from datetime import datetime, timezone
   from starlette.websockets import WebSocket
   @dataclass(slots=True)
   class ActiveConnection:
       run_id: str
       websocket: WebSocket
       connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
       last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
       _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
   class WebSocketRegistry:
       """Thread-safe registry of active copilot WebSocket connections."""
       def __init__(self) -> None:
           self._connections: dict[str, ActiveConnection] = {}
           self._lock = asyncio.Lock()
       async def register(self, run_id: str, websocket: WebSocket) -> ActiveConnection:
           async with self._lock:
               # If a connection already exists for this run_id, close it first
               existing = self._connections.get(run_id)
               if existing is not None:
                   await self._safe_close(existing.websocket, code=4000, reason="replaced")
               conn = ActiveConnection(run_id=run_id, websocket=websocket)
               self._connections[run_id] = conn
               return conn
       async def unregister(self, run_id: str) -> None:
           async with self._lock:
               self._connections.pop(run_id, None)
       async def touch(self, run_id: str) -> None:
           async with self._lock:
               conn = self._connections.get(run_id)
               if conn is not None:
                   conn.last_activity = datetime.now(timezone.utc)
       async def broadcast(self, run_id: str, message: dict) -> bool:
           async with self._lock:
               conn = self._connections.get(run_id)
           if conn is None:
               return False
           try:
               await conn.websocket.send_json(message)
               await self.touch(run_id)
               return True
           except Exception:
               await self.unregister(run_id)
               return False
       @property
       def active_count(self) -> int:
           return len(self._connections)
       async def _safe_close(self, ws: WebSocket, code: int, reason: str) -> None:
           try:
               await ws.close(code=code, reason=reason)
           except Exception:
               pass  # Already closed — swallow silently
   # Singleton
   registry = WebSocketRegistry()
   ```
**Why each piece matters:**
- `slots=True` on the dataclass reduces memory per connection by ~40%.
- The `asyncio.Lock` prevents race conditions when two coroutines try to register/unregister the same `run_id` simultaneously.
- `_safe_close` swallows the "already closed" exception that Starlette throws if you call `.close()` on a dead socket.
- The singleton `registry` at the bottom means every module imports the *same* instance.
**Verification the AI must do:** Confirm `registry.active_count` is importable from other modules.
---
## STEP 3: Rewrite the WebSocket Endpoint
**File:** `apps/api/src/api/copilot_ws.py` (or wherever `WS /ws/copilot/{run_id}` lives)
**What the AI does:**
1. Opens the existing WebSocket route handler.
2. Replaces the naive `while True: receive_text()` loop with the registry-aware pattern:
```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from src.services.ws_registry import registry
router = APIRouter()
@router.websocket("/ws/copilot/{run_id}")
async def copilot_ws(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    # Register — closes any zombie connection for this run_id
    conn = await registry.register(run_id, websocket)
    try:
        while True:
            # receive_text() raises WebSocketDisconnect when client vanishes
            raw = await websocket.receive_text()
            await registry.touch(run_id)
            # ... existing message-handling logic ...
            # (parse JSON, dispatch to tool handlers, stream response)
    except WebSocketDisconnect:
        # Client closed cleanly (tab closed, network drop)
        pass
    except Exception as exc:
        # Malformed frame, protocol error, etc.
        try:
            await websocket.close(code=1011, reason=f"internal error: {type(exc).__name__}")
        except Exception:
            pass
    finally:
        # THIS IS THE CRITICAL LINE — always unregister, even on crash
        await registry.unregister(run_id)
```
**Why the `try/except/finally` structure is non-negotiable:**
- `WebSocketDisconnect` is raised by Starlette when the client sends a close frame OR when the TCP connection drops. Without catching it, the coroutine dies and the connection stays in the registry forever.
- The `finally` block guarantees `unregister()` runs even if an unexpected exception (e.g., `TypeError` in your message parser) crashes the handler.
- Without this, every crashed connection is a **memory leak**: the `WebSocket` object holds a reference to the TCP socket, the ASGI scope, and all buffered messages. 100 leaked connections = ~50MB of dead RAM.
**Verification the AI must do:** Confirm the `finally` block exists and calls `registry.unregister(run_id)`.
---
## STEP 4: Wire the Registry Into the Pipeline
**File:** `apps/api/src/services/pipeline.py` (or wherever the optimization orchestration lives)
**What the AI does:**
1. Finds every place the backend currently pushes progress updates to the frontend.
2. Replaces direct `websocket.send_json(...)` calls with `await registry.broadcast(run_id, {...})`.
```python
# BEFORE (broken — holds a stale reference if client disconnected)
await websocket.send_json({"type": "log_update", "payload": {...}})
# AFTER (safe — returns False silently if connection is dead)
sent = await registry.broadcast(run_id, {
    "type": "log_update",
    "payload": {"timestamp": now_iso(), "message": "GNN forward pass complete"}
})
if not sent:
    logger.debug("broadcast skipped: no active connection for run_id=%s", run_id)
```
**Why this matters:** The pipeline runs as a background task. If the user closes the browser mid-optimization, the pipeline must not crash trying to send to a dead socket. `broadcast()` returns `False` instead of raising.
**Verification the AI must do:** `grep -rn "websocket.send" apps/api/src/services/` should return **zero** results. All sends go through `registry.broadcast()`.
---
## STEP 5: Expose Registry Health in the Status Endpoint
**File:** `apps/api/src/api/health.py` (or `engine_status.py`)
**What the AI does:**
1. Adds the active connection count to the health response:
```python
@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "ws_active_connections": registry.active_count,  # NEW
    }
```
**Why this matters:** During the demo, if `ws_active_connections` climbs above 5 and never drops, you have a leak. This gives you a live diagnostic without SSH-ing into the container.
---
## STEP 6: Write the Stress Test
**File:** `apps/api/tests/test_ws_registry.py` (NEW FILE)
**What the AI does:**
1. Creates the test file.
2. Writes the exact test the task requires:
```python
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from starlette.testclient import TestClient
from src.main import app
from src.services.ws_registry import registry
@pytest.mark.asyncio
async def test_rapid_connect_disconnect_no_leak():
    """10 rapid connect/disconnect cycles must leave registry empty."""
    initial_count = registry.active_count
    for i in range(10):
        run_id = f"stress-test-{i}"
        async with AsyncClient(transport=ASGITransport(app=app)) as client:
            # Open WebSocket
            async with client.stream(
                "GET",
                f"/api/v1/ws/copilot/{run_id}",
                headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            ) as response:
                assert response.status_code == 101  # Switching Protocols
                # Immediately close without sending anything
                await response.aclose()
        # Give the finally block time to execute
        await asyncio.sleep(0.05)
    final_count = registry.active_count
    assert final_count == initial_count, (
        f"Memory leak detected: {final_count - initial_count} zombie connections remain"
    )
@pytest.mark.asyncio
async def test_duplicate_run_id_replaces_old_connection():
    """Registering the same run_id twice must close the first connection."""
    run_id = "dup-test"
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        async with client.stream(
            "GET", f"/api/v1/ws/copilot/{run_id}",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        ):
            assert registry.active_count >= 1
            # Open a second connection with the SAME run_id
            async with client.stream(
                "GET", f"/api/v1/ws/copilot/{run_id}",
                headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            ):
                await asyncio.sleep(0.1)
                # Only ONE connection should exist for this run_id
                assert registry.active_count == 1  # (relative to baseline)
@pytest.mark.asyncio
async def test_broadcast_to_dead_connection_returns_false():
    """Broadcasting to a non-existent run_id must return False, not raise."""
    result = await registry.broadcast("nonexistent-run-id", {"type": "test"})
    assert result is False
```
**Why each test matters:**
- **Test 1** is the exact acceptance criterion: 10 cycles → 0 leaks.
- **Test 2** proves the `register()` method's "close existing first" logic works.
- **Test 3** proves `broadcast()` degrades gracefully instead of crashing the pipeline.
---
## STEP 7: Run the Full Test Suite
**What the AI does:**
1. Executes: `cd apps/api && python -m pytest tests/test_ws_registry.py -v --tb=short`
2. Then executes the full suite: `python -m pytest -v`
3. Confirms: **all previous 80 tests still pass** + **3 new tests pass** = **83 total**.
4. If any test fails, the AI reads the traceback, fixes the specific line, and re-runs. It does NOT rewrite the entire file.
---
## STEP 8: Verify in the Running App
**What the AI does:**
1. Starts the API: `uvicorn src.main:app --port 8000 --ws-ping-interval 30 --ws-ping-timeout 10`
2. Opens the browser at `http://localhost:3000`.
3. Runs a query → opens Copilot tab → sees the WebSocket connect.
4. **Closes the browser tab abruptly** (not a clean navigation).
5. Waits 40 seconds (30s ping + 10s timeout).
6. Hits `curl http://localhost:8000/api/v1/health` → confirms `ws_active_connections` dropped back to 0.
7. Repeats 5 times. Count never climbs.
---
## 🚨 Common Hallucinations to Watch For
If your AI agent does any of these, **reject the output immediately**:
| Hallucination | Why It's Wrong |
|---|---|
| `WebSocket(ping_interval=30)` | Starlette WebSocket has no such parameter. This will `TypeError`. |
| `@app.on_event("shutdown")` to clear registry | Deprecated in FastAPI. Use `lifespan` context manager instead. |
| Storing connections in a `list` instead of `dict` | You can't look up by `run_id` in O(1). Must be `dict[str, ActiveConnection]`. |
| No `finally` block around the message loop | This is the entire point of the task. Without it, zombies persist. |
| Using `threading.Lock` instead of `asyncio.Lock` | FastAPI is async. A threading lock will deadlock the event loop. |
| Forgetting `await response.aclose()` in the test | The test will hang forever waiting for the WebSocket to close. |
---
## Summary: The 8 Micro-Steps in Order
```
1. Add --ws-ping-interval/--ws-ping-timeout to uvicorn config
2. Create ws_registry.py with dict-based connection pool + asyncio.Lock
3. Rewrite copilot_ws.py with try/except WebSocketDisconnect/finally unregister
4. Replace all websocket.send_json() in pipeline.py with registry.broadcast()
5. Add ws_active_connections to /health endpoint
6. Write test_ws_registry.py with 3 tests (stress, duplicate, dead-broadcast)
7. Run pytest → 83 passed
8. Live verify: close tab → wait 40s → health shows 0 connections
```
}}
## Task 2: Redis or In-Memory
- OPTION A: Add Redis service to docker-compose.yml
- OPTION B: Remove Redis dependency, use `fastapi-cache2` with in-memory backend
- Update `apps/api/src/core/config.py` accordingly {{Here is the exact, micro-step-by-step breakdown of how the AI agent will execute Task 2. I am choosing **Option B (In-Memory)** because adding Redis to a capstone project introduces unnecessary complexity, a new container, a new dependency, and a new failure mode during your demo. In-memory is simpler, faster, and perfectly adequate for a single-user local system.
---
## PHASE 1: RECONNAISSANCE (Read Current State)
### Step 1.1 — Grep for Redis references
The AI runs:
```bash
grep -rn "redis\|Redis\|REDIS\|aioredis\|redis_cache\|fastapi.cache\|cache2" apps/api/
```
**What it finds (likely):**
- `apps/api/src/core/config.py` → a `REDIS_URL` or `CACHE_BACKEND` variable
- `apps/api/src/services/pipeline.py` → a `@cache(...)` decorator or a `RedisCache` import
- `apps/api/requirements.txt` → `redis>=4.0` or `fastapi-cache2[redis]`
- `docker-compose.yml` → nothing (Redis is missing, which is the bug)
- Possibly `apps/api/src/api/routes.py` → a cache invalidation call
### Step 1.2 — Read the config file
The AI opens `apps/api/src/core/config.py` and reads the full file. It identifies:
- The exact line where `REDIS_URL` is defined
- The exact line where `CACHE_TTL` or `CACHE_MAXSIZE` is defined
- Whether it uses `pydantic-settings` `BaseSettings` or plain `os.getenv()`
### Step 1.3 — Read the service file
The AI opens whichever file uses the cache (likely `apps/api/src/services/pipeline.py` or `apps/api/src/services/engine_bridge.py`). It identifies:
- The exact import statement (e.g., `from fastapi_cache import FastAPICache` or `from fastapi_cache.backends.redis import RedisBackend`)
- The exact decorator usage (e.g., `@cache(namespace="gnn_predictions", expire=300)`)
- The exact initialization call (e.g., `FastAPICache.init(RedisBackend(r), prefix="deeptune")`)
### Step 1.4 — Read requirements
The AI opens `apps/api/requirements.txt` (or `requirements-dev.txt`) and identifies:
- `redis>=4.0` or `redis[hiredis]>=5.0`
- `fastapi-cache2[redis]>=0.2.0`
### Step 1.5 — Read docker-compose.yml
The AI opens `docker-compose.yml` and confirms:
- There is **no** `redis:` service block
- There is **no** `REDIS_URL` environment variable in the `api:` service
---
## PHASE 2: DECISION LOGIC
The AI evaluates:
| Criterion | Option A (Redis) | Option B (In-Memory) |
|---|---|---|
| New container needed? | Yes | No |
| New dependency? | Already there | Remove redis dep |
| Demo failure risk? | Higher (port conflict, OOM) | Lower (no external service) |
| Capstone complexity? | Unnecessary | Appropriate |
| Multi-user scaling? | Yes | No (but irrelevant for capstone) |
**Decision: Option B.** The AI proceeds with in-memory LRU caching.
---
## PHASE 3: CODE CHANGES (File by File)
### Step 3.1 — Modify `apps/api/requirements.txt`
**Remove these lines:**
```
redis>=4.0
fastapi-cache2[redis]>=0.2.0
```
**Add this line (if not already present):**
```
cachetools>=5.3.0
```
**Why `cachetools`:** It is a pure-Python, zero-dependency LRU/TTL cache. No async driver, no connection pool, no external service. Perfect for in-memory.
### Step 3.2 — Modify `apps/api/src/core/config.py`
**Remove:**
```python
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_BACKEND: str = "redis"
```
**Replace with:**
```python
CACHE_MAXSIZE: int = int(os.getenv("CACHE_MAXSIZE", "256"))
CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))
```
**Full new config block (example):**
```python
from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    # ... existing fields (JWT_SECRET, TARGET_DB_URL, etc.) ...
    # Cache (in-memory LRU + TTL)
    CACHE_MAXSIZE: int = 256
    CACHE_TTL_SECONDS: int = 300
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```
### Step 3.3 — Create `apps/api/src/core/cache.py` (NEW FILE)
The AI writes a small, self-contained in-memory cache module:
```python
"""In-memory TTL+LRU cache. Zero external dependencies."""
from __future__ import annotations
import hashlib
import time
from functools import wraps
from typing import Any, Callable, Optional
from cachetools import TTLCache
# Module-level singleton. Sized from config at import time.
_cache: TTLCache | None = None
def init_cache(maxsize: int = 256, ttl: int = 300) -> None:
    """Called once during FastAPI lifespan startup."""
    global _cache
    _cache = TTLCache(maxsize=maxsize, ttl=ttl)
def get_cache() -> TTLCache:
    if _cache is None:
        raise RuntimeError("Cache not initialized. Call init_cache() in lifespan.")
    return _cache
def cached(
    namespace: str = "default",
    key_fn: Optional[Callable[..., str]] = None,
) -> Callable:
    """Decorator: cache the return value of an async or sync function."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _build_key(namespace, fn.__name__, args, kwargs, key_fn)
            cache = get_cache()
            if key in cache:
                return cache[key]
            result = await fn(*args, **kwargs)
            cache[key] = result
            return result
        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _build_key(namespace, fn.__name__, args, kwargs, key_fn)
            cache = get_cache()
            if key in cache:
                return cache[key]
            result = fn(*args, **kwargs)
            cache[key] = result
            return result
        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper
    return decorator
def invalidate(namespace: str, fn_name: str, *args: Any, **kwargs: Any) -> None:
    """Remove a specific key from the cache."""
    key = _build_key(namespace, fn_name, args, kwargs, None)
    get_cache().pop(key, None)
def clear_all() -> None:
    """Wipe the entire cache (for tests / hot-reload)."""
    get_cache().clear()
def _build_key(
    namespace: str,
    fn_name: str,
    args: tuple,
    kwargs: dict,
    key_fn: Optional[Callable[..., str]],
) -> str:
    if key_fn is not None:
        raw = key_fn(*args, **kwargs)
    else:
        raw = f"{args}:{sorted(kwargs.items())}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{namespace}:{fn_name}:{digest}"
```
### Step 3.4 — Modify `apps/api/src/main.py` (or wherever `lifespan` is)
**Remove** any Redis initialization:
```python
# DELETE THIS:
# from fastapi_cache import FastAPICache
# from fastapi_cache.backends.redis import RedisBackend
# import redis.asyncio as aioredis
# r = aioredis.from_url(settings.REDIS_URL)
# FastAPICache.init(RedisBackend(r), prefix="deeptune")
```
**Add** in-memory cache initialization inside the `lifespan` context manager:
```python
from src.core.cache import init_cache
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing engine loading ...
    init_cache(
        maxsize=settings.CACHE_MAXSIZE,
        ttl=settings.CACHE_TTL_SECONDS,
    )
    yield
    # ... existing cleanup ...
```
### Step 3.5 — Modify the service file (e.g., `pipeline.py` or `engine_bridge.py`)
**Remove:**
```python
from fastapi_cache.decorator import cache  # DELETE
```
**Add:**
```python
from src.core.cache import cached  # NEW
```
**Replace decorators:**
```python
# OLD:
# @cache(namespace="gnn_predictions", expire=300)
# async def predict_cost(graph: Data) -> float: ...
# NEW:
@cached(namespace="gnn_predictions")
async def predict_cost(graph: Data) -> float: ...
```
**Remove any `RedisBackend` or `aioredis` imports.**
### Step 3.6 — Modify `.env.example`
**Remove:**
```
REDIS_URL=redis://localhost:6379/0
```
**Add:**
```
CACHE_MAXSIZE=256
CACHE_TTL_SECONDS=300
```
---
## PHASE 4: DOCKER CHANGES
### Step 4.1 — Confirm `docker-compose.yml` needs NO change
Since we chose Option B (in-memory), there is **no Redis container to add**. The AI verifies:
- `docker-compose.yml` has no `redis:` service → correct, leave it alone
- The `api:` service has no `REDIS_URL` env var → correct, remove it if present
### Step 4.2 — Remove stale Redis env var from `api:` service
If `docker-compose.yml` contains:
```yaml
REDIS_URL: redis://redis:6379/0
```
The AI **deletes that line** from the `api:` environment block.
---
## PHASE 5: TEST VERIFICATION
### Step 5.1 — Run existing tests
```bash
cd apps/api && python -m pytest -x -q
```
**Expected:** All 80 tests still pass. The cache is now in-memory, so no Redis connection is attempted.
### Step 5.2 — Write a new cache unit test
The AI creates `apps/api/tests/test_cache.py`:
```python
import asyncio
import pytest
from src.core.cache import init_cache, cached, get_cache, clear_all
@pytest.fixture(autouse=True)
def reset_cache():
    init_cache(maxsize=8, ttl=60)
    yield
    clear_all()
@pytest.mark.asyncio
async def test_cached_returns_same_object():
    call_count = 0
    @cached(namespace="test")
    async def expensive(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x * 2
    r1 = await expensive(5)
    r2 = await expensive(5)
    assert r1 == r2 == 10
    assert call_count == 1  # second call was cached
@pytest.mark.asyncio
async def test_different_args_not_cached():
    @cached(namespace="test")
    async def add(a: int, b: int) -> int:
        return a + b
    assert await add(1, 2) == 3
    assert await add(3, 4) == 7  # different key, not cached
def test_ttl_expiry():
    init_cache(maxsize=8, ttl=0)  # instant expiry
    get_cache()["k"] = "v"
    assert "k" not in get_cache()  # already expired
```
### Step 5.3 — Run the new tests
```bash
cd apps/api && python -m pytest tests/test_cache.py -x -q
```
**Expected:** 3 tests pass.
### Step 5.4 — Run full suite again
```bash
cd apps/api && python -m pytest -x -q
```
**Expected:** 83 tests pass (80 original + 3 new).
---
## PHASE 6: TYPECHECK & LINT
### Step 6.1 — Python type check
```bash
cd apps/api && mypy src/core/cache.py src/core/config.py --strict
```
**Expected:** Clean. No `Any` leaks.
### Step 6.2 — Frontend type check (confirm no breakage)
```bash
cd apps/web && npm run typecheck
```
**Expected:** Clean. The frontend never talked to Redis directly.
### Step 6.3 — Lint
```bash
cd apps/api && ruff check src/core/cache.py src/core/config.py
cd apps/web && npm run lint
```
**Expected:** Clean.
---
## PHASE 7: COMMIT & REPORT
### Step 7.1 — Stage and commit
```bash
git add apps/api/requirements.txt \
        apps/api/src/core/config.py \
        apps/api/src/core/cache.py \
        apps/api/src/main.py \
        apps/api/src/services/pipeline.py \
        apps/api/tests/test_cache.py \
        .env.example \
        docker-compose.yml
git commit -m "fix(patch-3-task2): replace Redis with in-memory TTLCache
- Remove redis + fastapi-cache2[redis] from requirements
- Add cachetools>=5.3.0 (zero-dep in-memory LRU+TTL)
- New src/core/cache.py: init_cache(), @cached decorator, invalidate(), clear_all()
- Wire init_cache() into FastAPI lifespan
- Replace @cache(...) with @cached(...) in pipeline service
- Remove REDIS_URL from .env.example and docker-compose api env
- Add 3 unit tests for cache hit/miss/TTL expiry
- 83 tests pass, mypy strict clean, lint clean"
```
### Step 7.2 — Push
```bash
git push origin main
```
### Step 7.3 — Output the Patch Report
The AI prints:
```
## Task 2 Report — Redis → In-Memory Cache
| Item | Status |
|------|--------|
| redis removed from requirements.txt | ✅ |
| fastapi-cache2[redis] removed | ✅ |
| cachetools>=5.3.0 added | ✅ |
| src/core/cache.py created (TTLCache + @cached) | ✅ |
| init_cache() wired into FastAPI lifespan | ✅ |
| @cache → @cached in pipeline.py | ✅ |
| REDIS_URL removed from .env.example | ✅ |
| REDIS_URL removed from docker-compose api env | ✅ |
| 3 new cache unit tests | ✅ |
| Full suite: 83 passed | ✅ |
| mypy --strict: clean | ✅ |
| ruff + eslint: clean | ✅ |
**Decision:** Option B (in-memory). No Redis container added.
**Rationale:** Single-user local capstone does not need distributed caching.
cachetools TTLCache is zero-dependency, sub-microsecond lookup, and
eliminates an entire failure mode (Redis connection refused / OOM).
```
---
## What Could Go Wrong (And How the AI Handles It)
| Failure | AI Response |
|---------|-------------|
| `pipeline.py` uses `fastapi_cache` in 3 different places | AI greps ALL occurrences, replaces each one, runs full test suite after each |
| `cachetools` is not compatible with Python 3.14 (your venv) | AI pins `cachetools>=5.5.0` which supports 3.14, or falls back to a 15-line hand-rolled `OrderedDict` + `time.monotonic()` TTL cache |
| A test mocks Redis and now fails | AI updates the test fixture to mock `get_cache()` instead |
| The `@cached` decorator breaks on methods with `self` | AI's `_build_key` includes `args[0]` (self) in the hash, so different instances get different cache entries |
---
}}
## Task 3: Fix tmpfs Memory Bomb
- Remove `tmpfs` from shadow_db in docker-compose.yml
- OR add warning: "Demo dataset must be <50MB"
- Update README with dataset size limit {{The AI should execute **Task 3** as a precise, mechanical patch. It should not “think creatively.” It should locate the file, remove the dangerous `tmpfs` mount, replace it with a disk-backed Docker volume, add a reset procedure, update the README warning, validate the Compose file, and commit the change.
Below is the exact micro-step process the AI should follow.
---
# Task 3: Fix `tmpfs` Memory Bomb — Exact Micro-Step Execution Plan
## Decision
The AI should implement **both** options:
1. **Remove `tmpfs` from `shadow_db`**  
   This is the actual fix for the memory bomb.
2. **Add a README warning: “Demo dataset must be < 50 MB”**  
   This preserves demo speed and avoids slow `hypopg` validation.
So the final behavior is:
> The Shadow DB no longer stores PostgreSQL data in RAM. It uses a normal Docker volume. The README warns that the demo dataset should remain small for predictable performance.
---
# Phase A — Reconnaissance
The AI must first inspect the current state before editing.
## Step A1: Locate the Compose file
Run:
```bash
ls docker-compose.yml
```
Expected result:
```text
docker-compose.yml
```
If missing, stop and report:
```text
ERROR: docker-compose.yml not found at repository root.
```
---
## Step A2: Find the `shadow_db` service
Run:
```bash
grep -n "shadow_db:" docker-compose.yml
```
Expected example:
```text
54:shadow_db:
```
The AI must note the line number where `shadow_db:` begins.
---
## Step A3: Confirm the dangerous `tmpfs` block exists
Run:
```bash
grep -n "tmpfs" docker-compose.yml
```
Expected example:
```text
62:    tmpfs:
63:      - /var/lib/postgresql/data
```
If `tmpfs` is absent, the AI should report:
```text
WARNING: tmpfs already removed. Proceeding only with README warning and validation.
```
---
## Step A4: Read the full `shadow_db` block
The AI should open `docker-compose.yml` and inspect the section from `shadow_db:` until the next top-level service, usually `api:`.
It should look for this pattern:
```yaml
shadow_db:
  build:
    context: ./infra/shadow_db
  environment:
    POSTGRES_USER: shadow_user
    POSTGRES_PASSWORD: ${SHADOW_DB_PASSWORD:-shadow_dev_password}
    POSTGRES_DB: shadow_db
  ports:
    - "127.0.0.1:5433:5432"
  tmpfs:
    - /var/lib/postgresql/data
  shm_size: 256mb
  volumes:
    - ./infra/postgres/demo.sql:/docker-entrypoint-initdb.d/10-demo.sql:ro
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U shadow_user -d shadow_db"]
    interval: 5s
    timeout: 3s
    retries: 30
  restart: unless-stopped
```
The AI must identify:
```yaml
tmpfs:
  - /var/lib/postgresql/data
```
as the object to remove.
---
# Phase B — Edit `docker-compose.yml`
## Step B1: Remove the old `tmpfs` comment
The current file may contain a comment like:
```yaml
# Reviewer mandate: hypothetical indexes live in RAM only.
```
The AI must delete that comment because it is now false.
---
## Step B2: Remove the `tmpfs` block
Delete these lines:
```yaml
tmpfs:
  - /var/lib/postgresql/data
```
The AI must not merely comment them out. It must remove them.
---
## Step B3: Insert the replacement comment
Immediately before `shm_size`, insert:
```yaml
  # Patch 3: do not use tmpfs for PostgreSQL data.
  # tmpfs consumes host RAM and can OOM the machine when the demo dataset grows.
  # The shadow DB is now disk-backed via a named Docker volume.
  # Reset it after changing demo.sql with:
  #   docker compose stop shadow_db
  #   docker compose rm -f shadow_db
  #   docker volume rm deeptune_shadow_data
  #   docker compose up -d shadow_db
```
This comment is important because it explains why the previous “RAM only” instruction was overridden.
---
## Step B4: Keep `shm_size`
Leave this line intact:
```yaml
  shm_size: 256mb
```
Do not remove it. PostgreSQL still needs `/dev/shm` for internal shared memory.
Optional improvement:
If the AI wants to be slightly safer for larger demos, it may change:
```yaml
shm_size: 256mb
```
to:
```yaml
shm_size: 512mb
```
But for the minimal patch, keep `256mb`.
---
## Step B5: Add the named volume mount
Inside the existing `volumes:` block for `shadow_db`, add this as the first volume:
```yaml
- shadow_data:/var/lib/postgresql/data
```
The `volumes:` block should become:
```yaml
  volumes:
    - shadow_data:/var/lib/postgresql/data
    - ./infra/postgres/demo.sql:/docker-entrypoint-initdb.d/10-demo.sql:ro
```
Order matters conceptually:
1. PostgreSQL data directory volume first.
2. Init SQL mount second.
---
## Step B6: Add the top-level volume declaration
At the bottom of `docker-compose.yml`, find:
```yaml
volumes:
  metadata_data:
  target_data:
```
Add:
```yaml
  shadow_data:
```
Final block should be:
```yaml
volumes:
  metadata_data:
  target_data:
  shadow_data:
```
Without this, Docker Compose will fail validation.
---
# Phase C — Final `shadow_db` Service Shape
After the edit, the `shadow_db` service should look like this:
```yaml
shadow_db:
  build:
    context: ./infra/shadow_db
  environment:
    POSTGRES_USER: shadow_user
    POSTGRES_PASSWORD: ${SHADOW_DB_PASSWORD:-shadow_dev_password}
    POSTGRES_DB: shadow_db
  ports:
    - "127.0.0.1:5433:5432"
  # Patch 3: do not use tmpfs for PostgreSQL data.
  # tmpfs consumes host RAM and can OOM the machine when the demo dataset grows.
  # The shadow DB is now disk-backed via a named Docker volume.
  # Reset it after changing demo.sql with:
  #   docker compose stop shadow_db
  #   docker compose rm -f shadow_db
  #   docker volume rm deeptune_shadow_data
  #   docker compose up -d shadow_db
  shm_size: 256mb
  volumes:
    - shadow_data:/var/lib/postgresql/data
    - ./infra/postgres/demo.sql:/docker-entrypoint-initdb.d/10-demo.sql:ro
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U shadow_user -d shadow_db"]
    interval: 5s
    timeout: 3s
    retries: 30
  restart: unless-stopped
```
And the bottom volumes section should be:
```yaml
volumes:
  metadata_data:
  target_data:
  shadow_data:
```
---
# Phase D — Validate the Compose File
## Step D1: Run Docker Compose config validation
If Docker is available, run:
```bash
docker compose config --quiet
```
Expected:
```text
exit code 0
no output
```
If it fails, the AI must read the error and fix the YAML indentation or missing volume declaration.
Common failure:
```text
volumes.shadow_data must be a mapping
```
Fix by ensuring:
```yaml
volumes:
  metadata_data:
  target_data:
  shadow_data:
```
not:
```yaml
volumes:
  - metadata_data
  - target_data
  - shadow_data
```
---
## Step D2: Confirm `tmpfs` is gone from `shadow_db`
Run:
```bash
grep -n "tmpfs" docker-compose.yml
```
Expected:
```text
no output
```
If any `tmpfs` remains, the AI must remove it.
---
## Step D3: Confirm the new volume mount exists
Run:
```bash
grep -n "shadow_data:/var/lib/postgresql/data" docker-compose.yml
```
Expected:
```text
some_line_number:    - shadow_data:/var/lib/postgresql/data
```
---
## Step D4: Confirm top-level volume exists
Run:
```bash
grep -n "^  shadow_data:" docker-compose.yml
```
Expected:
```text
some_line_number:  shadow_data:
```
---
## Step D5: Optional fallback validation if Docker is unavailable
If `docker compose config` cannot run, the AI should at least perform text assertions:
```bash
grep -q "tmpfs" docker-compose.yml && echo "FAIL: tmpfs still present" || echo "PASS: tmpfs removed"
grep -q "shadow_data:/var/lib/postgresql/data" docker-compose.yml && echo "PASS: shadow volume mounted" || echo "FAIL: shadow volume missing"
grep -q "^  shadow_data:" docker-compose.yml && echo "PASS: top-level shadow volume declared" || echo "FAIL: top-level shadow volume missing"
```
Expected:
```text
PASS: tmpfs removed
PASS: shadow volume mounted
PASS: top-level shadow volume declared
```
---
# Phase E — Update README
The AI must add a clear warning to the README.
## Step E1: Locate the Quick Start section
Run:
```bash
grep -n "Quick start" README.md
```
Expected:
```text
some_line_number:## Quick start
```
---
## Step E2: Locate the “Everything (Phase 4)” subsection
Run:
```bash
grep -n "Everything (Phase 4)" README.md
```
Expected:
```text
some_line_number:### Everything (Phase 4)
```
---
## Step E3: Insert the warning after the Docker Compose command
Find this block:
```bash
cp .env.example .env          # fill in JWT_SECRET and CREDENTIAL_ENCRYPTION_KEY
docker compose up -d --build  # metadata_db, target_db, shadow_db, api, web, nginx
```
Immediately after it, insert:
```md
> **Demo dataset limit:** keep the demo dataset under approximately **50 MB**. The shadow database is now disk-backed, but large datasets make `hypopg` validation and `EXPLAIN (ANALYZE)` slow during live demos.
>
> If you change `infra/postgres/demo.sql`, reset the shadow DB volume so PostgreSQL re-runs the init script:
>
> ```bash
> docker compose stop shadow_db
> docker compose rm -f shadow_db
> docker volume rm deeptune_shadow_data
> docker compose up -d shadow_db
> ```
```
This is important because named volumes persist. If `demo.sql` changes but the volume already exists, PostgreSQL will not automatically reload the init script.
---
## Step E4: Add a short note in the infrastructure section if present
If README has a section describing services, update the Shadow DB description from anything implying RAM storage to:
```md
The shadow database uses a disk-backed Docker volume (`shadow_data`) to avoid host RAM exhaustion. It is intended for hypothetical index validation through `hypopg`, not for large production datasets.
```
---
# Phase F — Optional Regression Test
To prevent future agents from reintroducing `tmpfs`, the AI may add a lightweight policy test.
## Step F1: Create test file
Create:
```text
apps/api/tests/test_compose_policy.py
```
---
## Step F2: Add test
```python
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
def test_shadow_db_does_not_use_tmpfs() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    shadow_start = text.find("shadow_db:")
    assert shadow_start != -1, "shadow_db service missing from docker-compose.yml"
    api_start = text.find("\n  api:", shadow_start)
    assert api_start != -1, "api service boundary missing after shadow_db"
    shadow_block = text[shadow_start:api_start]
    assert "tmpfs:" not in shadow_block, (
        "shadow_db must not use tmpfs; tmpfs can exhaust host RAM during demos"
    )
    assert "shadow_data:/var/lib/postgresql/data" in shadow_block, (
        "shadow_db must mount shadow_data:/var/lib/postgresql/data"
    )
def test_top_level_shadow_volume_declared() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    volumes_start = text.rfind("\nvolumes:")
    assert volumes_start != -1, "top-level volumes section missing"
    volumes_block = text[volumes_start:]
    assert "shadow_data:" in volumes_block, (
        "top-level volumes must declare shadow_data"
    )
```
---
## Step F3: Run the test
```bash
cd apps/api
python -m pytest tests/test_compose_policy.py -q
```
Expected:
```text
2 passed
```
If PyYAML is not available, this test intentionally avoids YAML parsing and uses text boundaries.
---
# Phase G — Git Diff Review
Before committing, the AI must inspect the diff.
Run:
```bash
git diff docker-compose.yml README.md
```
The AI must verify:
1. `tmpfs:` is removed.
2. `shadow_data:/var/lib/postgresql/data` is added.
3. top-level `shadow_data:` is added.
4. README warning is added.
5. No unrelated files are modified.
6. No secrets are introduced.
7. No `.env` values are hardcoded.
---
# Phase H — Commit
Use a precise commit message.
```bash
git add docker-compose.yml README.md
```
If the regression test was added:
```bash
git add apps/api/tests/test_compose_policy.py
```
Commit:
```bash
git commit -m "fix(patch-3): remove shadow_db tmpfs and document demo dataset limit"
```
Optional fuller message:
```bash
git commit -m "fix(patch-3): remove shadow_db tmpfs to prevent host RAM exhaustion
- Replace tmpfs-backed PostgreSQL data with named volume shadow_data
- Add reset instructions for demo.sql changes
- Document 50 MB demo dataset limit in README
- Add compose policy regression test"
```
---
# Phase I — Push
```bash
git push origin main
```
Or, if using a branch:
```bash
git push origin patch-3-tmpfs-fix
```
---
# Phase J — Final Verification
After push, the AI must run:
```bash
docker compose config --quiet
grep -n "tmpfs" docker-compose.yml
grep -n "shadow_data:/var/lib/postgresql/data" docker-compose.yml
grep -n "^  shadow_data:" docker-compose.yml
```
Expected final state:
```text
docker compose config --quiet -> success
grep tmpfs -> no output
grep shadow_data volume -> match
grep top-level shadow_data -> match
```
---
# Exact Prompt to Give the AI Agent
Paste this to your coding agent:
```text
Execute Task 3 from patchfile_3.md: Fix tmpfs Memory Bomb.
Do not improvise. Follow these exact micro-steps.
1. Open docker-compose.yml.
2. Locate the shadow_db service.
3. Remove the tmpfs block:
   tmpfs:
     - /var/lib/postgresql/data
4. Remove the old comment implying hypothetical indexes live in RAM.
5. Insert this comment above shm_size:
   # Patch 3: do not use tmpfs for PostgreSQL data.
   # tmpfs consumes host RAM and can OOM the machine when the demo dataset grows.
   # The shadow DB is now disk-backed via a named Docker volume.
   # Reset it after changing demo.sql with:
   #   docker compose stop shadow_db
   #   docker compose rm -f shadow_db
   #   docker volume rm deeptune_shadow_data
   #   docker compose up -d shadow_db
6. Keep shm_size: 256mb.
7. In shadow_db.volumes, add:
   - shadow_data:/var/lib/postgresql/data
   before the existing demo.sql mount.
8. At the bottom top-level volumes section, add:
   shadow_data:
9. Validate with:
   docker compose config --quiet
   If Docker is unavailable, use grep checks to confirm:
   - no tmpfs remains
   - shadow_data:/var/lib/postgresql/data exists
   - top-level shadow_data exists
10. Update README.md:
   After the Quick Start docker compose up command, add this warning:
   > **Demo dataset limit:** keep the demo dataset under approximately **50 MB**. The shadow database is now disk-backed, but large datasets make `hypopg` validation and `EXPLAIN (ANALYZE)` slow during live demos.
   >
   > If you change `infra/postgres/demo.sql`, reset the shadow DB volume so PostgreSQL re-runs the init script:
   >
   > ```bash
   > docker compose stop shadow_db
   > docker compose rm -f shadow_db
   > docker volume rm deeptune_shadow_data
   > docker compose up -d shadow_db
   > ```
11. Optionally add apps/api/tests/test_compose_policy.py with two tests:
   - shadow_db does not contain tmpfs
   - shadow_db mounts shadow_data:/var/lib/postgresql/data
   - top-level volumes declares shadow_data
12. Run:
   git diff docker-compose.yml README.md
   and if test added:
   cd apps/api && python -m pytest tests/test_compose_policy.py -q
13. Commit:
   git add docker-compose.yml README.md
   git add apps/api/tests/test_compose_policy.py  # if created
   git commit -m "fix(patch-3): remove shadow_db tmpfs and document demo dataset limit"
14. Push to main or the active patch branch.
15. Output a Patch Report containing:
   - files changed
   - validation commands run
   - test result
   - commit hash
   - confirmation that tmpfs is removed
   - confirmation that shadow_data volume is declared
   - confirmation README warning added
Reviewer note required:
State that this patch removes the host RAM exhaustion risk caused by tmpfs-backed PostgreSQL data while preserving safe disk-backed shadow validation through hypopg.
```
---
# What the AI’s Final Patch Report Should Look Like
The AI should output something like:
```text
Patch 3 Report — tmpfs Memory Bomb Fix
Files changed:
- docker-compose.yml
- README.md
- apps/api/tests/test_compose_policy.py
Changes:
- Removed tmpfs mount from shadow_db.
- Replaced RAM-backed PostgreSQL data directory with named volume shadow_data.
- Added top-level shadow_data volume declaration.
- Added comment explaining reset procedure after demo.sql changes.
- Added README warning: demo dataset should remain under ~50 MB.
- Added regression test preventing future tmpfs usage in shadow_db.
Validation:
- docker compose config --quiet: PASS
- grep tmpfs docker-compose.yml: no matches
- grep shadow_data:/var/lib/postgresql/data docker-compose.yml: PASS
- grep "^  shadow_data:" docker-compose.yml: PASS
- pytest apps/api/tests/test_compose_policy.py: 2 passed
Commit:
- abc1234 fix(patch-3): remove shadow_db tmpfs and document demo dataset limit
Reviewer note:
This patch removes the host RAM exhaustion risk caused by tmpfs-backed PostgreSQL data while preserving safe disk-backed shadow validation through hypopg.
```
---
# Important Operational Detail the AI Must Not Miss
Because the AI is replacing `tmpfs` with a **named volume**, the Shadow DB will now persist between restarts.
That means this is now required documentation:
```bash
docker compose stop shadow_db
docker compose rm -f shadow_db
docker volume rm deeptune_shadow_data
docker compose up -d shadow_db
```
Why?
PostgreSQL only runs files in:
```text
/docker-entrypoint-initdb.d/
```
when the data directory is empty.
So if the developer changes:
```text
infra/postgres/demo.sql
```
but the old `shadow_data` volume still exists, PostgreSQL will not reload the new demo schema/data.
Therefore, the README must include the reset command.
---
# Final Answer
The AI should execute Task 3 by doing this exact sequence:
1. Find `shadow_db` in `docker-compose.yml`.
2. Delete the `tmpfs` block.
3. Delete the old “RAM only” comment.
4. Add a new comment explaining the disk-backed volume and reset procedure.
5. Keep `shm_size: 256mb`.
6. Add:
```yaml
volumes:
  - shadow_data:/var/lib/postgresql/data
  - ./infra/postgres/demo.sql:/docker-entrypoint-initdb.d/10-demo.sql:ro
```
7. Add top-level:
```yaml
volumes:
  metadata_data:
  target_data:
  shadow_data:
```
8. Validate with `docker compose config --quiet`.
9. Update README with the 50 MB demo dataset warning.
10. Add reset instructions for `demo.sql` changes.
11. Optionally add a regression test.
12. Commit and push.
13. Output a Patch Report confirming `tmpfs` is gone and `shadow_data` is present.}}
## Task 4: Unify Benchmarking Docs
- Update ALL documents to say "median of 5 runs"
- Remove "mean of 2" references from Evaluation_and_Benchmarking_Strategy.md
- Update List_Risks&Bottlenecks.md to match {{Here is the **exact micro-step execution plan** the AI agent should follow for:
## Task 4: Unify Benchmarking Docs
Goal:
- Remove contradictory latency measurement language.
- Make **all documents** use one canonical phrase:
> **“median-of-5 runs protocol”**
Definition to use everywhere:
> Execute `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` five times, discard the fastest and slowest samples, and report the median of the remaining three samples.
This preserves your current implementation while removing the old “average of next two” contradiction.
---
# Step-by-step micro instructions for the AI agent
## Step 0: Create a safe editing branch
The agent should first ensure it is not editing directly on a dirty main branch.
```bash
git status
git switch main
git pull origin main
git switch -c docs/unify-benchmarking-median-of-5
```
If the repo is already clean and the agent is allowed to commit to main, it can skip branch creation, but branch is safer.
---
## Step 1: Inventory all documentation files
The agent must list every markdown/doc file that could contain benchmarking language.
Run:
```bash
rg --files -g "*.md" -g "*.mdx" -g "*.txt" -g "README*" -g "docs/**"
```
Expected files to inspect:
```text
README.md
AGENTS.md
docs/README.md
docs/phase-1-ui-skeleton.md
docs/phase-2-backend-api.md
docs/phase-3-ml-engine.md
docs/phase-4-integration.md
docs/Evaluation_and_Benchmarking_Strategy.md
docs/List_Risks&Bottlenecks.md
docs/ML_Pipeline_and_Model_Training.md
docs/System_Architecture_and_Data_Flow.md
docs/API_Specification_and_Endpoints.md
docs/User_Control_Flow_AI-Driven_Database_Query_Optimizer_&_Index_Recommender.md
docs/Security_and_Deployment_Strategy.md
docs/Database_Schema_and_Metadata_Model.md
```
If the files are still in root or in `.docx`, the agent should first note that, but for this task it should edit the markdown versions where possible.
---
## Step 2: Search for all conflicting latency phrases
The agent must find every occurrence of contradictory measurement language.
Run:
```bash
rg -n "average|mean|discard the first|next two|3 times|three times|median of 5|median-of-5|median of remaining|steady-state|Warm Cache|Cold Cache|Execution Protocol" .
```
Also run stricter searches:
```bash
rg -n "average the next two" .
rg -n "discard the first run" .
rg -n "Run the query 3 times" .
rg -n "three times" .
rg -n "mean of 2" .
rg -n "median of 5" .
rg -n "median-of-5" .
rg -n "median of the remaining" .
```
The agent must create a mental or written list of every match and classify it into one of these buckets:
### Bucket A: Latency measurement language
Examples:
```text
Run the query 3 times, discard the first run, and average the next two.
Every query is executed 5 times. We discard the minimum and maximum times and report the median.
run the query 5 times and take the median execution time
```
Action:
- Replace with canonical median-of-5 wording.
### Bucket B: Training label generation
Examples:
```text
The ground truth label y for the graph is the median actual execution time of the 5 runs.
```
Action:
- Update to canonical median-of-5 wording.
### Bucket C: Cache warming / cold cache discussion
Examples:
```text
Cold Cache Tests: Restart PostgreSQL and drop OS page cache before every query run.
Warm Cache Tests: Run the query 3 times, discard the first run, and average the next two.
```
Action:
- Keep cold cache concept if useful.
- Delete or rewrite warm cache “average next two” language.
- Ensure all timing uses median-of-5.
### Bucket D: Non-latency averages
Examples:
```text
avg row size
average row width
average execution cost
```
Action:
- Do **not** change these unless they refer to query latency measurement.
- “avg row size” is schema metadata, not benchmarking. Leave it alone.
---
## Step 3: Define the canonical replacement text
The agent must use one consistent paragraph wherever latency measurement is described.
Canonical text:
```markdown
All latency measurements use the **median-of-5 runs protocol**: execute `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` five times, discard the fastest and slowest samples, and report the median of the remaining three samples. This eliminates outlier noise and prevents PostgreSQL cache effects from deciding the reported baseline or optimized time.
```
Short canonical phrase for tables/bullets:
```markdown
median-of-5 runs protocol
```
Extended canonical phrase for method sections:
```markdown
median-of-5 runs protocol: five `EXPLAIN (ANALYZE)` executions, discard min/max, report median of remaining three.
```
The agent must not introduce new variants like:
```text
median of 5
median of three
trimmed median
average median
warm cache average
```
Unless they are explicitly defining the same canonical protocol.
---
## Step 4: Edit `Evaluation_and_Benchmarking_Strategy.md`
This is the primary file.
### 4.1 Open the file
```bash
nvim docs/Evaluation_and_Benchmarking_Strategy.md
```
or equivalent editor.
### 4.2 Find Section 5: Experimental Setup & Reproducibility
Locate:
```markdown
## 5. Experimental Setup & Reproducibility
```
### 4.3 Remove the contradictory warm cache bullet
Delete this type of line:
```markdown
* **Warm Cache Tests:** Run the query 3 times, discard the first run, and average the next two.
```
Also delete any variation:
```markdown
Run the query three times, discard the first run, and average the next two.
```
### 4.4 Replace the execution protocol bullet
Find:
```markdown
* **Execution Protocol:** Every query is executed **5 times**. We discard the minimum and maximum times and report the **median (p50)** of the remaining 3 runs to eliminate outlier noise.
```
Replace with:
```markdown
* **Execution Protocol:** All latency measurements use the **median-of-5 runs protocol**: execute `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` five times, discard the fastest and slowest samples, and report the median of the remaining three samples. This eliminates outlier noise and prevents PostgreSQL cache effects from deciding the reported baseline or optimized time.
```
### 4.5 Adjust cold cache language so it does not conflict
If the file contains:
```markdown
* **Cold Cache Tests:** Restart PostgreSQL and drop OS page cache (`echo 3 > /proc/sys/vm/drop_caches`) before every query run.
```
Change to:
```markdown
* **Cold Cache Option:** For strict cold-cache experiments, restart PostgreSQL and drop the OS page cache before the median-of-5 run sequence. The default reported metric remains the median-of-5 runs protocol.
```
This keeps the concept but removes ambiguity.
### 4.6 Search the whole file again
Run inside the file or via ripgrep:
```bash
rg -n "average|mean|discard the first|next two|3 times|three times" docs/Evaluation_and_Benchmarking_Strategy.md
```
Expected result:
- No matches for latency measurement contradictions.
- Allowed matches only if they refer to non-latency things like “average row size”.
---
## Step 5: Edit `List_Risks&Bottlenecks.md`
### 5.1 Open the file
```bash
nvim docs/List_Risks\&Bottlenecks.md
```
### 5.2 Find Risk 1: The Postgres Query Cache Trap
Locate:
```markdown
#### 1. The Postgres Query Cache Trap (Demo Killer)
```
### 5.3 Replace the fix paragraph
Find text like:
```markdown
Alternatively, run the query 5 times and take the *median* execution time, explicitly stating in your presentation that you are measuring "steady-state" performance.
```
Replace with:
```markdown
All latency measurements use the **median-of-5 runs protocol**: execute `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` five times, discard the fastest and slowest samples, and report the median of the remaining three samples. This is the only accepted steady-state measurement method.
```
### 5.4 Remove old “median execution time” vagueness
Search:
```bash
rg -n "median execution time|take the median|run the query 5 times" docs/List_Risks\&Bottlenecks.md
```
Ensure every match now refers to the full canonical definition.
---
## Step 6: Edit `ML_Pipeline_and_Model_Training.md`
### 6.1 Find ground truth generation
Locate:
```markdown
### 2.2. Ground Truth Generation (The "Labeling" Phase)
```
### 6.2 Replace label assignment wording
Find:
```markdown
The ground truth label y for the graph is the median actual execution time (in milliseconds) of the 5 runs.
```
Replace with:
```markdown
The ground truth label y for the graph is the median actual execution time, in milliseconds, produced by the **median-of-5 runs protocol**: five `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions, discard the fastest and slowest samples, and take the median of the remaining three samples.
```
### 6.3 Replace execution wording
Find:
```markdown
Each generated query is executed 5 times against the target PostgreSQL database to warm up the cache and mitigate OS-level jitter.
```
Replace with:
```markdown
Each generated query is executed using the **median-of-5 runs protocol** against the target PostgreSQL database: five `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions, discard the fastest and slowest samples, and use the median of the remaining three samples as the label.
```
### 6.4 Search file for conflicts
```bash
rg -n "average|mean|discard the first|next two|3 times|three times" docs/ML_Pipeline_and_Model_Training.md
```
Fix any latency-related matches.
---
## Step 7: Edit `System_Architecture_and_Data_Flow.md`
### 7.1 Find Phase 2: Query Ingestion & QEP Extraction
Locate:
```markdown
### Phase 2: Query Ingestion & QEP Extraction
```
### 7.2 Update baseline extraction wording
Find:
```markdown
Executes `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>` against the Target DB.
Captures the raw execution plan JSON and actual execution time.
```
Replace with:
```markdown
Executes the baseline measurement using the **median-of-5 runs protocol**: five `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions against the Target DB, discard the fastest and slowest samples, and capture the median of the remaining three samples as the baseline execution time.
```
### 7.3 Update shadow validation wording
Find:
```markdown
Executes `EXPLAIN (FORMAT JSON) <query>` on the Shadow DB.
```
Replace with:
```markdown
Executes the candidate measurement using the **median-of-5 runs protocol** on the Shadow DB: five `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions with the hypothetical index injected, discard the fastest and slowest samples, and capture the median of the remaining three samples as the validated execution time.
```
Important:
- If the current code uses `EXPLAIN (FORMAT JSON)` without `ANALYZE` for hypothetical validation, the doc should not claim `ANALYZE` unless the code actually does it.
- The agent must check the code first.
So the agent should run:
```bash
rg -n "EXPLAIN|hypopg|median|steady_state|measurement_runs" apps/api packages/ml-engine
```
Then align docs to actual implementation.
If implementation uses:
```python
explain_steady_state()
```
with five runs, document that exactly.
If implementation uses hypothetical `EXPLAIN` without `ANALYZE`, document:
```markdown
For hypothetical index validation, the system uses the planner’s estimated cost from repeated `EXPLAIN (FORMAT JSON)` runs where supported, and reports the median-of-5 estimated planning result. Physical `EXPLAIN (ANALYZE)` is reserved for the real target baseline unless the shadow database contains sufficient data.
```
But based on your patch report, the backend has:
```text
EXPLAIN_MEASUREMENT_RUNS=5
explain_steady_state()
median-of-5 rule
```
So the canonical wording is safe for baseline and likely for shadow validation if the code does it.
---
## Step 8: Edit `User_Control_Flow_AI-Driven_Database_Query_Optimizer_&_Index_Recommender.md`
### 8.1 Find Phase 3: AI Analysis & Recommendation
Locate:
```markdown
## 🧠 Phase 3: AI Analysis & Recommendation
```
### 8.2 Update shadow DB validation wording
Find:
```markdown
Re-runs query with `EXPLAIN ANALYZE`
Measures actual speedup
```
Replace with:
```markdown
Re-runs the query using the **median-of-5 runs protocol**: five `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions, discard the fastest and slowest samples, and measure speedup using the median of the remaining three samples.
```
### 8.3 Find Phase 4: Results & Recommendations
Locate:
```markdown
Execution time: 423ms
```
Add a note below the metrics block:
```markdown
All displayed latency values are median-of-5 run measurements, not single-run timings.
```
### 8.4 Do not change non-latency averages
Leave this alone:
```markdown
avg row size
```
That is schema metadata, not benchmarking.
---
## Step 9: Edit `API_Specification_and_Endpoints.md`
### 9.1 Find analysis models or endpoint descriptions
Search:
```bash
rg -n "execution|time_ms|baseline|optimized|EXPLAIN" docs/API_Specification_and_Endpoints.md
```
### 9.2 Add measurement note to response models
Wherever `time_ms` or `execution_time_ms_before/after` appears, add:
```markdown
Latency fields are reported using the median-of-5 runs protocol.
```
Example:
```python
class AnalysisResult(BaseModel):
    run_id: str
    status: str
    original_metrics: Dict[str, float]
    optimized_metrics: Dict[str, float]
```
Add comment/docstring:
```python
# original_metrics["time_ms"] and optimized_metrics["time_ms"] are median-of-5 run measurements.
```
---
## Step 10: Edit `Security_and_Deployment_Strategy.md`
### 10.1 Find EXPLAIN sandbox section
Search:
```bash
rg -n "EXPLAIN|statement_timeout|transaction|rollback" docs/Security_and_Deployment_Strategy.md
```
### 10.2 Add measurement consistency note
After the transaction-wrapped EXPLAIN explanation, add:
```markdown
Each timing sample is executed inside its own transaction with `SET LOCAL statement_timeout` and rollback. The reported baseline and validated latency values use the **median-of-5 runs protocol**: five samples, discard fastest and slowest, report median of remaining three.
```
This is important because your patch report says:
```text
Every sample keeps its own transaction + SET LOCAL statement_timeout + rollback.
```
The doc must reflect that.
---
## Step 11: Edit `Database_Schema_and_Metadata_Model.md`
### 11.1 Find execution metrics table
Locate:
```markdown
### Table 6: `execution_metrics`
```
### 11.2 Update column descriptions
Change:
```markdown
Actual time in ms without the index.
```
To:
```markdown
Median-of-5 baseline execution time in ms without the index.
```
Change:
```markdown
Actual time in ms with the index (via hypopg).
```
To:
```markdown
Median-of-5 validated execution time in ms with the hypothetical index applied via hypopg.
```
---
## Step 12: Edit README.md
### 12.1 Find Phase 2 or Phase 3 summary
Search:
```bash
rg -n "median of 5|median-of-5|EXPLAIN|baseline|cache" README.md
```
### 12.2 Replace any inconsistent wording
Ensure README says:
```markdown
The baseline is the **median-of-5 runs protocol**: five `EXPLAIN (ANALYZE)` runs, fastest and slowest dropped, median of remaining three reported.
```
If README currently says:
```markdown
median of 5 runs
```
that is okay, but expand it once to the full definition.
---
## Step 13: Edit phase docs under `docs/`
The agent must inspect:
```text
docs/phase-2-backend-api.md
docs/phase-3-ml-engine.md
docs/phase-4-integration.md
```
Search:
```bash
rg -n "average|mean|median|cache|EXPLAIN|steady-state|measurement" docs/phase-*.md
```
Replace latency-related contradictions with canonical wording.
Important:
- Do not rewrite entire phase records.
- Only patch the measurement language.
- Preserve historical notes if they explicitly say “previous behavior was changed”.
If a phase doc says:
```text
Patch 2 implemented median-of-5
```
leave it.
If it says:
```text
average next two
```
fix it.
---
## Step 14: Edit `AGENTS.md` / `REVIEWER_AND_ENFORCER.md`
The constitution files must also enforce the unified rule.
Search:
```bash
rg -n "median|average|benchmark|cache|EXPLAIN" AGENTS.md REVIEWER_AND_ENFORCER.md .cursorrules 2>/dev/null
```
Add or update a quality gate:
```markdown
**Benchmarking Failure:** If any document or code path reports latency using a single run, an average of two runs, or “discard first then average next two”, REJECT AND REWRITE. All latency metrics must use the median-of-5 runs protocol: five `EXPLAIN (ANALYZE)` samples, discard fastest and slowest, report median of remaining three.
```
---
## Step 15: Run final verification greps
The agent must run these commands and inspect every result.
### 15.1 Forbidden phrases
```bash
rg -n "average the next two" .
rg -n "discard the first run" .
rg -n "Run the query 3 times" .
rg -n "run the query three times" .
rg -n "mean of 2" .
rg -n "mean of two" .
rg -n "average next two" .
```
Expected:
```text
No matches.
```
If matches exist, they must be either:
- In a changelog saying “removed old average-next-two method”, or
- Non-latency context.
Otherwise, fix them.
### 15.2 Canonical phrase presence
```bash
rg -n "median-of-5 runs protocol" .
```
Expected files with matches:
```text
README.md
AGENTS.md
docs/Evaluation_and_Benchmarking_Strategy.md
docs/List_Risks&Bottlenecks.md
docs/ML_Pipeline_and_Model_Training.md
docs/System_Architecture_and_Data_Flow.md
docs/User_Control_Flow_AI-Driven_Database_Query_Optimizer_&_Index_Recommender.md
docs/API_Specification_and_Endpoints.md
docs/Security_and_Deployment_Strategy.md
docs/Database_Schema_and_Metadata_Model.md
docs/phase-2-backend-api.md
docs/phase-3-ml-engine.md
docs/phase-4-integration.md
```
Not every file must contain the full phrase, but the core method docs must.
### 15.3 Check for ambiguous “median of 5”
```bash
rg -n "median of 5|median of five|median of the remaining" .
```
The agent should normalize these to:
```text
median-of-5 runs protocol
```
unless the sentence already defines it clearly.
---
## Step 16: Check code/docs alignment
The agent must verify the docs match actual implementation.
Run:
```bash
rg -n "EXPLAIN_MEASUREMENT_RUNS|explain_steady_state|median|measurement_runs" apps/api packages/ml-engine
```
Expected evidence:
```text
EXPLAIN_MEASUREMENT_RUNS default 5
explain_steady_state()
discard fastest and slowest
median of remaining samples
```
If code differs from docs, the agent must update docs to match code, not the other way around, unless instructed to change code.
For this task, docs only.
---
## Step 17: Run documentation lint/build if available
If the repo has docs lint:
```bash
make docs-lint
```
or:
```bash
npm run docs:lint
```
If not, skip.
At minimum, ensure markdown files are valid and no broken links were introduced.
Run:
```bash
rg -n "\\]\\(" docs README.md
```
Check relative links still point to existing files.
---
## Step 18: Produce a patch report
The agent must output a report in this format:
```markdown
# Task 4 Report — Unified Benchmarking Docs
## Canonical rule introduced
All latency measurements now use:
“median-of-5 runs protocol: five EXPLAIN (ANALYZE) samples, discard fastest and slowest, report median of remaining three.”
## Files changed
- docs/Evaluation_and_Benchmarking_Strategy.md
- docs/List_Risks&Bottlenecks.md
- docs/ML_Pipeline_and_Model_Training.md
- docs/System_Architecture_and_Data_Flow.md
- docs/User_Control_Flow_AI-Driven_Database_Query_Optimizer_&_Index_Recommender.md
- docs/API_Specification_and_Endpoints.md
- docs/Security_and_Deployment_Strategy.md
- docs/Database_Schema_and_Metadata_Model.md
- README.md
- AGENTS.md
## Contradictions removed
- Removed “Run the query 3 times, discard the first run, and average the next two.”
- Removed “mean of 2” / “average next two” language.
- Replaced vague “median of 5” references with canonical median-of-5 runs protocol.
## Verification
- `rg "average the next two" .` → no matches
- `rg "discard the first run" .` → no matches
- `rg "Run the query 3 times" .` → no matches
- `rg "median-of-5 runs protocol" .` → matches in core docs
- Code alignment checked against `EXPLAIN_MEASUREMENT_RUNS` and `explain_steady_state()`.
## Residual risks
- Some `.docx` blueprints may still contain old wording if not converted to markdown.
- Historical phase notes may mention old method as prior behavior; these were preserved only if clearly marked as changelog.
```
---
## Step 19: Commit
```bash
git add docs README.md AGENTS.md
git status
git commit -m "docs: unify benchmarking latency measurement to median-of-5 runs protocol"
```
Then push:
```bash
git push -u origin docs/unify-benchmarking-median-of-5
```
Or if direct main is allowed:
```bash
git switch main
git merge docs/unify-benchmarking-median-of-5
git push origin main
```
---
# Exact prompt to give your AI agent
You can paste this directly:
```text
Execute Task 4: Unify Benchmarking Docs.
Objective:
Remove all contradictory latency measurement language from the project documentation and make every document use one canonical method:
"median-of-5 runs protocol: execute EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) five times, discard the fastest and slowest samples, and report the median of the remaining three samples."
Rules:
1. Do not change code in this task. Docs only.
2. Do not alter non-latency averages such as "avg row size".
3. Preserve historical changelog notes only if they clearly describe old behavior that was removed.
4. Align documentation with the actual implementation by checking:
   - EXPLAIN_MEASUREMENT_RUNS
   - explain_steady_state()
   - median logic in apps/api and packages/ml-engine
5. If docs and code disagree, update docs to match code.
Files to inspect and update:
- README.md
- AGENTS.md
- docs/README.md
- docs/Evaluation_and_Benchmarking_Strategy.md
- docs/List_Risks&Bottlenecks.md
- docs/ML_Pipeline_and_Model_Training.md
- docs/System_Architecture_and_Data_Flow.md
- docs/User_Control_Flow_AI-Driven_Database_Query_Optimizer_&_Index_Recommender.md
- docs/API_Specification_and_Endpoints.md
- docs/Security_and_Deployment_Strategy.md
- docs/Database_Schema_and_Metadata_Model.md
- docs/phase-2-backend-api.md
- docs/phase-3-ml-engine.md
- docs/phase-4-integration.md
Required edits:
A. In docs/Evaluation_and_Benchmarking_Strategy.md:
- Remove:
  "Warm Cache Tests: Run the query 3 times, discard the first run, and average the next two."
- Replace Execution Protocol with:
  "All latency measurements use the median-of-5 runs protocol: execute EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) five times, discard the fastest and slowest samples, and report the median of the remaining three samples. This eliminates outlier noise and prevents PostgreSQL cache effects from deciding the reported baseline or optimized time."
- If Cold Cache Tests are mentioned, rewrite so cold cache is optional and the reported metric still uses median-of-5.
B. In docs/List_Risks&Bottlenecks.md:
- Replace the Postgres Query Cache Trap fix with the canonical median-of-5 runs protocol wording.
C. In docs/ML_Pipeline_and_Model_Training.md:
- Update ground truth label generation to use median-of-5 runs protocol.
- Replace "median actual execution time of the 5 runs" with the full canonical definition.
D. In docs/System_Architecture_and_Data_Flow.md:
- Update baseline extraction and shadow validation to state median-of-5 runs protocol.
- Ensure wording matches actual code.
E. In docs/User_Control_Flow...:
- Update Phase 3 validation wording.
- Add note that displayed latency values are median-of-5 measurements.
- Do not change "avg row size".
F. In docs/API_Specification_and_Endpoints.md:
- Add note that time_ms fields are median-of-5 measurements.
G. In docs/Security_and_Deployment_Strategy.md:
- Add note that each timing sample runs in its own transaction with SET LOCAL statement_timeout and rollback, and reported latency uses median-of-5.
H. In docs/Database_Schema_and_Metadata_Model.md:
- Update execution_metrics column descriptions to say median-of-5 baseline/validated time.
I. In README.md and phase docs:
- Replace any inconsistent wording with canonical median-of-5 runs protocol.
J. In AGENTS.md / reviewer enforcer rules:
- Add a quality gate rejecting single-run, average-next-two, or mean-of-2 latency reporting.
Verification commands to run:
rg -n "average the next two" .
rg -n "discard the first run" .
rg -n "Run the query 3 times" .
rg -n "run the query three times" .
rg -n "mean of 2" .
rg -n "mean of two" .
rg -n "median-of-5 runs protocol" .
rg -n "EXPLAIN_MEASUREMENT_RUNS|explain_steady_state|median|measurement_runs" apps/api packages/ml-engine
Expected:
- No forbidden latency phrases remain.
- Core docs contain canonical phrase.
- Docs align with code.
Output:
Provide a Task 4 Report listing files changed, contradictions removed, verification results, and residual risks.
Then commit with:
git commit -m "docs: unify benchmarking latency measurement to median-of-5 runs protocol"
```
---
# The most important detail the agent must not miss
The old docs contain this contradiction:
```text
Warm Cache Tests: Run the query 3 times, discard the first run, and average the next two.
Execution Protocol: Every query is executed 5 times. We discard the minimum and maximum times and report the median of the remaining 3 runs.
```
The agent must not simply replace one and leave the other.
It must make the entire measurement philosophy singular:
```text
There is only one reported latency method: median-of-5 runs protocol.
```
If any document still says:
```text
average
mean
discard first
next two
three times
```
in the context of query latency, the task is incomplete.}}
## Task 5: Fix Polling vs WebSocket
- Update README to say "WebSocket for progress streaming"
- Remove REST polling references from User_Control_Flow.md
- Verify frontend uses WebSocket, not polling {{Here is the exact, mechanical, micro-step sequence the AI agent will follow to execute Task 5. Read every line. This is not a suggestion; this is the literal execution trace.
---
## Task 5: Fix Polling vs WebSocket — Micro-Step Execution Trace
---
### STEP 1: Establish Ground Truth (Read the Actual Code)
The AI must first determine **what the code actually does** before touching any documentation.
**Micro-step 1.1:** Open `apps/web/src/lib/api.ts` (or equivalent API client file). Search for the string `poll`, `setInterval`, `setTimeout`, or `refetchInterval`.
```bash
grep -rn "poll\|setInterval\|refetchInterval\|useQuery" apps/web/src/lib/ apps/web/src/store/
```
**Micro-step 1.2:** Search for WebSocket usage in the same files.
```bash
grep -rn "WebSocket\|ws://\|wss://\|useWebSocket\|EventSource\|SSE" apps/web/src/lib/ apps/web/src/store/
```
**Micro-step 1.3:** Open `apps/web/src/store/useAnalysisStore.ts`. Read the `startAnalysis` or `optimize` action. Determine: Does it call `fetch('/queries/{id}/status')` in a loop (polling)? Or does it open a `new WebSocket(...)` and listen for `onmessage` events?
**Micro-step 1.4:** Open `apps/api/src/api/routes.py` (or `endpoints/`). Search for the `/queries/{run_id}/status` endpoint. Note whether it exists. Then search for a WebSocket route:
```bash
grep -rn "websocket\|WebSocket\|ws/" apps/api/src/api/
```
**Decision Gate:** The AI now knows the truth. One of three scenarios:
| Scenario | Code Reality | Action |
|----------|-------------|--------|
| A | Frontend polls, backend has `/status` REST endpoint | **Code is wrong.** Fix code to use WebSocket. |
| B | Frontend uses WebSocket, backend has `WS /ws/copilot/{run_id}` | **Code is correct.** Only fix docs. |
| C | Mixed: Copilot uses WS, but optimization progress uses polling | **Partial fix.** Unify to WebSocket for both. |
---
### STEP 2: Fix the Frontend Code (If Scenario A or C)
**Micro-step 2.1:** In `apps/web/src/store/useAnalysisStore.ts`, locate the polling loop. It will look something like:
```typescript
// BAD - polling
const pollStatus = async (runId: string) => {
  const interval = setInterval(async () => {
    const res = await fetch(`/api/v1/queries/${runId}/status`);
    const data = await res.json();
    if (data.status === 'completed') clearInterval(interval);
  }, 500);
};
```
**Micro-step 2.2:** Replace it with a WebSocket connection:
```typescript
// GOOD - WebSocket
const connectOptimizeStream = (runId: string) => {
  const ws = new WebSocket(`ws://localhost:8000/api/v1/ws/optimize/${runId}`);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case 'log_update': appendLogLine(msg.payload); break;
      case 'progress': setProgress(msg.payload.percentage); break;
      case 'complete': setResult(msg.payload); ws.close(); break;
      case 'error': setError(msg.payload.message); ws.close(); break;
    }
  };
  ws.onerror = () => setError('WebSocket connection failed');
  ws.onclose = () => { if (!result) setError('Stream closed unexpectedly'); };
  return ws;
};
```
**Micro-step 2.3:** Remove the `setInterval` / `clearInterval` logic entirely. Remove the `refetchInterval` from any TanStack Query hooks (if they still exist from the dead dependency).
**Micro-step 2.4:** In `apps/web/src/lib/api.ts`, delete the `getRunStatus(runId)` function that calls `GET /queries/{run_id}/status`. Replace with `createOptimizeWebSocket(runId)` that returns the WS instance.
**Micro-step 2.5:** Ensure the WebSocket URL is configurable via env var:
```typescript
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
```
Verify this matches `docker-compose.yml`'s `NEXT_PUBLIC_WS_URL` build arg.
---
### STEP 3: Fix the Backend Code (If Scenario A)
**Micro-step 3.1:** In `apps/api/src/api/routes.py`, locate the `GET /queries/{run_id}/status` endpoint. **Do not delete it yet.** Mark it as deprecated:
```python
@router.get("/queries/{run_id}/status", deprecated=True)
async def get_run_status(run_id: str):
    """DEPRECATED: Use WS /ws/optimize/{run_id} for real-time progress."""
    ...
```
**Micro-step 3.2:** Verify the WebSocket endpoint exists at `WS /ws/optimize/{run_id}`. If it does not, create it:
```python
@router.websocket("/ws/optimize/{run_id}")
async def optimize_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()
    try:
        async for event in pipeline.stream_events(run_id):
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from optimize stream {run_id}")
    finally:
        await websocket.close()
```
**Micro-step 3.3:** In `apps/api/src/services/pipeline.py`, ensure the optimization orchestrator emits events as an async generator:
```python
async def stream_events(self, run_id: str) -> AsyncGenerator[dict, None]:
    yield {"type": "log_update", "payload": {"ts": now(), "message": "Parsing EXPLAIN..."}}
    # ... after each phase ...
    yield {"type": "progress", "payload": {"percentage": 30}}
    # ... after GNN ...
    yield {"type": "log_update", "payload": {"ts": now(), "message": "GNN inference complete"}}
    # ... after hypopg ...
    yield {"type": "complete", "payload": result_dict}
```
**Micro-step 3.4:** Add heartbeat/ping to prevent zombie connections (fixes the WebSocket leak from the master list):
```python
import asyncio
async def optimize_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()
    ping_task = asyncio.create_task(_heartbeat(websocket, interval=30))
    try:
        async for event in pipeline.stream_events(run_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        await websocket.close()
async def _heartbeat(ws: WebSocket, interval: int):
    try:
        while True:
            await asyncio.sleep(interval)
            await ws.send_json({"type": "ping"})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
```
---
### STEP 4: Fix the Documentation
**Micro-step 4.1:** Open `docs/phase-2-backend-api.md`. Find any mention of:
- "Polling endpoint"
- "GET /queries/{run_id}/status"
- "Frontend polls for updates"
Replace with:
- "WebSocket stream at `WS /ws/optimize/{run_id}`"
- "Real-time progress via WebSocket events"
- "Legacy REST status endpoint retained for backward compatibility only (deprecated)"
**Micro-step 4.2:** Open `docs/blueprints/` (the converted `.md` files). Find `User Control Flow` content. Locate Phase 3 ("AI Analysis & Recommendation"). The current text says:
> *"Progress bar: 'Parsing QEP → Running GNN → Testing indexes → Validating...'"*
Replace with:
> *"WebSocket stream delivers timestamped log events (`log_update`), progress percentages (`progress`), and final result (`complete`). The frontend renders these in the Streaming Log Overlay. No polling. No `setInterval`."*
**Micro-step 4.3:** Open `README.md`. In the "What is in Phase 4" section, find:
> *"the console calls `POST /queries/analyze`, **polls** the run, and renders the returned DAG."*
Replace with:
> *"the console calls `POST /queries/analyze`, **opens a WebSocket stream** at `/ws/optimize/{run_id}`, receives real-time log/progress/complete events, and renders the returned DAG."*
**Micro-step 4.4:** In the same README, find the "What is in Phase 2" section. If it mentions the `/status` polling endpoint as a primary feature, add:
> *"(Deprecated: retained only for non-WebSocket fallback. Primary path is `WS /ws/optimize/{run_id}`.)"*
**Micro-step 4.5:** Open `API_Specification_and_Endpoints.md` (in `docs/blueprints/`). Section 3.2 currently defines `GET /queries/{run_id}/status` as the primary progress mechanism. Restructure:
- Move the WebSocket section (currently Section 4) **above** the REST polling section.
- Mark the REST `/status` endpoint as `[DEPRECATED — use WS /ws/optimize/{run_id}]`.
- Add the new `WS /ws/optimize/{run_id}` endpoint spec with the exact event schema:
```json
// Server → Client events (in order):
{"type": "log_update", "payload": {"ts": "...", "level": "info|run|ok|err", "text": "..."}}
{"type": "progress", "payload": {"percentage": 0-100, "step": "parsing|gnn|hypopg|done"}}
{"type": "complete", "payload": { /* full AnalysisResult */ }}
{"type": "error", "payload": {"code": "...", "message": "..."}}
{"type": "ping"}  // heartbeat every 30s
```
---
### STEP 5: Fix the `REVIEWER_AND_ENFORCER.md` / `AGENTS.md`
**Micro-step 5.1:** Add a new rule to the "NEVER" list:
> **- NEVER use `setInterval` or REST polling for optimization progress. All real-time streaming MUST use WebSocket (`WS /ws/optimize/{run_id}`). The deprecated `/queries/{run_id}/status` REST endpoint exists only for non-WS fallback and must never be the primary path.**
**Micro-step 5.2:** Add to the Anti-Drift Checklist:
> - [ ] Does this introduce a `setInterval` or `refetchInterval` for progress tracking? (If yes, REJECT — use WebSocket.)
---
### STEP 6: Verify (Run Tests + Manual Check)
**Micro-step 6.1:** Run the API test suite:
```bash
cd apps/api && .venv/bin/python -m pytest tests/ -v
```
Confirm no tests reference the old polling flow as the primary assertion. If `test_pipeline.py` asserts on `GET /status`, update it to assert on the WebSocket event sequence.
**Micro-step 6.2:** Run the frontend type check:
```bash
cd apps/web && npm run typecheck
```
Confirm no TypeScript errors from removed `pollStatus` function or changed store interface.
**Micro-step 6.3:** Manual verification:
1. `docker compose up -d`
2. Open `http://localhost:3000`
3. Paste a query. Press `Ctrl+Enter`.
4. Open DevTools → Network tab → filter by `WS`.
5. Confirm a WebSocket connection opens to `ws://localhost:8000/api/v1/ws/optimize/{uuid}`.
6. Confirm log lines stream in the Center Pane overlay in real-time.
7. Confirm NO `GET /queries/{uuid}/status` requests appear in the Network tab during the optimization.
8. Confirm the DAG renders after the `complete` event.
9. Close the browser tab mid-optimization. Confirm the backend logs `Client disconnected from optimize stream` and the ping task is cancelled (no zombie).
**Micro-step 6.4:** Grep the entire codebase for any remaining polling references:
```bash
grep -rn "setInterval\|pollStatus\|refetchInterval\|polling" apps/ packages/ docs/ README.md
```
Expected result: Only the deprecated REST endpoint definition and its docstring. Zero hits in frontend code. Zero hits in active documentation.
---
### STEP 7: Commit
**Micro-step 7.1:** Stage and commit:
```bash
git add -A
git commit -m "fix(task-5): unify progress streaming to WebSocket, deprecate REST polling, update all docs
- Frontend: replaced setInterval polling with WS /ws/optimize/{run_id}
- Backend: added heartbeat ping (30s) to prevent zombie connections
- Docs: updated README, phase-2, phase-4, API spec, User Control Flow
- Constitution: added WebSocket-only rule to AGENTS.md NEVER list
- Verified: 0 polling references in active code, WS confirmed in DevTools"
```
**Micro-step 7.2:** Push and verify remote:
```bash
git push origin main
git ls-remote origin main  # confirm SHA matches
```
---
### Summary: What the AI Literally Does
| Step | File(s) Touched | Action |
|------|----------------|--------|
| 1 | `api.ts`, `useAnalysisStore.ts`, `routes.py` | **Read only.** Determine truth. |
| 2 | `useAnalysisStore.ts`, `api.ts` | **Edit.** Replace polling with WS. |
| 3 | `routes.py`, `pipeline.py` | **Edit.** Add WS endpoint + heartbeat. |
| 4 | `README.md`, `docs/phase-2`, `docs/phase-4`, `docs/blueprints/*` | **Edit.** Replace "poll" with "WebSocket". |
| 5 | `AGENTS.md` | **Edit.** Add NEVER rule. |
| 6 | All | **Run.** Tests + grep + manual browser check. |
| 7 | Git | **Commit + Push.** |
That is the exact mechanical trace. The AI does not "think" about it. It greps, reads, replaces, tests, commits. Every step is binary: the string `setInterval` either exists in the frontend or it does not. The WebSocket either connects in DevTools or it does not. No ambiguity. No hallucination.}}