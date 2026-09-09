"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, Check, Loader2, PanelLeft, Plus, Send, Trash2, X } from "lucide-react";
import { api, ApiError, streamChat } from "@/lib/api";
import type { ChatMessage, MelToolCard, MelToolCardApi } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/markdown";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** Build a friendly, likely-unique name for a saved snippet from its SQL. */
function scriptName(code: string): string {
  const firstMeaningful =
    code.split("\n").map((l) => l.trim()).find((l) => l && !l.startsWith("--")) ?? code.trim();
  const snippet = firstMeaningful.replace(/\s+/g, " ").slice(0, 40);
  const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return `Mel: ${snippet}${firstMeaningful.length > 40 ? "…" : ""} · ${t}`;
}

function whenLabel(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toolCardToApi(card: MelToolCard): MelToolCardApi {
  return {
    proposal_id: card.proposalId,
    name: card.name,
    args_summary: card.argsSummary,
    args: card.args ?? {},
    status: card.status,
    outcome_summary: card.outcomeSummary ?? null,
  };
}

function toolCardFromApi(card: MelToolCardApi): MelToolCard {
  return {
    proposalId: card.proposal_id,
    name: card.name,
    argsSummary: card.args_summary ?? "",
    args: card.args ?? {},
    status: card.status,
    outcomeSummary: card.outcome_summary ?? undefined,
  };
}

const SUGGESTIONS = [
  "Write a query to find the largest tables and their index bloat in Postgres.",
  "How do I safely add a NOT NULL column to a 50M-row table with zero downtime?",
  "Explain the trade-offs between a CTE and a subquery for performance.",
  "What's the fastest, safest way to bulk-load millions of rows into Postgres?",
];

export default function ChatPage() {
  return (
    <Suspense fallback={<p className="p-4 text-sm text-muted-foreground">Loading Mel…</p>}>
      <ChatPageBody />
    </Suspense>
  );
}

function ChatPageBody() {
  const qc = useQueryClient();
  const router = useRouter();
  const search = useSearchParams();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const models = useQuery({ queryKey: ["chat-models"], queryFn: api.getChatModels });
  const sessions = useQuery({ queryKey: ["chat-sessions"], queryFn: api.listChatSessions });
  const mcpActive = useQuery({
    queryKey: ["mcp-active"],
    queryFn: api.getActiveMcp,
    refetchInterval: 5_000,
  });

  const [model, setModel] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolCards, setToolCards] = useState<MelToolCard[]>([]);
  const toolCardsRef = useRef<MelToolCard[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const ambientHandled = useRef(false);

  useEffect(() => {
    if (!model && models.data) setModel(models.data.default);
  }, [model, models.data]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, toolCards]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Ambient Mel: ?prompt=&connection=&mcp=1 from Ask Mel entry points
  useEffect(() => {
    if (ambientHandled.current) return;
    const prompt = search.get("prompt");
    const connectionId = search.get("connection");
    const activateMcp = search.get("mcp") === "1";
    if (!prompt && !connectionId) return;
    ambientHandled.current = true;

    (async () => {
      try {
        if (activateMcp && connectionId) {
          await api.mcpActivate(connectionId);
          qc.invalidateQueries({ queryKey: ["mcp-active"] });
          toast.success("MCP activated for Mel — read-only");
        }
      } catch (e) {
        toast.error(`Couldn't activate MCP: ${String(e)}`);
      }
      if (prompt) {
        setInput(prompt);
        // Clear query params so refresh doesn't re-trigger
        router.replace("/chat");
        inputRef.current?.focus();
      } else {
        router.replace("/chat");
      }
    })();
  }, [search, qc, router]);

  const keySet = settings.data?.anthropic_api_key_set ?? true;

  async function saveToScripts(code: string) {
    const name = scriptName(code);
    try {
      await api.createScript({ name, content: code });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        await api.createScript({ name: `${name} (${Math.random().toString(36).slice(2, 6)})`, content: code });
      } else {
        toast.error(`Couldn't save: ${String(e)}`);
        throw e;
      }
    }
    qc.invalidateQueries({ queryKey: ["scripts"] });
    toast.success("Saved to SQL Scripts", {
      action: { label: "Open", onClick: () => router.push("/scripts") },
    });
  }

  async function persist(final: ChatMessage[], cards?: MelToolCard[]) {
    const tool_cards = (cards ?? toolCardsRef.current).map(toolCardToApi);
    try {
      if (sessionId) {
        await api.updateChatSession(sessionId, { model, messages: final, tool_cards });
      } else {
        const created = await api.createChatSession({ model, messages: final, tool_cards });
        setSessionId(created.id);
      }
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      qc.invalidateQueries({ queryKey: ["activity"] });
      qc.invalidateQueries({ queryKey: ["mel-audit"] });
    } catch {
      toast.error("Couldn't save chat history");
    }
  }

  function newChat() {
    abortRef.current?.abort();
    setMessages([]);
    setToolCards([]);
    toolCardsRef.current = [];
    setInput("");
    setSessionId(null);
  }

  async function openSession(id: string) {
    if (id === sessionId) return;
    abortRef.current?.abort();
    try {
      const s = await api.getChatSession(id);
      const cards = (s.tool_cards ?? []).map(toolCardFromApi);
      setMessages(s.messages);
      setModel(s.model);
      setSessionId(s.id);
      setInput("");
      setToolCards(cards);
      toolCardsRef.current = cards;
    } catch (e) {
      toast.error(`Couldn't open chat: ${String(e)}`);
    }
  }

  async function deleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await api.deleteChatSession(id);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      if (id === sessionId) newChat();
    } catch (err) {
      toast.error(`Couldn't delete: ${String(err)}`);
    }
  }

  function upsertToolCard(card: MelToolCard) {
    setToolCards((prev) => {
      const i = prev.findIndex((c) => c.proposalId === card.proposalId);
      let next: MelToolCard[];
      if (i < 0) {
        next = [...prev, card];
      } else {
        const prevCard = prev[i];
        const mergedArgs =
          card.args && Object.keys(card.args).length > 0 ? card.args : prevCard.args;
        next = [...prev];
        next[i] = { ...prevCard, ...card, args: mergedArgs };
      }
      toolCardsRef.current = next;
      return next;
    });
  }

  async function decideTool(proposalId: string, decision: "approve" | "deny") {
    setToolCards((prev) => {
      const next = prev.map((c) =>
        c.proposalId === proposalId
          ? { ...c, status: (decision === "approve" ? "running" : "denied") as MelToolCard["status"] }
          : c,
      );
      toolCardsRef.current = next;
      return next;
    });
    try {
      await api.decideMelTool(proposalId, decision);
    } catch (e) {
      toast.error(`Couldn't ${decision}: ${String(e)}`);
    }
  }

  async function send(override?: string) {
    const text = (override ?? input).trim();
    if (!text || streaming || !model) return;
    const history: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let assembled = "";
    try {
      await streamChat(
        { model, messages: history, session_id: sessionId },
        {
          signal: ctrl.signal,
          onEvent: (ev) => {
            if (ev.type === "token") {
              assembled += ev.text;
              setMessages((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                copy[copy.length - 1] = { ...last, content: last.content + ev.text };
                return copy;
              });
            } else if (ev.type === "tool_pending") {
              upsertToolCard({
                proposalId: ev.proposal_id,
                name: ev.name,
                argsSummary: ev.args_summary,
                args: ev.args,
                status: ev.status === "auto" ? "auto" : "pending",
              });
            } else if (ev.type === "tool_result") {
              const status =
                ev.status === "denied"
                  ? "denied"
                  : ev.outcome === "error"
                    ? "error"
                    : ev.status === "auto"
                      ? "auto"
                      : "success";
              upsertToolCard({
                proposalId: ev.proposal_id,
                name: ev.name,
                argsSummary: ev.args_summary,
                args: {},
                status,
                outcomeSummary: ev.outcome_summary,
              });
            } else if (ev.type === "error") {
              assembled += `\n\n[error: ${ev.message}]`;
              setMessages((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                copy[copy.length - 1] = {
                  ...last,
                  content: last.content + `\n\n[error: ${ev.message}]`,
                };
                return copy;
              });
            }
          },
        },
      );
      await persist([...history, { role: "assistant", content: assembled }]);
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        setMessages((prev) => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, content: last.content + `\n\n[error: ${String(e)}]` };
          return copy;
        });
      }
    } finally {
      setStreaming(false);
    }
  }

  function applySuggestion(text: string) {
    setInput(text);
    inputRef.current?.focus();
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={() => setHistoryOpen((o) => !o)}
            title={historyOpen ? "Hide chat history" : "Show chat history"}
            aria-pressed={historyOpen}
            className={cn(
              "hidden shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground md:inline-flex",
              historyOpen && "bg-accent text-foreground",
            )}
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 leading-tight">
            <div className="text-sm font-semibold">Mel</div>
            <div className="truncate text-xs text-muted-foreground">
              {mcpActive.data
                ? `Live read-only: ${mcpActive.data.name} (${mcpActive.data.engine})`
                : "Database expert — schemas, migrations, and SQL across engines"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {settings.data?.mel_tool_approval && (
            <Badge variant="outline" className="hidden sm:inline-flex" title="Mel tool approval mode">
              tools: {settings.data.mel_tool_approval.replace(/_/g, " ")}
            </Badge>
          )}
          <Select value={model} onValueChange={setModel} disabled={streaming}>
            <SelectTrigger className="w-[190px]">
              <SelectValue placeholder="Model…" />
            </SelectTrigger>
            <SelectContent>
              {models.data?.models.map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={newChat}>
            <Plus className="h-4 w-4 mr-1.5" /> New chat
          </Button>
        </div>
      </header>

      {!keySet ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <Card className="max-w-md">
            <CardContent className="space-y-3 py-10 text-center">
              <p className="text-sm text-muted-foreground">
                No Anthropic API key is configured. Add one to start chatting with Mel.
              </p>
              <Button asChild>
                <Link href="/settings">Go to Settings</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <aside
            className={cn(
              "w-72 shrink-0 flex-col border-r md:flex",
              historyOpen ? "hidden md:flex" : "hidden",
            )}
          >
            <div className="flex items-center justify-between px-3 py-2.5">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Chats
              </span>
              <button
                type="button"
                onClick={newChat}
                title="New chat"
                className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
              {sessions.isLoading ? (
                <p className="px-1 text-xs text-muted-foreground">Loading…</p>
              ) : !sessions.data?.length ? (
                <p className="px-1 text-xs text-muted-foreground">No saved chats yet.</p>
              ) : (
                <ul className="space-y-0.5">
                  {sessions.data.map((s) => (
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => openSession(s.id)}
                        className={cn(
                          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent",
                          s.id === sessionId && "bg-accent",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate">{s.title}</span>
                          <span className="block text-[10px] text-muted-foreground">
                            {whenLabel(s.updated_at)}
                          </span>
                        </span>
                        <span
                          role="button"
                          tabIndex={-1}
                          onClick={(e) => deleteSession(s.id, e)}
                          title="Delete chat"
                          className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>

          <div className="flex min-h-0 flex-1 flex-col">
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
              {messages.length === 0 ? (
                <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-4 text-center">
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <Bot className="h-9 w-9" />
                  </div>
                  <h2 className="text-lg font-semibold">Hi, I&apos;m Mel.</h2>
                  <p className="mt-1 max-w-md text-sm text-muted-foreground">
                    Your database expert for schemas, migrations, indexing, and SQL — across
                    Postgres, MySQL, SQL Server, Oracle, and more. Ask me anything.
                    {mcpActive.data
                      ? " A live read-only MCP connection is active — I can inspect it after you Approve tool calls."
                      : " Activate MCP on a connection to let me inspect it live (read-only)."}
                  </p>
                  <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => applySuggestion(s)}
                        className="rounded-lg border bg-card px-3 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:bg-accent hover:text-foreground"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
                  {messages.map((m, i) => (
                    <div
                      key={i}
                      className={m.role === "user" ? "flex justify-end" : "flex justify-start gap-3"}
                    >
                      {m.role === "assistant" && (
                        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                          <Bot className="h-5 w-5" />
                        </div>
                      )}
                      <div
                        className={
                          m.role === "user"
                            ? "max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground"
                            : "min-w-0 flex-1 rounded-2xl bg-muted px-4 py-3 text-sm"
                        }
                      >
                        {m.role === "assistant" ? (
                          m.content ? (
                            <Markdown onSaveSql={saveToScripts}>{m.content}</Markdown>
                          ) : streaming && i === messages.length - 1 ? (
                            <span className="flex items-center gap-2 text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin" /> Mel is thinking…
                            </span>
                          ) : null
                        ) : (
                          m.content
                        )}
                      </div>
                    </div>
                  ))}

                  {toolCards.length > 0 && (
                    <div className="space-y-2 pl-11">
                      {toolCards.map((c) => (
                        <ToolApprovalCard
                          key={c.proposalId}
                          card={c}
                          interactive={streaming}
                          onApprove={() => void decideTool(c.proposalId, "approve")}
                          onDeny={() => void decideTool(c.proposalId, "deny")}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="shrink-0 border-t bg-background">
              <div className="mx-auto w-full max-w-3xl px-4 py-3">
                <div className="flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm focus-within:border-primary/50">
                  <Textarea
                    ref={inputRef}
                    className="max-h-48 min-h-[2.5rem] resize-none border-0 bg-transparent px-2 py-1.5 shadow-none focus-visible:ring-0"
                    placeholder="Ask Mel… (Enter to send, Shift+Enter for newline)"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <Button
                    size="icon"
                    className="h-9 w-9 shrink-0 rounded-xl"
                    onClick={() => void send()}
                    disabled={!input.trim() || streaming || !model}
                  >
                    {streaming ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                <p className="mt-1.5 px-1 text-center text-[11px] text-muted-foreground">
                  Mel can make mistakes — verify destructive SQL before running it. Live tools are
                  read-only; {settings.data?.mel_tool_approval === "auto" ? "auto-run is on" : "run_sql waits for Approve"}{" "}
                  (change in Settings).
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ToolApprovalCard({
  card,
  interactive = true,
  onApprove,
  onDeny,
}: {
  card: MelToolCard;
  /** When false (reloaded history), show status only — Redis waiters are gone. */
  interactive?: boolean;
  onApprove: () => void;
  onDeny: () => void;
}) {
  const pending = card.status === "pending" && interactive;
  const statusLabel =
    card.status === "pending"
      ? interactive
        ? "Needs approval"
        : "Was pending"
      : card.status === "running"
        ? "Running…"
        : card.status === "denied"
          ? "Denied"
          : card.status === "error"
            ? "Error"
            : card.status === "auto"
              ? "Auto-ran"
              : "Approved";

  const variant =
    card.status === "denied" || card.status === "error"
      ? "destructive"
      : card.status === "pending"
        ? "warning"
        : "secondary";

  return (
    <div className="rounded-xl border bg-card px-3 py-2.5 text-sm shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-semibold">{card.name || "tool"}</span>
        <Badge variant={variant as "destructive" | "warning" | "secondary"}>{statusLabel}</Badge>
        {pending && (
          <span className="ml-auto flex gap-1.5">
            <Button size="sm" variant="outline" className="h-7 px-2" onClick={onDeny}>
              <X className="mr-1 h-3.5 w-3.5" /> Deny
            </Button>
            <Button size="sm" className="h-7 px-2" onClick={onApprove}>
              <Check className="mr-1 h-3.5 w-3.5" /> Approve
            </Button>
          </span>
        )}
        {card.status === "running" && (
          <Loader2 className="ml-auto h-4 w-4 animate-spin text-muted-foreground" />
        )}
      </div>
      {card.argsSummary && (
        <p className="mt-1.5 font-mono text-xs text-muted-foreground break-all">{card.argsSummary}</p>
      )}
      {card.outcomeSummary && (
        <p className="mt-1 text-xs text-muted-foreground">{card.outcomeSummary}</p>
      )}
    </div>
  );
}
