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
- `TARGET_ALLOW_MAINTENANCE` stays `false`: the read-only target role cannot `VACUUM`, and the API
  logs `Skipping VACUUM ANALYZE…` instead of attempting it.

### 6. Analysis pipeline

1. Validate the SQL with sqlglot (single read-only `SELECT`).
2. Load the encrypted DSN, connect with the stored SSL mode.
3. Capture baseline `EXPLAIN (ANALYZE, FORMAT JSON)`; introspect schema in one query.
4. Convert the plan into API DAG nodes/edges; attention scores are heuristic in Phase 2.
5. Derive candidate indexes from equality/join/range/ordering predicates.
6. Validate each candidate with `hypopg` in the shadow DB, recording the speedup and keeping the
   fastest optimised plan.
7. Return `CREATE INDEX CONCURRENTLY` scripts, storage overhead, write impact, and confidence.

If the shadow DB is unavailable, the baseline DAG and metrics are returned unchanged with
`validated_speedup_factor = null` — a validation failure never erases results.

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
docker compose up -d --build    # metadata_db, target_db, shadow_db, api, nginx

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
`http://localhost:8080` with the same routes.

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
