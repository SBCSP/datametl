"""Pydantic request/response schemas shared by API routers.

(Filename intentionally `schemas_io` to avoid clashing with the schema-introspection routes
in `api/snapshots.py` and the introspection module.)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Connection ---

class PostgresCredentials(BaseModel):
    host: str
    port: int = 5432
    database: str
    user: str
    password: str
    sslmode: str | None = None  # disable | allow | prefer | require | verify-ca | verify-full
    sslrootcert: str | None = None  # PEM contents (e.g. AWS RDS global-bundle.pem)


class PostgresCredentialsUpdate(BaseModel):
    """Partial credentials for updates. Only fields you set get changed; the rest keep
    their previous values. Note: password / sslrootcert are not returned by the GET
    endpoint, so the frontend never knows their current values — leave them unset to
    preserve the existing password / cert."""

    host: str | None = None
    port: int | None = None
    database: str | None = None
    user: str | None = None
    password: str | None = None
    sslmode: str | None = None
    sslrootcert: str | None = None


class RedactedPostgresCredentials(BaseModel):
    """Non-secret parts of a Postgres connection — safe to return from the API."""

    host: str
    port: int
    database: str
    user: str
    sslmode: str | None = None
    has_sslrootcert: bool = False


Environment = Literal["development", "staging", "production"]


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    engine: Literal["postgres", "mysql", "mssql"]
    environment: Environment | None = None
    # Postgres / MySQL / SQL Server credentials are structurally identical
    # (host/port/database/user/password + optional sslmode/sslrootcert);
    # the connector interprets SSL/TDS options per engine.
    credentials: PostgresCredentials


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    environment: Environment | None = None
    credentials: PostgresCredentialsUpdate | None = None


class ConnectionRead(BaseModel):
    id: uuid.UUID
    name: str
    engine: str
    environment: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectionDetail(ConnectionRead):
    redacted_credentials: RedactedPostgresCredentials


class TestConnectionResult(BaseModel):
    ok: bool
    detail: str


# --- Snapshot ---

class SnapshotSummary(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    captured_at: datetime
    table_count: int
    warning_count: int


class SnapshotRead(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    captured_at: datetime
    normalized_schema: dict[str, Any]
    warnings: list[dict[str, Any]]


class SchemaSummary(BaseModel):
    """Per-schema counts within a snapshot — fuels the schema picker on New comparison."""

    name: str
    table_count: int
    view_count: int


class SchemaDdlResponse(BaseModel):
    """Lightweight CREATE-DDL generated from a snapshot, for preview before applying."""

    sql: str
    statement_count: int


class SchemaApplyRequest(BaseModel):
    connection_id: uuid.UUID
    schema_override: str | None = None  # retarget all objects into one schema; null keeps source schemas


# --- Comparison ---

class ComparisonCreate(BaseModel):
    source_snapshot_id: uuid.UUID
    dest_snapshot_id: uuid.UUID
    # Optional schema scope. Both must be set to take effect. If unset, the comparison
    # covers every non-system schema in both snapshots.
    source_schema: str | None = None
    dest_schema: str | None = None


class ComparisonRead(BaseModel):
    id: uuid.UUID
    source_snapshot_id: uuid.UUID
    dest_snapshot_id: uuid.UUID
    source_schema: str | None = None
    dest_schema: str | None = None
    diff: dict[str, Any]
    created_at: datetime


class ComparisonSummary(BaseModel):
    """List-row shape for /comparisons — resolves the source/dest databases so the UI shows
    real names instead of opaque snapshot/comparison ids, plus a small drift summary."""

    id: uuid.UUID
    created_at: datetime
    source_connection: str | None = None
    source_engine: str | None = None
    dest_connection: str | None = None
    dest_engine: str | None = None
    source_schema: str | None = None
    dest_schema: str | None = None
    ready: bool = False
    common_tables: int = 0
    only_in_source: int = 0
    only_in_dest: int = 0


class ConnectionSummary(BaseModel):
    """Just the labelling fields — what the user named the connection. No credentials."""

    id: uuid.UUID
    name: str
    engine: str


class SnapshotInReport(BaseModel):
    id: uuid.UUID
    captured_at: datetime
    server_version: str | None = None
    table_count: int
    view_count: int
    extension_count: int
    rls_policy_count: int
    warnings: list[dict[str, Any]]


class ComparisonReport(BaseModel):
    """Everything the report view / print-friendly page needs in one round-trip."""

    id: uuid.UUID
    created_at: datetime
    diff: dict[str, Any]
    source_schema: str | None = None
    dest_schema: str | None = None
    source_connection: ConnectionSummary
    dest_connection: ConnectionSummary
    source_snapshot: SnapshotInReport
    dest_snapshot: SnapshotInReport


# --- Mapping ---

class MappingRead(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    source_table: str
    source_column: str
    dest_table: str
    dest_column: str
    source_type: str
    default_dest_type: str
    override_dest_type: str | None
    is_lossy: bool
    notes: str | None


class MappingUpdate(BaseModel):
    dest_table: str | None = None
    dest_column: str | None = None
    override_dest_type: str | None = None
    notes: str | None = None


# --- Jobs ---

class JobEnqueued(BaseModel):
    job_id: str


class ComparisonEnqueued(BaseModel):
    """POST /comparisons returns both the freshly-created comparison row id and the job id
    that's computing its diff. The frontend uses comparison_id to deep-link into the detail
    view (which polls until the diff is populated)."""

    comparison_id: uuid.UUID
    job_id: str


class JobStatusResponse(BaseModel):
    id: str
    status: str
    function: str | None = None
    enqueue_time: str | None = None
    result: Any = None
    error: str | None = None
    progress: dict[str, Any] | None = None  # live progress snapshot (e.g. introspection counts)


# --- Migration ---

class MigrationTableOption(BaseModel):
    source_table: str
    dest_table: str
    include: bool = True
    conflict_mode: Literal["truncate", "append", "abort"] = "truncate"
    verification: Literal["count_only", "count_and_sample", "count_sample_and_full_hash"] = "count_and_sample"


class MigrationOptionsPayload(BaseModel):
    tables: list[MigrationTableOption]
    default_verification: Literal["count_only", "count_and_sample", "count_sample_and_full_hash"] = (
        "count_and_sample"
    )


class MigrationPreflightRequest(BaseModel):
    comparison_id: uuid.UUID
    options: MigrationOptionsPayload


class MigrationPreflightResponse(BaseModel):
    findings: list[dict[str, Any]]
    can_run: bool
    would_truncate_counts: dict[str, int]
    skipped_tables: list[dict[str, Any]]  # {source_table, reason, ddl_preview}


class MigrationRunCreate(BaseModel):
    comparison_id: uuid.UUID
    options: MigrationOptionsPayload


class MigrationRunEnqueued(BaseModel):
    run_id: uuid.UUID
    job_id: str


class MigrationRunTableRead(BaseModel):
    id: uuid.UUID
    source_table: str
    dest_table: str
    conflict_mode: str
    status: str
    rows_read: int | None = None
    rows_written: int | None = None
    duration_ms: int | None = None
    verification: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class MigrationRunRead(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    status: str
    plan: dict[str, Any]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    tables: list[MigrationRunTableRead] = Field(default_factory=list)


class MigrationRunSummary(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    status: str
    source_connection: str | None = None
    dest_connection: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    table_count: int
    created_at: datetime


# --- Verification ---

class VerificationTableOption(BaseModel):
    source_table: str
    dest_table: str
    include: bool = True
    level: Literal["count_only", "count_and_sample", "count_sample_and_full_hash"] = "count_and_sample"


class VerificationOptionsPayload(BaseModel):
    tables: list[VerificationTableOption]
    default_level: Literal["count_only", "count_and_sample", "count_sample_and_full_hash"] = (
        "count_and_sample"
    )


class VerificationRunCreate(BaseModel):
    comparison_id: uuid.UUID
    options: VerificationOptionsPayload


class VerificationRunEnqueued(BaseModel):
    run_id: uuid.UUID
    job_id: str


class VerificationRunTableRead(BaseModel):
    id: uuid.UUID
    source_table: str
    dest_table: str
    level: str
    status: str
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class VerificationRunRead(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    status: str
    plan: dict[str, Any]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    tables: list[VerificationRunTableRead] = Field(default_factory=list)


class VerificationRunSummary(BaseModel):
    id: uuid.UUID
    comparison_id: uuid.UUID
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    table_count: int
    pass_count: int
    fail_count: int
    created_at: datetime


# --- Activity / runs aggregator ---

class ActivityEntry(BaseModel):
    """Unified shape for the /api/runs aggregator. Each row represents one background job
    or run across the system, no matter where it lives in storage."""

    type: Literal[
        "introspection",
        "comparison",
        "migration",
        "verification",
        "pipeline",
        "scheduled",
        "api_fetch",
        "mel_tool",
    ]
    id: str
    label: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None
    href: str


# --- Auth (simple single-user login) ---

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_at: int  # epoch seconds


class AuthStatus(BaseModel):
    auth_enabled: bool
    authenticated: bool
    username: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1)


# --- Tap (API data source) ---

TapMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
TapWriteMode = Literal["append", "replace"]


class TapCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1)
    method: TapMethod = "GET"
    records_path: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    dest_connection_ids: list[uuid.UUID] = Field(default_factory=list)
    dest_table: str = ""
    write_mode: TapWriteMode = "append"


class TapUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = None
    method: TapMethod | None = None
    records_path: str | None = None
    headers: dict[str, str] | None = None
    query_params: dict[str, str] | None = None
    body: str | None = None
    dest_connection_ids: list[uuid.UUID] | None = None
    dest_table: str | None = None
    write_mode: TapWriteMode | None = None


class TapRead(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    method: str
    records_path: str
    headers: dict[str, str]  # values masked
    query_params: dict[str, str]  # values masked
    has_body: bool
    dest_connection_ids: list[uuid.UUID]
    dest_table: str
    write_mode: str
    created_at: datetime
    updated_at: datetime


class TapSummary(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    method: str
    dest_count: int
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    is_scheduled: bool = False
    schedule_enabled: bool = False
    updated_at: datetime


class TapTestRequest(BaseModel):
    url: str = Field(min_length=1)
    method: TapMethod = "GET"
    records_path: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None


class TapTestResult(BaseModel):
    ok: bool
    http_status: int | None = None
    record_count: int = 0
    sample: list[Any] = Field(default_factory=list)
    error: str | None = None


class TapRunRead(BaseModel):
    id: uuid.UUID
    tap_id: uuid.UUID
    status: str
    http_status: int | None = None
    record_count: int | None = None
    sample: list[Any] = Field(default_factory=list)
    summary: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


# --- Dashboard metrics ---

class MetricsTotals(BaseModel):
    connections: int
    connections_by_env: dict[str, int]
    snapshots: int
    comparisons: int
    scripts: int
    pipelines: int
    schedules: int
    taps: int = 0
    migration_runs: int
    verification_runs: int
    pipeline_runs: int
    scheduled_runs: int
    tap_runs: int = 0


class MetricsSeriesPoint(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    introspection: int = 0
    comparison: int = 0
    migration: int = 0
    verification: int = 0
    pipeline: int = 0
    scheduled: int = 0
    api_fetch: int = 0


class MetricsResponse(BaseModel):
    days: int
    totals: MetricsTotals
    series: list[MetricsSeriesPoint]
    status_breakdown: dict[str, int]  # run statuses across all run types within the window


# --- SQL scripts ---

class SqlScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content: str = ""
    description: str = ""


class SqlScriptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    description: str | None = None


class SqlScriptRead(BaseModel):
    id: uuid.UUID
    name: str
    content: str
    description: str = ""
    run_count: int = 0
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Schedule indicators (populated by the list endpoint; default off elsewhere).
    is_scheduled: bool = False  # at least one schedule references this script
    schedule_enabled: bool = False  # at least one *enabled* schedule references it
    last_scheduled_status: str | None = None  # status of the most recent scheduled run


class SqlScriptRunRequest(BaseModel):
    connection_ids: list[uuid.UUID] = Field(min_length=1)
    allow_writes: bool = False  # default read-only; opt in to commit writes/DDL


class StatementResultRead(BaseModel):
    """Result of one statement on one connection. Mirrors scripts.runner.StatementResult.
    Delivered to the frontend inside the job result (GET /api/jobs/{id}), not as a direct
    response_model — defined here so the shape is documented and kept in sync."""

    index: int
    sql: str
    kind: Literal["rows", "command", "error"]
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    error: str | None = None


class ConnectionRunResultRead(BaseModel):
    connection_id: uuid.UUID
    connection_name: str
    ok: bool
    error: str | None = None
    statements: list[StatementResultRead]


class ScriptRunResult(BaseModel):
    script_id: uuid.UUID
    statement_count: int
    connections: list[ConnectionRunResultRead]


# --- License ---

class LicenseStatus(BaseModel):
    """Non-secret license / entitlement snapshot for Settings."""

    tier: Literal["community", "pro", "team"]
    active: bool
    source: Literal["none", "key", "dev_bypass"]
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    email: str | None = None
    seat_id: str | None = None
    instance_id: str | None = None
    message: str | None = None
    # Community Mel limit description (always present for UI copy)
    community_mel_limit: str
    can_use_mysql_mssql: bool
    can_choose_mel_approval: bool
    allows_external_mcp: bool = False
    license_key_set: bool = False


class LicenseActivateRequest(BaseModel):
    """Paste a signed license key (dmtl1.…). Write-only — never returned."""

    license_key: str


class LicenseActivateResponse(BaseModel):
    license: LicenseStatus


# --- Settings ---

class SettingsResponse(BaseModel):
    version: str
    log_level: str
    encryption_key_set: bool
    anthropic_api_key_set: bool = False
    cors_origins: list[str]
    redis_url_redacted: str
    database_url_redacted: str
    queue_depth: int
    worker_max_jobs: int
    worker_job_timeout_seconds: int
    auth_enabled: bool = False
    auth_username: str | None = None
    auth_token_ttl_hours: int = 0
    # Mel: run_sql_only (default) | always | auto
    mel_tool_approval: str = "run_sql_only"
    # Licensing (Phase 1 offline Ed25519 keys)
    license: LicenseStatus | None = None


class AnthropicKeyUpdate(BaseModel):
    """Write-only — empty/blank clears the stored key. The key is never returned."""

    api_key: str | None = None


class AnthropicKeyStatus(BaseModel):
    anthropic_api_key_set: bool


# --- Chat ---

class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessageIn] = Field(min_length=1)
    session_id: uuid.UUID | None = None  # links Mel tool audit rows when known


class ChatModelsResponse(BaseModel):
    models: list[str]
    default: str


class DescribeSqlRequest(BaseModel):
    """Ask Mel to write a description of a SQL script (for the Scripts editor)."""

    sql: str
    model: str | None = None  # defaults server-side


class MelToolCardIn(BaseModel):
    """Mel Approve/Deny card persisted with a chat session transcript."""

    proposal_id: str
    name: str
    args_summary: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "auto", "approved", "denied", "success", "error", "running"]
    outcome_summary: str | None = None


class ChatSessionCreate(BaseModel):
    title: str | None = None  # derived from the first user message when blank
    model: str
    messages: list[ChatMessageIn] = Field(default_factory=list)
    tool_cards: list[MelToolCardIn] = Field(default_factory=list)


class ChatSessionUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    messages: list[ChatMessageIn]
    # None = leave existing sidecar unchanged (older clients); [] clears.
    tool_cards: list[MelToolCardIn] | None = None


class ChatSessionSummary(BaseModel):
    id: uuid.UUID
    title: str
    model: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionRead(BaseModel):
    id: uuid.UUID
    title: str
    model: str
    messages: list[ChatMessageIn]
    tool_cards: list[MelToolCardIn] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# --- MCP (live read-only connection) ---

class McpActivateRequest(BaseModel):
    connection_id: uuid.UUID


class McpActiveResponse(BaseModel):
    connection_id: uuid.UUID
    name: str
    engine: str


# --- Mel tool approval / audit ---

class MelToolApprovalUpdate(BaseModel):
    """Operator preference for Mel DB tool confirmation in chat."""

    mel_tool_approval: Literal["run_sql_only", "always", "auto"]


class MelToolApprovalStatus(BaseModel):
    mel_tool_approval: Literal["run_sql_only", "always", "auto"]


class MelToolDecisionRequest(BaseModel):
    proposal_id: uuid.UUID
    decision: Literal["approve", "deny"]


class MelToolDecisionResponse(BaseModel):
    ok: bool
    proposal_id: uuid.UUID
    decision: Literal["approve", "deny"]


class MelToolInvocationRead(BaseModel):
    id: uuid.UUID
    created_at: datetime
    finished_at: datetime | None = None
    session_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    connection_name: str | None = None
    tool_name: str
    args_redacted: dict[str, Any]
    args_summary: str
    decision: str
    outcome: str
    outcome_detail: str | None = None
    model: str | None = None
    proposal_id: uuid.UUID

    model_config = {"from_attributes": True}


# --- Scheduled scripts (cron) ---

ScheduleTargetKind = Literal["script", "tap"]


class ScheduleCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)  # defaults to the script/tap name
    target_kind: ScheduleTargetKind = "script"
    # script schedules:
    script_id: uuid.UUID | None = None
    connection_ids: list[uuid.UUID] = Field(default_factory=list)
    allow_writes: bool = False
    # tap schedules:
    tap_id: uuid.UUID | None = None
    tap_write_mode: TapWriteMode | None = None
    cron: str = Field(min_length=1, max_length=255)
    timezone: str = "UTC"
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    target_kind: ScheduleTargetKind | None = None
    script_id: uuid.UUID | None = None
    connection_ids: list[uuid.UUID] | None = None
    allow_writes: bool | None = None
    tap_id: uuid.UUID | None = None
    tap_write_mode: TapWriteMode | None = None
    cron: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = None
    enabled: bool | None = None


class ScheduleRead(BaseModel):
    id: uuid.UUID
    name: str
    target_kind: str
    script_id: uuid.UUID | None = None
    script_name: str | None = None
    connection_ids: list[uuid.UUID]
    allow_writes: bool
    tap_id: uuid.UUID | None = None
    tap_name: str | None = None
    tap_write_mode: str | None = None
    cron: str
    timezone: str
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ScheduledRunRead(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    status: str
    error: str | None = None
    summary: list[dict[str, Any]] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None


class CronPreviewRequest(BaseModel):
    cron: str
    timezone: str = "UTC"


class CronPreviewResponse(BaseModel):
    valid: bool
    error: str | None = None
    next_runs: list[datetime] = Field(default_factory=list)


# --- ETL Pipelines ---

class PipelineStepIO(BaseModel):
    """A step as authored in the builder. `config` is type-specific (see PipelineStep model)."""

    name: str = Field(default="", max_length=255)
    step_type: Literal["sql", "transfer"]
    config: dict[str, Any] = Field(default_factory=dict)


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    steps: list[PipelineStepIO] = Field(default_factory=list)


class PipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    steps: list[PipelineStepIO] | None = None  # when present, replaces all steps


class PipelineStepRead(BaseModel):
    id: uuid.UUID
    step_order: int
    name: str
    step_type: str
    config: dict[str, Any]


class PipelineRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    steps: list[PipelineStepRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PipelineSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    step_count: int
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    updated_at: datetime


class PipelineRunEnqueued(BaseModel):
    run_id: uuid.UUID
    job_id: str


class PipelineRunStepRead(BaseModel):
    id: uuid.UUID
    step_order: int
    name: str
    step_type: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PipelineRunRead(BaseModel):
    id: uuid.UUID
    pipeline_id: uuid.UUID
    status: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    steps: list[PipelineRunStepRead] = Field(default_factory=list)


class PipelineRunSummary(BaseModel):
    id: uuid.UUID
    pipeline_id: uuid.UUID
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    step_count: int
    created_at: datetime
