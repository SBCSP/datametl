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

export interface Connection {
  id: string;
  name: string;
  engine: Engine;
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

export type ActivityType = "introspection" | "comparison" | "migration" | "verification";

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

// --- Settings ---

export interface AppSettings {
  version: string;
  log_level: string;
  encryption_key_set: boolean;
  cors_origins: string[];
  redis_url_redacted: string;
  database_url_redacted: string;
  queue_depth: number;
  worker_max_jobs: number;
  worker_job_timeout_seconds: number;
}
export interface JobStatus {
  id: string;
  status: "queued" | "in_progress" | "complete" | "not_found" | string;
  function: string | null;
  enqueue_time: string | null;
  result: unknown;
  error: string | null;
}
