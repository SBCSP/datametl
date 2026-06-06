// Hand-mirrors backend pydantic models. Switch to openapi-typescript codegen later if needed.

export type Engine = "postgres";

export type NormalizedType =
  | "string" | "int16" | "int32" | "int64" | "float32" | "float64" | "decimal"
  | "boolean" | "uuid" | "json" | "binary" | "date" | "time" | "timestamp"
  | "timestamptz" | "interval" | "array" | "enum" | "geometry" | "unknown";

export interface PostgresCredentials {
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
  sslmode?: string;
  sslrootcert?: string; // PEM contents (e.g. AWS RDS global-bundle.pem)
}

/** Partial credentials for PUT /connections/{id}. Unset fields keep previous values. */
export interface PostgresCredentialsUpdate {
  host?: string;
  port?: number;
  database?: string;
  user?: string;
  password?: string;
  sslmode?: string;
  sslrootcert?: string;
}

/** Non-secret parts of a Postgres connection — returned by GET /connections/{id}. */
export interface RedactedPostgresCredentials {
  host: string;
  port: number;
  database: string;
  user: string;
  sslmode?: string | null;
  has_sslrootcert: boolean;
}

export type Environment = "development" | "staging" | "production";

export interface Connection {
  id: string;
  name: string;
  engine: Engine;
  environment: Environment | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectionDetail extends Connection {
  redacted_credentials: RedactedPostgresCredentials;
}

export interface TestConnectionResult {
  ok: boolean;
  detail: string;
}

export interface ForeignKeyRef { schema: string; table: string; column: string; }
export interface NormalizedColumn {
  name: string;
  native_type: string;
  normalized_type: NormalizedType;
  nullable: boolean;
  default: string | null;
  is_primary_key: boolean;
  foreign_key: ForeignKeyRef | null;
}
export interface NormalizedIndex { name: string; columns: string[]; unique: boolean; }
export interface NormalizedTable {
  schema: string;
  name: string;
  columns: NormalizedColumn[];
  indexes: NormalizedIndex[];
  row_count_estimate: number | null;
  rls_enabled: boolean;
}
export interface NormalizedView { schema: string; name: string; definition: string; }
export interface RlsPolicy {
  schema: string; table: string; name: string; command: string;
  using_expr: string | null; with_check_expr: string | null; permissive: boolean;
}
export interface NormalizedSchema {
  engine: Engine;
  server_version: string;
  tables: NormalizedTable[];
  views: NormalizedView[];
  extensions: string[];
  rls_policies: RlsPolicy[];
}

export interface SchemaWarning {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  target: string | null;
}

export interface SnapshotSummary {
  id: string;
  connection_id: string;
  captured_at: string;
  table_count: number;
  warning_count: number;
}

export interface SchemaSummary {
  name: string;
  table_count: number;
  view_count: number;
}
export interface Snapshot {
  id: string;
  connection_id: string;
  captured_at: string;
  normalized_schema: NormalizedSchema;
  warnings: SchemaWarning[];
}

export interface SchemaDdl {
  sql: string;
  statement_count: number;
}
export interface SchemaApplyStatement {
  index: number;
  sql: string;
  ok: boolean;
  error: string | null;
  duration_ms: number;
}
export interface SchemaApplyResult {
  connection_name: string;
  statement_count: number;
  ok_count: number;
  fail_count: number;
  statements: SchemaApplyStatement[];
}

export type ColumnDriftKind =
  | "type_changed" | "nullable_changed" | "default_changed" | "pk_changed"
  | "fk_changed" | "missing_in_dest" | "missing_in_source";
export interface ColumnDrift {
  table: string;
  column: string;
  kind: ColumnDriftKind;
  source: string | null;
  dest: string | null;
}
export interface TableComparison { table: string; column_drift: ColumnDrift[]; }
export interface SchemaDiff {
  tables_only_in_source: string[];
  tables_only_in_dest: string[];
  common_tables: TableComparison[];
}
export interface Comparison {
  id: string;
  source_snapshot_id: string;
  dest_snapshot_id: string;
  source_schema?: string | null;
  dest_schema?: string | null;
  diff: SchemaDiff;
  created_at: string;
}

export interface ConnectionSummary {
  id: string;
  name: string;
  engine: Engine;
}

export interface ComparisonSummary {
  id: string;
  created_at: string;
  source_connection: string | null;
  source_engine: string | null;
  dest_connection: string | null;
  dest_engine: string | null;
  source_schema: string | null;
  dest_schema: string | null;
  ready: boolean;
  common_tables: number;
  only_in_source: number;
  only_in_dest: number;
}

export interface SnapshotInReport {
  id: string;
  captured_at: string;
  server_version: string | null;
  table_count: number;
  view_count: number;
  extension_count: number;
  rls_policy_count: number;
  warnings: SchemaWarning[];
}

export interface ComparisonReport {
  id: string;
  created_at: string;
  diff: SchemaDiff;
  source_schema?: string | null;
  dest_schema?: string | null;
  source_connection: ConnectionSummary;
  dest_connection: ConnectionSummary;
  source_snapshot: SnapshotInReport;
  dest_snapshot: SnapshotInReport;
}

export interface Mapping {
  id: string;
  comparison_id: string;
  source_table: string;
  source_column: string;
  dest_table: string;
  dest_column: string;
  source_type: string;
  default_dest_type: string;
  override_dest_type: string | null;
  is_lossy: boolean;
  notes: string | null;
}

export interface JobEnqueued { job_id: string; }
export interface ComparisonEnqueued { comparison_id: string; job_id: string; }

// --- Migrations ---

export type ConflictMode = "truncate" | "append" | "abort";
export type VerificationLevel = "count_only" | "count_and_sample" | "count_sample_and_full_hash";
export type MigrationRunStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";
export type TableRunStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";

export interface MigrationTableOption {
  source_table: string;
  dest_table: string;
  include: boolean;
  conflict_mode: ConflictMode;
  verification: VerificationLevel;
}

export interface MigrationOptionsPayload {
  tables: MigrationTableOption[];
  default_verification: VerificationLevel;
}

export interface MigrationFinding {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  target?: string | null;
}

export interface MigrationSkippedTable {
  source_table: string;
  reason: string;
  ddl_preview: string | null;
}

export interface MigrationPreflightResponse {
  findings: MigrationFinding[];
  can_run: boolean;
  would_truncate_counts: Record<string, number>;
  skipped_tables: MigrationSkippedTable[];
}

export interface MigrationRunEnqueued {
  run_id: string;
  job_id: string;
}

export interface CheckResult {
  name: string;
  passed: boolean;
  detail: string;
  metrics?: Record<string, unknown>;
  error?: string | null;
}

export interface MigrationRunTable {
  id: string;
  source_table: string;
  dest_table: string;
  conflict_mode: ConflictMode;
  status: TableRunStatus;
  rows_read?: number | null;
  rows_written?: number | null;
  duration_ms?: number | null;
  verification: CheckResult[];
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface MigrationRun {
  id: string;
  comparison_id: string;
  status: MigrationRunStatus;
  plan: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  created_at: string;
  tables: MigrationRunTable[];
}

export interface MigrationRunSummary {
  id: string;
  comparison_id: string;
  status: MigrationRunStatus;
  started_at?: string | null;
  finished_at?: string | null;
  table_count: number;
  created_at: string;
}

// --- Verification ---

export type VerificationRunStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";
export type VerificationTableStatus = "pending" | "running" | "passed" | "failed" | "skipped";

export interface VerificationTableOption {
  source_table: string;
  dest_table: string;
  include: boolean;
  level: VerificationLevel;
}

export interface VerificationOptionsPayload {
  tables: VerificationTableOption[];
  default_level: VerificationLevel;
}

export interface VerificationRunEnqueued {
  run_id: string;
  job_id: string;
}

export interface VerificationRunTable {
  id: string;
  source_table: string;
  dest_table: string;
  level: VerificationLevel;
  status: VerificationTableStatus;
  results: CheckResult[];
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface VerificationRun {
  id: string;
  comparison_id: string;
  status: VerificationRunStatus;
  plan: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  created_at: string;
  tables: VerificationRunTable[];
}

export interface VerificationRunSummary {
  id: string;
  comparison_id: string;
  status: VerificationRunStatus;
  started_at?: string | null;
  finished_at?: string | null;
  table_count: number;
  pass_count: number;
  fail_count: number;
  created_at: string;
}

// --- Activity / Runs ---

export type ActivityType =
  | "introspection"
  | "comparison"
  | "migration"
  | "verification"
  | "pipeline"
  | "scheduled"
  | "api_fetch";

export interface ActivityEntry {
  type: ActivityType;
  id: string;
  label: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  detail?: string | null;
  href: string;
}

// --- Auth ---

export interface AuthStatus {
  auth_enabled: boolean;
  authenticated: boolean;
  username: string | null;
}
export interface LoginResponse {
  token: string;
  username: string;
  expires_at: number;
}

// --- Dashboard metrics ---

export interface MetricsTotals {
  connections: number;
  connections_by_env: Record<string, number>;
  snapshots: number;
  comparisons: number;
  scripts: number;
  pipelines: number;
  schedules: number;
  migration_runs: number;
  verification_runs: number;
  pipeline_runs: number;
  scheduled_runs: number;
}
export interface MetricsSeriesPoint {
  date: string;
  introspection: number;
  comparison: number;
  migration: number;
  verification: number;
  pipeline: number;
  scheduled: number;
}
export interface Metrics {
  days: number;
  totals: MetricsTotals;
  series: MetricsSeriesPoint[];
  status_breakdown: Record<string, number>;
}

// --- Settings ---

export interface AppSettings {
  version: string;
  log_level: string;
  encryption_key_set: boolean;
  anthropic_api_key_set: boolean;
  cors_origins: string[];
  redis_url_redacted: string;
  database_url_redacted: string;
  queue_depth: number;
  worker_max_jobs: number;
  worker_job_timeout_seconds: number;
}

// --- Chat ---

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
export interface ChatModels {
  models: string[];
  default: string;
}
export interface ActiveMcp {
  connection_id: string;
  name: string;
  engine: string;
}
export interface ChatSessionSummary {
  id: string;
  title: string;
  model: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}
export interface ChatSessionDetail {
  id: string;
  title: string;
  model: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
}
// --- Tap (API data source) ---

export type TapMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type TapWriteMode = "append" | "replace";

export interface TapSummary {
  id: string;
  name: string;
  url: string;
  method: string;
  dest_count: number;
  last_run_status: string | null;
  last_run_at: string | null;
  is_scheduled: boolean;
  schedule_enabled: boolean;
  updated_at: string;
}
export interface Tap {
  id: string;
  name: string;
  url: string;
  method: TapMethod;
  records_path: string;
  headers: Record<string, string>; // values masked
  query_params: Record<string, string>; // values masked
  has_body: boolean;
  dest_connection_ids: string[];
  dest_table: string;
  write_mode: TapWriteMode;
  created_at: string;
  updated_at: string;
}
export interface TapTestResult {
  ok: boolean;
  http_status: number | null;
  record_count: number;
  sample: unknown[];
  error: string | null;
}
export interface TapRunSummaryItem {
  connection_name: string | null;
  ok: boolean;
  rows_written: number;
  error: string | null;
}
export interface TapRun {
  id: string;
  tap_id: string;
  status: "running" | "succeeded" | "failed" | string;
  http_status: number | null;
  record_count: number | null;
  sample: unknown[];
  summary: TapRunSummaryItem[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface JobProgress {
  connection?: string | null;
  phase?: string; // "tables" | "views" | "done"
  schema?: string;
  current?: number;
  total?: number;
  object?: string;
  updated_at?: number;
}
export interface JobStatus {
  id: string;
  status: "queued" | "in_progress" | "complete" | "not_found" | string;
  function: string | null;
  enqueue_time: string | null;
  result: unknown;
  error: string | null;
  progress?: JobProgress | null;
}

// --- SQL scripts ---

export interface SqlScript {
  id: string;
  name: string;
  content: string;
  description: string;
  run_count: number;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
  is_scheduled: boolean;
  schedule_enabled: boolean;
  last_scheduled_status: "running" | "succeeded" | "partial" | "failed" | null;
}
export interface StatementResult {
  index: number;
  sql: string;
  kind: "rows" | "command" | "error";
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  duration_ms: number;
  error: string | null;
}
export interface ConnectionRunResult {
  connection_id: string;
  connection_name: string;
  ok: boolean;
  error: string | null;
  statements: StatementResult[];
}
export interface ScriptRunResult {
  script_id: string;
  statement_count: number;
  connections: ConnectionRunResult[];
}

// --- Scheduled scripts (cron) ---

export type ScheduleTargetKind = "script" | "tap";
export interface Schedule {
  id: string;
  name: string;
  target_kind: ScheduleTargetKind;
  script_id: string | null;
  script_name: string | null;
  connection_ids: string[];
  allow_writes: boolean;
  tap_id: string | null;
  tap_name: string | null;
  tap_write_mode: TapWriteMode | null;
  cron: string;
  timezone: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface ScheduleConnectionSummary {
  connection_name: string | null;
  ok: boolean;
  error: string | null;
  row_total: number;
}
export interface ScheduledRun {
  id: string;
  schedule_id: string;
  status: "running" | "succeeded" | "partial" | "failed" | string;
  error: string | null;
  summary: ScheduleConnectionSummary[];
  started_at: string;
  finished_at: string | null;
}
export interface CronPreview {
  valid: boolean;
  error: string | null;
  next_runs: string[];
}

// --- ETL Pipelines ---

export type PipelineStepType = "sql" | "transfer";
export type TransferMode = "truncate" | "append";

export interface SqlStepConfig {
  connection_id?: string;
  script_id?: string;
  inline_sql?: string;
  allow_writes?: boolean;
}
export interface TransferStepConfig {
  source_connection_id?: string;
  source_script_id?: string;
  source_sql?: string;
  dest_connection_id?: string;
  dest_table?: string;
  dest_columns?: string[];
  mode?: TransferMode;
}
export type StepConfig = Record<string, unknown>;

export interface PipelineStepIO {
  name: string;
  step_type: PipelineStepType;
  config: StepConfig;
}
export interface PipelineStepRead extends PipelineStepIO {
  id: string;
  step_order: number;
}
export interface Pipeline {
  id: string;
  name: string;
  description: string;
  steps: PipelineStepRead[];
  created_at: string;
  updated_at: string;
}
export interface PipelineSummary {
  id: string;
  name: string;
  description: string;
  step_count: number;
  last_run_status: string | null;
  last_run_at: string | null;
  updated_at: string;
}
export interface PipelineRunStep {
  id: string;
  step_order: number;
  name: string;
  step_type: PipelineStepType;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped" | string;
  summary: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}
export interface PipelineRun {
  id: string;
  pipeline_id: string;
  status: "pending" | "running" | "succeeded" | "failed" | string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  steps: PipelineRunStep[];
}
export interface PipelineRunSummary {
  id: string;
  pipeline_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  step_count: number;
  created_at: string;
}
export interface PipelineRunEnqueued {
  run_id: string;
  job_id: string;
}
