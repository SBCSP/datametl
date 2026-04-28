import type {
  Comparison,
  ComparisonEnqueued,
  ComparisonReport,
  Connection,
  ConnectionDetail,
  JobEnqueued,
  JobStatus,
  Mapping,
  ActivityEntry,
  AppSettings,
  MigrationOptionsPayload,
  MigrationPreflightResponse,
  MigrationRun,
  MigrationRunEnqueued,
  MigrationRunSummary,
  VerificationOptionsPayload,
  VerificationRun,
  VerificationRunEnqueued,
  VerificationRunSummary,
  PostgresCredentials,
  PostgresCredentialsUpdate,
  SchemaSummary,
  Snapshot,
  SnapshotSummary,
  TestConnectionResult,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`API ${status}: ${body}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // Connections
  listConnections: () => request<Connection[]>("/api/connections"),
  getConnection: (id: string) => request<ConnectionDetail>(`/api/connections/${id}`),
  createConnection: (body: { name: string; engine: "postgres"; credentials: PostgresCredentials }) =>
    request<Connection>("/api/connections", { method: "POST", body: JSON.stringify(body) }),
  updateConnection: (
    id: string,
    body: { name?: string; credentials?: PostgresCredentialsUpdate },
  ) =>
    request<ConnectionDetail>(`/api/connections/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteConnection: (id: string) =>
    request<void>(`/api/connections/${id}`, { method: "DELETE" }),
  testConnection: (id: string) =>
    request<TestConnectionResult>(`/api/connections/${id}/test`, { method: "POST" }),
  introspect: (id: string) =>
    request<JobEnqueued>(`/api/connections/${id}/introspect`, { method: "POST" }),

  // Snapshots
  listSnapshots: (connectionId: string) =>
    request<SnapshotSummary[]>(`/api/connections/${connectionId}/snapshots`),
  getSnapshot: (id: string) => request<Snapshot>(`/api/snapshots/${id}`),
  getSnapshotSchemas: (id: string) => request<SchemaSummary[]>(`/api/snapshots/${id}/schemas`),

  // Comparisons
  listComparisons: () => request<Comparison[]>("/api/comparisons"),
  createComparison: (body: {
    source_snapshot_id: string;
    dest_snapshot_id: string;
    source_schema?: string | null;
    dest_schema?: string | null;
  }) => request<ComparisonEnqueued>("/api/comparisons", { method: "POST", body: JSON.stringify(body) }),
  getComparison: (id: string) => request<Comparison>(`/api/comparisons/${id}`),
  getComparisonReport: (id: string) => request<ComparisonReport>(`/api/comparisons/${id}/report`),

  // Mappings
  listMappings: (comparisonId: string) =>
    request<Mapping[]>(`/api/comparisons/${comparisonId}/mappings`),
  updateMapping: (
    comparisonId: string,
    mappingId: string,
    body: Partial<Pick<Mapping, "dest_table" | "dest_column" | "override_dest_type" | "notes">>,
  ) =>
    request<Mapping>(`/api/comparisons/${comparisonId}/mappings/${mappingId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // Jobs
  jobStatus: (id: string) => request<JobStatus>(`/api/jobs/${id}`),

  // Migrations
  preflightMigration: (body: { comparison_id: string; options: MigrationOptionsPayload }) =>
    request<MigrationPreflightResponse>("/api/migrations/preflight", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createMigrationRun: (body: { comparison_id: string; options: MigrationOptionsPayload }) =>
    request<MigrationRunEnqueued>("/api/migrations/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listMigrationRuns: () => request<MigrationRunSummary[]>("/api/migrations/runs"),
  getMigrationRun: (id: string) => request<MigrationRun>(`/api/migrations/runs/${id}`),
  cancelMigrationRun: (id: string) =>
    request<MigrationRun>(`/api/migrations/runs/${id}/cancel`, { method: "POST" }),

  // Verifications
  createVerificationRun: (body: { comparison_id: string; options: VerificationOptionsPayload }) =>
    request<VerificationRunEnqueued>("/api/verifications/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listVerificationRuns: () => request<VerificationRunSummary[]>("/api/verifications/runs"),
  getVerificationRun: (id: string) => request<VerificationRun>(`/api/verifications/runs/${id}`),
  cancelVerificationRun: (id: string) =>
    request<VerificationRun>(`/api/verifications/runs/${id}/cancel`, { method: "POST" }),

  // Activity (unified runs feed)
  listActivity: () => request<ActivityEntry[]>("/api/activity"),

  // Settings
  getSettings: () => request<AppSettings>("/api/settings"),
};

export { ApiError };
