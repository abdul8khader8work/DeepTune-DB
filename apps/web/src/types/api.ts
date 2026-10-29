/**
 * Wire contracts for the DeepTune API.
 *
 * These mirror `apps/api/src/schemas/*` exactly. Keep them in sync — the API is
 * strict (`extra="forbid"`), so a drifted field is a 422, not a silent default.
 */

export type OptimizationGoal =
  | "read_performance"
  | "balanced"
  | "minimal_storage";

export type RunState =
  | "queued"
  | "parsing"
  | "gnn_inference"
  | "hypopg_validation"
  | "completed"
  | "failed";

export type EngineBackend = "gnn" | "heuristic";

export interface ApiErrorDetail {
  error_code: string;
  message: string;
  suggestion?: string;
}

export interface ApiErrorBody {
  detail: ApiErrorDetail;
}

export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
  auth_enabled: boolean;
  shadow_db_configured: boolean;
  metadata_store: string;
}

export type EngineRuntime = "onnx" | "torch" | "heuristic";

export interface EngineStatus {
  enabled: boolean;
  available: boolean;
  backend: EngineBackend;
  label: string;
  device: string;
  runtime: EngineRuntime;
  checkpoint: string | null;
  model_version: string | null;
  parameters: number | null;
  hidden_dim: number | null;
  layers: number | null;
  heads: number | null;
  error: string | null;
}

export interface ConnectionRequest {
  host: string;
  port: number;
  dbname: string;
  user: string;
  password: string;
  ssl_mode: "disable" | "allow" | "prefer" | "require";
}

export interface ConnectionResponse {
  connection_id: string;
  status: string;
  db_version: string;
}

export interface ColumnSchema {
  name: string;
  data_type: string;
  is_nullable: boolean;
  is_primary_key: boolean;
  existing_indexes: string[];
}

export interface TableSchema {
  name: string;
  schema_name: string;
  row_estimate: number;
  total_bytes: number;
  columns: ColumnSchema[];
}

export interface SchemaResponse {
  connection_id: string;
  tables: TableSchema[];
}

export interface AnalyzeRequest {
  connection_id: string;
  sql_query: string;
  optimization_goal: OptimizationGoal;
}

export interface AnalyzeAccepted {
  run_id: string;
  status: string;
  message: string;
}

export interface RunStatusResponse {
  run_id: string;
  status: RunState;
  progress_percentage: number;
  current_step_log: string;
}

export interface DAGNode {
  id: string;
  operation_type: string;
  relation_name: string | null;
  estimated_cost: number;
  estimated_rows: number;
  actual_time_ms: number | null;
  gnn_attention_score: number;
}

export interface DAGEdge {
  id: string;
  source: string;
  target: string;
  rows_transferred: number;
}

export interface AttentionHotspot {
  node_index: number;
  operator: string;
  relation: string | null;
  weight: number;
}

export interface RejectedCandidate {
  description: string;
  reason: string;
}

export interface IndexRecommendation {
  id: string;
  sql_statement: string;
  target_table: string;
  target_columns: string[];
  predicted_speedup_factor: number;
  validated_speedup_factor: number | null;
  storage_overhead_bytes: number;
  write_impact_percentage: number;
  confidence_score: number;
  explanation: string;
}

export interface AnalysisResult {
  run_id: string;
  status: "completed" | "failed";
  engine: EngineBackend;
  original_metrics: Record<string, number>;
  optimized_metrics: Record<string, number>;
  original_dag: DAGNode[];
  optimized_dag: DAGNode[];
  edges: DAGEdge[];
  original_edges: DAGEdge[];
  recommendations: IndexRecommendation[];
  attention: AttentionHotspot[];
  symbolic_trace: string[];
  rejected_candidates: RejectedCandidate[];
  speedup_factor: number;
  symbolic_candidate_count: number;
}

export interface ApplyIndexResponse {
  hypopg_index_id: number;
  status: string;
  validated_execution_time_ms: number;
  message: string;
}

export interface RevertResponse {
  status: string;
}

/** Frames exchanged on `/api/v1/ws/copilot/{run_id}`. */
export interface CopilotFrame {
  type: "ready" | "thinking" | "token" | "tool" | "done" | "error";
  text?: string;
  run_id?: string;
  engine?: EngineBackend;
  tool?: string;
  args?: string;
  result?: string;
  status?: "running" | "done" | "error";
}
