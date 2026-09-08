/** Build deep-links into Mel chat with optional MCP activation + prefilled prompt. */

export function melChatHref(opts: {
  prompt?: string;
  connectionId?: string;
  activateMcp?: boolean;
}): string {
  const params = new URLSearchParams();
  if (opts.prompt?.trim()) params.set("prompt", opts.prompt.trim());
  if (opts.connectionId) params.set("connection", opts.connectionId);
  if (opts.activateMcp) params.set("mcp", "1");
  const q = params.toString();
  return q ? `/chat?${q}` : "/chat";
}

export function askMelAboutConnection(name: string, connectionId: string): string {
  return melChatHref({
    connectionId,
    activateMcp: true,
    prompt: `I've activated connection "${name}" as the live read-only MCP target. Please list the tables and give me a quick orientation of what's in this database.`,
  });
}

export function askMelAboutSchema(connectionName: string, connectionId: string, schema: string): string {
  return melChatHref({
    connectionId,
    activateMcp: true,
    prompt: `Focus on schema "${schema}" in connection "${connectionName}". Summarize the tables and anything notable (RLS, large tables, odd types).`,
  });
}

export function askMelAboutTable(
  connectionName: string,
  connectionId: string,
  schema: string,
  table: string,
): string {
  return melChatHref({
    connectionId,
    activateMcp: true,
    prompt: `Describe table ${schema}.${table} on connection "${connectionName}" (columns, keys, anything risky to migrate) and suggest a couple of useful read-only investigative queries.`,
  });
}

export function askMelAboutComparison(label: string): string {
  return melChatHref({
    prompt: `Help me interpret this schema comparison: ${label}. What should I watch for before migrating?`,
  });
}

export function askMelAboutMigration(label: string): string {
  return melChatHref({
    prompt: `I'm looking at migration run: ${label}. What pre-flight checks and cutover risks should I double-check?`,
  });
}
