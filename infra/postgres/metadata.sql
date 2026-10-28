-- App Metadata DB: encrypted target DSNs only. No query text is persisted in
-- Phase 2 (runs and recommendations live in process memory with a TTL).

CREATE TABLE IF NOT EXISTS target_databases (
    connection_id UUID PRIMARY KEY,
    encrypted_dsn TEXT NOT NULL,
    ssl_mode TEXT NOT NULL DEFAULT 'prefer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id UUID PRIMARY KEY,
    connection_id UUID NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
