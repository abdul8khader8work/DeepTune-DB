/**
 * Typed client for the DeepTune API.
 *
 * The bearer token is read from `NEXT_PUBLIC_API_TOKEN` at build time, or from
 * `localStorage["deeptune.token"]` at runtime so the operator can paste a token
 * minted by `python -m src.cli.token` without rebuilding the bundle.
 */

import type {
  AnalysisResult,
  AnalyzeAccepted,
  AnalyzeRequest,
  ApiErrorBody,
  ApplyIndexResponse,
  ConnectionRequest,
  ConnectionResponse,
  EngineStatus,
  HealthResponse,
  RevertResponse,
  RunStatusResponse,
  SchemaResponse,
} from "@/types/api";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const TOKEN_STORAGE_KEY = "deeptune.token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly suggestion?: string;

  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    const detail = body?.detail;
    super(detail?.message ?? fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = detail?.error_code ?? "NETWORK_ERROR";
    this.suggestion = detail?.suggestion;
  }
}

export function readToken(): string | null {
  if (typeof window === "undefined") {
    return process.env.NEXT_PUBLIC_API_TOKEN ?? null;
  }
  const stored = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  return stored && stored.trim().length > 0
    ? stored.trim()
    : (process.env.NEXT_PUBLIC_API_TOKEN ?? null);
}

export function storeToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token.trim());
}

function authHeaders(): Record<string, string> {
  const token = readToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      null,
      `Cannot reach the DeepTune API at ${API_BASE_URL}. Is it running?`,
    );
  }

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    throw new ApiError(response.status, body, `Request failed (${response.status})`);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function post<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(payload) });
}

const V1 = "/api/v1";

export const api = {
  health: (): Promise<HealthResponse> => request<HealthResponse>(`${V1}/health`),

  engineStatus: (): Promise<EngineStatus> =>
    request<EngineStatus>(`${V1}/engine/status`),

  connect: (payload: ConnectionRequest): Promise<ConnectionResponse> =>
    post<ConnectionResponse>(`${V1}/databases/connect`, payload),

  schema: (connectionId: string): Promise<SchemaResponse> =>
    request<SchemaResponse>(
      `${V1}/databases/${encodeURIComponent(connectionId)}/schema`,
    ),

  analyze: (payload: AnalyzeRequest): Promise<AnalyzeAccepted> =>
    post<AnalyzeAccepted>(`${V1}/queries/analyze`, payload),

  runStatus: (runId: string): Promise<RunStatusResponse> =>
    request<RunStatusResponse>(
      `${V1}/queries/${encodeURIComponent(runId)}/status`,
    ),

  runResults: (runId: string): Promise<AnalysisResult> =>
    request<AnalysisResult>(
      `${V1}/queries/${encodeURIComponent(runId)}/results`,
    ),

  applyRecommendation: (recommendationId: string): Promise<ApplyIndexResponse> =>
    post<ApplyIndexResponse>(
      `${V1}/recommendations/${encodeURIComponent(recommendationId)}/apply`,
      {},
    ),

  revertRecommendation: (recommendationId: string): Promise<RevertResponse> =>
    post<RevertResponse>(
      `${V1}/recommendations/${encodeURIComponent(recommendationId)}/revert`,
      {},
    ),
};

/** Build the copilot socket URL, appending the bearer token as a query param. */
export function copilotSocketUrl(runId: string): string {
  const base = (
    process.env.NEXT_PUBLIC_WS_URL ?? API_BASE_URL.replace(/^http/, "ws")
  ).replace(/\/$/, "");
  const token = readToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${base}${V1}/ws/copilot/${encodeURIComponent(runId)}${query}`;
}
