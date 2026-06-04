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
  ActiveMcp,
  ChatMessage,
  ChatModels,
  ChatSessionDetail,
  ChatSessionSummary,
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
  SqlScript,
  Schedule,
  ScheduledRun,
  CronPreview,
  Pipeline,
  PipelineSummary,
  PipelineStepIO,
  PipelineRun,
  PipelineRunSummary,
  PipelineRunEnqueued,
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
  cleanupStaleMigrationTables: (id: string) =>
    request<MigrationRun>(`/api/migrations/runs/${id}/cleanup-stale`, { method: "POST" }),

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

  // SQL scripts
  listScripts: () => request<SqlScript[]>("/api/scripts"),
  getScript: (id: string) => request<SqlScript>(`/api/scripts/${id}`),
  createScript: (body: { name: string; content: string; description?: string }) =>
    request<SqlScript>("/api/scripts", { method: "POST", body: JSON.stringify(body) }),
  updateScript: (id: string, body: { name?: string; content?: string; description?: string }) =>
    request<SqlScript>(`/api/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteScript: (id: string) => request<void>(`/api/scripts/${id}`, { method: "DELETE" }),
  runScript: (id: string, connectionIds: string[], allowWrites = false) =>
    request<JobEnqueued>(`/api/scripts/${id}/run`, {
      method: "POST",
      body: JSON.stringify({ connection_ids: connectionIds, allow_writes: allowWrites }),
    }),

  // Scheduled scripts (cron)
  listSchedules: () => request<Schedule[]>("/api/schedules"),
  getSchedule: (id: string) => request<Schedule>(`/api/schedules/${id}`),
  createSchedule: (body: {
    name?: string | null;
    script_id: string;
    connection_ids: string[];
    cron: string;
    timezone: string;
    allow_writes: boolean;
    enabled: boolean;
  }) => request<Schedule>("/api/schedules", { method: "POST", body: JSON.stringify(body) }),
  updateSchedule: (
    id: string,
    body: Partial<{
      name: string | null;
      script_id: string;
      connection_ids: string[];
      cron: string;
      timezone: string;
      allow_writes: boolean;
      enabled: boolean;
    }>,
  ) => request<Schedule>(`/api/schedules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteSchedule: (id: string) => request<void>(`/api/schedules/${id}`, { method: "DELETE" }),
  runScheduleNow: (id: string) =>
    request<JobEnqueued>(`/api/schedules/${id}/run-now`, { method: "POST" }),
  getScheduleRuns: (id: string) => request<ScheduledRun[]>(`/api/schedules/${id}/runs`),
  previewCron: (cron: string, timezone: string) =>
    request<CronPreview>("/api/schedules/preview", {
      method: "POST",
      body: JSON.stringify({ cron, timezone }),
    }),

  // ETL Pipelines
  listPipelines: () => request<PipelineSummary[]>("/api/pipelines"),
  getPipeline: (id: string) => request<Pipeline>(`/api/pipelines/${id}`),
  createPipeline: (body: { name: string; description?: string; steps: PipelineStepIO[] }) =>
    request<Pipeline>("/api/pipelines", { method: "POST", body: JSON.stringify(body) }),
  updatePipeline: (
    id: string,
    body: { name?: string; description?: string; steps?: PipelineStepIO[] },
  ) => request<Pipeline>(`/api/pipelines/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deletePipeline: (id: string) => request<void>(`/api/pipelines/${id}`, { method: "DELETE" }),
  runPipeline: (id: string) =>
    request<PipelineRunEnqueued>(`/api/pipelines/${id}/runs`, { method: "POST" }),
  getPipelineRun: (runId: string) => request<PipelineRun>(`/api/pipelines/runs/${runId}`),
  listPipelineRuns: (id: string) =>
    request<PipelineRunSummary[]>(`/api/pipelines/${id}/runs`),

  // Activity (unified runs feed)
  listActivity: () => request<ActivityEntry[]>("/api/activity"),

  // Settings
  getSettings: () => request<AppSettings>("/api/settings"),
  updateAnthropicKey: (apiKey: string) =>
    request<{ anthropic_api_key_set: boolean }>("/api/settings/anthropic-key", {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    }),

  // Chat
  getChatModels: () => request<ChatModels>("/api/chat/models"),
  listChatSessions: () => request<ChatSessionSummary[]>("/api/chat/sessions"),
  getChatSession: (id: string) => request<ChatSessionDetail>(`/api/chat/sessions/${id}`),
  createChatSession: (body: { title?: string | null; model: string; messages: ChatMessage[] }) =>
    request<ChatSessionDetail>("/api/chat/sessions", { method: "POST", body: JSON.stringify(body) }),
  updateChatSession: (
    id: string,
    body: { title?: string | null; model?: string | null; messages: ChatMessage[] },
  ) =>
    request<ChatSessionDetail>(`/api/chat/sessions/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteChatSession: (id: string) =>
    request<void>(`/api/chat/sessions/${id}`, { method: "DELETE" }),

  // MCP (live read-only connection)
  getActiveMcp: () => request<ActiveMcp | null>("/api/mcp/active"),
  mcpActivate: (connectionId: string) =>
    request<ActiveMcp>("/api/mcp/activate", {
      method: "POST",
      body: JSON.stringify({ connection_id: connectionId }),
    }),
  mcpDeactivate: () => request<void>("/api/mcp/deactivate", { method: "POST" }),
};

/** POST `body` to `path` and pump the plain-text streaming response into `onToken`.
 * Resolves when the stream ends; rejects (incl. AbortError) on transport failure. */
async function streamPost(
  path: string,
  body: unknown,
  opts: { onToken: (chunk: string) => void; signal?: AbortSignal },
): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: opts.signal,
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) opts.onToken(decoder.decode(value, { stream: true }));
  }
  const tail = decoder.decode();
  if (tail) opts.onToken(tail);
}

/** Stream a chat completion. Calls `onToken` with each text chunk as it arrives. */
export function streamChat(
  body: { model: string; messages: ChatMessage[] },
  opts: { onToken: (chunk: string) => void; signal?: AbortSignal },
): Promise<void> {
  return streamPost("/api/chat/stream", body, opts);
}

/** Ask Mel to describe a SQL script, streaming the Markdown breakdown back token by token. */
export function streamDescribeSql(
  sql: string,
  opts: { onToken: (chunk: string) => void; signal?: AbortSignal },
): Promise<void> {
  return streamPost("/api/chat/describe-sql", { sql }, opts);
}

export { ApiError };
