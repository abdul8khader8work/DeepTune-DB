# Phase 2 — Backend API & Security

**Status:** Complete (unit-tested; container stack defined but not executed on this machine)
**Scope:** `apps/api/`, `infra/`, root `docker-compose.yml`, root `.env.example`, `Makefile`.
**Source of truth:** `GOD_FILE.docx`, `MASTER_EXECUTION_PLAN.md.docx`, `REVIEWER&Enforcer.docx`,
`API_Specification_and_Endpoints.docx`, `Security_and_Deployment_Strategy.docx`,
`Database_Schema_and_Metadata_Model.docx`.

## Deliverables

### 1. FastAPI service (`apps/api`)

| Layer | Files | Responsibility |
|---|---|---|
| Core | `src/core/config.py`, `errors.py`, `security.py`, `logging.py`, `ratelimit.py` | Settings, uniform error envelope, Fernet encryption, HS256 JWT, redacting logs, per-IP limits |
| API | `src/api/deps.py`, `src/api/v1/*`, `src/api/legacy.py` | Bearer-token dependency, v1 routes, three compatibility aliases |
| Schemas | `src/schemas/*` | Pydantic v2 models with `strict=True`, `extra="forbid"` |
| DB | `src/db/metadata.py`, `target.py`, `shadow.py` | Encrypted connection store, read-only target connections, hypopg shadow sessions |
| Services | `src/services/*` | sqlglot guard, EXPLAIN sandbox, introspection, DAG builder, candidates, run registry, pipeline |
| CLI | `src/cli/token.py` | `python -m src.cli.token --subject dev` |

### 2. HTTP surface

All canonical routes live under `/api/v1`. `/health` is public; everything else requires
`Authorization: Bearer <token>` when `AUTH_ENABLED=true`.

| Method | Path | Result |
|---|---|---|
| `GET` | `/api/v1/health` | Version, environment, auth flag, shadow/metadata status |
| `POST` | `/api/v1/databases/connect` | Validates credentials, stores the encrypted DSN, returns `connection_id` + version |
| `GET` | `/api/v1/databases/{connection_id}/schema` | Tables, columns, PKs, existing indexes, row estimates |
| `DELETE` | `/api/v1/databases/{connection_id}` | Removes the stored DSN |
| `POST` | `/api/v1/queries/analyze` | Validates SQL synchronously, then runs the pipeline in a background task (`202`) |
| `GET` | `/api/v1/queries/{run_id}/status` | `queued → parsing → gnn_inference → hypopg_validation → completed/failed` |
| `GET` | `/api/v1/queries/{run_id}/results` | Baseline/optimised metrics, DAG nodes + edges, validated recommendations |
| `POST` | `/api/v1/recommendations/{id}/apply` | Creates the hypothetical index in the shadow DB only |
| `POST` | `/api/v1/recommendations/{id}/revert` | Drops the hypothetical index and closes the session |

Compatibility aliases (hidden from OpenAPI): `POST /api/connect`, `POST /api/analyze`,
`POST /api/apply_index` (`{"recommendation_id": "..."}`).

### 3. Security controls

| Requirement | Implementation |
|---|---|
| Read-only target role | `infra/postgres/grants.sql` grants `SELECT` only and revokes DML/DDL |
| No regex SQL sanitising | `src/services/sql_guard.py` parses with `sqlglot` (`read="postgres"`), requires exactly one statement and a `SELECT` root, rejects all write/DDL/transaction nodes |
| EXPLAIN sandbox | `src/services/explain.py` opens a transaction, `SET LOCAL statement_timeout = '<ms>'`, runs `EXPLAIN (ANALYZE, FORMAT JSON)`, then **always** rolls back |
| No auto-DDL on target | Only the shadow DB ever sees `hypopg_create_index`; recommendations are emitted as `CREATE INDEX CONCURRENTLY` text for review |
| Credential encryption at rest | `src/core/security.py` derives a Fernet key from `CREDENTIAL_ENCRYPTION_KEY`; only ciphertext reaches the metadata DB |
| CORS | `CORS_ORIGINS` defaults to `http://localhost:3000`; credentials + `Authorization` header allowed |
| Rate limit | `slowapi` limits `/queries/analyze` (`ANALYZE_RATE_LIMIT`, default `10/minute`); nginx adds a second 10 r/m zone |
| Max SQL length | `MAX_SQL_LENGTH` (10,000) enforced before parsing and mirrored in the Pydantic model |
| Auth | HS256 JWT with `aud` check, 12h default TTL; tokens minted out-of-band by the CLI (no invented login endpoint) |
| Secret leakage | `src/core/logging.py` redacts DSN passwords and `password=` values; `mask_dsn` is available for explicit logs |
| Containers | API image runs as a non-root user; all published ports bind `127.0.0.1` |

### 4. Metadata DB

`infra/postgres/metadata.sql` defines `target_databases(connection_id, encrypted_dsn, ssl_mode,
created_at)` and an unused `analysis_runs` table reserved for Phase 4. When the metadata DB is
unreachable the API logs a warning and falls back to an in-memory store so local development
still works; the health endpoint reports which store is active.

### 5. Shadow database

- `infra/shadow_db/Dockerfile` installs `postgresql-16-hypopg` on top of `postgres:16-bookworm`.
- The data directory is a `tmpfs`, so hypothetical indexes never persist.
- `infra/postgres/demo.sql` seeds an identical schema (20k customers, 5k products, 120k orders)
  in both the target and shadow DBs and runs `VACUUM ANALYZE` once at init.
- `TARGET_ALLOW_MAINTENANCE` defaults to `true` (Patch 2): the pipeline attempts `VACUUM ANALYZE`
  before measuring the baseline, because stale planner statistics are the most common reason a
  correct query gets a bad plan. The read-only target role cannot `VACUUM` (it needs table
  ownership), so a refusal or timeout is logged as
  `VACUUM ANALYZE not applied (…)` and the run continues. Set the flag to `false` to skip the
  attempt entirely.

### 6. Analysis pipeline

1. Validate the SQL with sqlglot (single read-only `SELECT`).
2. Load the encrypted DSN, connect with the stored SSL mode.
3. Attempt `VACUUM ANALYZE` (best effort; see above), then capture the baseline
   `EXPLAIN (ANALYZE, FORMAT JSON)` and introspect the schema in one query.
4. Convert the plan into API DAG nodes/edges; attention scores are heuristic in Phase 2.
5. Derive candidate indexes from equality/join/range/ordering predicates.
6. Validate each candidate with `hypopg` in the shadow DB, recording the speedup and keeping the
   fastest optimised plan.
7. Return `CREATE INDEX CONCURRENTLY` scripts, storage overhead, write impact, and confidence.

#### Steady-state measurement (Patch 2)

A single `EXPLAIN (ANALYZE)` is biased by Postgres caching: the first execution pays for cold
shared buffers and an immediate repeat can beat the steady state. `services/explain.py` now
exposes `explain_steady_state()`, the "median of 5" rule:

```text
run EXPLAIN (ANALYZE) N times (default 5, EXPLAIN_MEASUREMENT_RUNS)
sort by Execution Time
drop the fastest and the slowest sample
return the median of the remaining N-2 runs (the whole result: plan, cost, rows)
```

- The target baseline uses it, so `original_metrics.time_ms` is a median rather than a
  cache-cold first run.
- `validate_index()` applies the same N runs to both the baseline and the indexed measurement, so
  `validated_speedup_factor` compares like with like instead of a median against one sample.
  Cost is `2 × N` EXPLAINs per candidate; set `EXPLAIN_MEASUREMENT_RUNS=1` to restore the old
  single-shot behaviour.
- Every sample still runs in its own transaction with `SET LOCAL statement_timeout` and rollback;
  the rule changes how many times the sandbox runs, never how it runs.


If the shadow DB is unavailable, the baseline DAG and metrics are returned unchanged with
`validated_speedup_factor = null` — a validation failure never erases results.

### 7. Patch 2: DevOps cleanup

- `@tanstack/react-query` is gone from `apps/web/package.json` and `package-lock.json` (it had
  zero imports; client state is `zustand`).
- `docker-compose.yml` gained a `web` service: `apps/web/Dockerfile` builds the Next.js app in a
  multi-stage `node:20-alpine` image, `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_WS_URL` are build args
  (Next inlines them), and the container listens on `127.0.0.1:3000`.
- The `Makefile` is cross-platform: `$(PYTHON)` and `$(BASE_PYTHON)` are selected from `$(OS)`
  (`.venv/Scripts/python.exe` vs `.venv/bin/python`), and `$(ENV_PATH)` switches
  `PYTHONPATH=src` between `cmd.exe` (`set PYTHONPATH=src&&`) and POSIX syntax.
- The `ml-engine` checkpoint/ONNX boundaries no longer use `Any`: `MetricValue`/`MetadataValue`
  aliases in `models/checkpoint.py`, and `Data`, `GATv2Conv`, `InferenceSession`, `Tensor` in
  `models/onnx.py`. Raw EXPLAIN JSON keeps `dict[str, Any]` on purpose — Postgres plan payloads
  are untyped trees validated at the parser boundary, not a model contract.
- Tests: 68 API (was 61), 79 ml-engine (unchanged).

## Verification

Run from `apps/api/` with Python 3.11:

| Command | Result |
|---|---|
| `python -m pytest` | **40 passed** (SQL guard, encryption/JWT, EXPLAIN rollback, DAG, recommender, pipeline fallback, HTTP contract, legacy aliases, CORS) |
| `python -m compileall -q src tests` | Pass |
| `uvicorn src.main:app --port 8011` + `/api/v1/health` | `{"status":"ok", ...}` |
| `/openapi.json` | All v1 paths present |

Not executed on this machine: `docker compose up`. Docker is not installed and the local
PostgreSQL 18 instance has no `hypopg` extension, so the containerised hypopg round-trip is
documented rather than demonstrated. Unit tests stub the database boundary.

## How to run

```bash
cp .env.example .env            # fill in secrets
docker compose up -d --build    # metadata_db, target_db, shadow_db, api, web, nginx

# Mint a dev token (inside apps/api or the api container)
python -m src.cli.token --subject dev

curl -s localhost:8000/api/v1/health
curl -s -X POST localhost:8000/api/v1/databases/connect \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"host":"target_db","port":5432,"dbname":"target_db","user":"query_optimizer","password":"query_optimizer_dev_password","ssl_mode":"prefer"}'
curl -s -X POST localhost:8000/api/v1/queries/analyze \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"connection_id":"<id>","sql_query":"SELECT * FROM orders WHERE status = '\''paid'\'' ORDER BY created_at DESC","optimization_goal":"balanced"}'
```

Then poll `/queries/{run_id}/status` and fetch `/queries/{run_id}/results`. The nginx path is
`http://localhost:8080` with the same routes, and the containerised UI is at
`http://localhost:3000` (`make dev` runs it with hot reload instead).

## Reviewer checklist

- [x] Only `apps/api/`, `infra/`, root `docker-compose.yml`, `.env.example`, `Makefile` touched.
- [x] `async def` endpoints and `asyncpg` only; no blocking DB I/O in handlers.
- [x] No regex SQL validation; sqlglot AST + single-statement + SELECT-root checks.
- [x] `EXPLAIN (ANALYZE)` only inside a transaction with a 5s `statement_timeout` and rollback.
- [x] Target role is SELECT-only; no DDL is applied to the target.
- [x] DSNs encrypted at rest; logs redact credentials.
- [x] CORS restricted to `http://localhost:3000`; analyze endpoint rate-limited.
- [x] SQL length capped at 10,000 characters.
- [x] Shadow DB uses `hypopg` on `tmpfs`; recommendations are `CREATE INDEX CONCURRENTLY`.
- [x] Pydantic models are strict; every response has a typed model.
- [x] No imports from `apps/web` or `packages/ml-engine`; no ML training logic in the API.
- [x] `.env` files and model weights remain git-ignored.

## Deferred to later phases

- Real GATv2 inference, beam search, and symbolic pruning (Phase 3) replace the heuristic scorer;
  the request/response contract is already frozen.
- Persisting runs/recommendations (currently in memory with `RUN_TTL_SECONDS`).
- WebSocket `/ws/copilot/{run_id}` streaming (Phase 4).
- Automatic target-schema replication into the shadow DB; Phase 2 expects both to share the demo
  schema, which `docker-compose` guarantees.
