"use client";

import { create } from "zustand";
import { ApiError, api, storeToken } from "@/lib/api";
import type { EngineStatus, HealthResponse, TableSchema } from "@/types/api";

/**
 * Demo connection defaults. These match `docker-compose.yml` so the app works
 * with one click; override them with NEXT_PUBLIC_DB_* when pointing elsewhere.
 */
const DEMO_CONNECTION = {
  host: process.env.NEXT_PUBLIC_DB_HOST ?? "localhost",
  port: Number(process.env.NEXT_PUBLIC_DB_PORT ?? 5432),
  dbname: process.env.NEXT_PUBLIC_DB_NAME ?? "target_db",
  user: process.env.NEXT_PUBLIC_DB_USER ?? "query_optimizer",
  password: process.env.NEXT_PUBLIC_DB_PASSWORD ?? "query_optimizer_dev_password",
  ssl_mode: "prefer" as const,
};

type SessionState = {
  health: HealthResponse | null;
  engine: EngineStatus | null;
  connectionId: string | null;
  dbVersion: string | null;
  tables: TableSchema[];
  busy: boolean;
  error: string | null;
  setToken: (token: string) => void;
  refresh: () => Promise<void>;
  connect: () => Promise<string>;
  ensureConnection: () => Promise<string>;
};

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.suggestion ? `${error.message} ${error.suggestion}` : error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

export const useSessionStore = create<SessionState>((set, get) => ({
  health: null,
  engine: null,
  connectionId: null,
  dbVersion: null,
  tables: [],
  busy: false,
  error: null,

  setToken: (token) => {
    storeToken(token);
    void get().refresh();
  },

  refresh: async () => {
    try {
      const [health, engine] = await Promise.all([
        api.health(),
        api.engineStatus(),
      ]);
      set({ health, engine, error: null });
    } catch (error) {
      set({ error: describe(error) });
    }
  },

  connect: async () => {
    set({ busy: true, error: null });
    try {
      const connection = await api.connect(DEMO_CONNECTION);
      set({
        connectionId: connection.connection_id,
        dbVersion: connection.db_version,
        busy: false,
      });
      const schema = await api.schema(connection.connection_id);
      set({ tables: schema.tables });
      return connection.connection_id;
    } catch (error) {
      set({ busy: false, error: describe(error) });
      throw error;
    }
  },

  ensureConnection: async () => {
    const existing = get().connectionId;
    if (existing) return existing;
    return get().connect();
  },
}));
