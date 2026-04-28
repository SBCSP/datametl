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


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    engine: Literal["postgres"]
    credentials: PostgresCredentials


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    credentials: PostgresCredentialsUpdate | None = None


class ConnectionRead(BaseModel):
    id: uuid.UUID
    name: str
    engine: str
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

    type: Literal["introspection", "comparison", "migration", "verification"]
    id: str
    label: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None
    href: str


# --- Settings ---

class SettingsResponse(BaseModel):
    version: str
    log_level: str
    encryption_key_set: bool
    cors_origins: list[str]
    redis_url_redacted: str
    database_url_redacted: str
    queue_depth: int
    worker_max_jobs: int
    worker_job_timeout_seconds: int
