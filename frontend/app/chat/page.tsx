"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, Loader2, PanelLeft, Plus, Send, Trash2 } from "lucide-react";
import { api, ApiError, streamChat } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/markdown";
import { Card, CardContent } from "@/components/ui/card";
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

// Shown on the empty state to invite use and showcase what Mel is good at.
const SUGGESTIONS = [
  "Write a query to find the largest tables and their index bloat in Postgres.",
  "How do I safely add a NOT NULL column to a 50M-row table with zero downtime?",
  "Explain the trade-offs between a CTE and a subquery for performance.",
  "What's the fastest, safest way to bulk-load millions of rows into Postgres?",
];

export default function ChatPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const models = useQuery({ queryKey: ["chat-models"], queryFn: api.getChatModels });
  const sessions = useQuery({ queryKey: ["chat-sessions"], queryFn: api.listChatSessions });

  const [model, setModel] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false); // collapsed by default
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Seed the selector with the server's default once models load.
  useEffect(() => {
    if (!model && models.data) setModel(models.data.default);
  }, [model, models.data]);

  // Auto-scroll to the newest content.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  // Abort any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const keySet = settings.data?.anthropic_api_key_set ?? true; // assume set until known

  // Save a SQL snippet from a chat response to the SQL Scripts page — stays on chat.
  async function saveToScripts(code: string) {
    const name = scriptName(code);
    try {
      await api.createScript({ name, content: code });
    } catch (e) {
      // Vanishingly rare name collision (same snippet+second) — retry with a unique suffix.
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

  // Upsert the conversation after a completed turn so it survives refresh / New chat.
  async function persist(final: ChatMessage[]) {
    try {
      if (sessionId) {
        await api.updateChatSession(sessionId, { model, messages: final });
      } else {
        const created = await api.createChatSession({ model, messages: final }); // title derived server-side
        setSessionId(created.id);
      }
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    } catch {
      toast.error("Couldn't save chat history"); // non-fatal — keep chatting
    }
  }

  function newChat() {
    abortRef.current?.abort();
    setMessages([]);
    setInput("");
    setSessionId(null);
  }

  async function openSession(id: string) {
    if (id === sessionId) return;
    abortRef.current?.abort();
    try {
      const s = await api.getChatSession(id);
      setMessages(s.messages);
      setModel(s.model);
      setSessionId(s.id);
      setInput("");
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

  async function send() {
    const text = input.trim();
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
        { model, messages: history },
        {
          signal: ctrl.signal,
          onToken: (chunk) => {
            assembled += chunk;
            setMessages((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              copy[copy.length - 1] = { ...last, content: last.content + chunk };
              return copy;
            });
          },
        },
      );
      // Clean completion → persist the full transcript.
      await persist([...history, { role: "assistant", content: assembled }]);
    } catch (e) {
      // Aborted (New chat / open another) → don't save a partial turn.
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

  function useSuggestion(text: string) {
    setInput(text);
    inputRef.current?.focus();
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Top bar */}
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
              Database expert — schemas, migrations, and SQL across engines
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
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
          {/* History rail — collapsed by default, toggled from the top bar. */}
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

          {/* Chat column */}
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
                  </p>
                  <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
                    {SUGGESTIONS.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => useSuggestion(s)}
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
                </div>
              )}
            </div>

            {/* Composer */}
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
                  Mel can make mistakes — verify destructive SQL before running it.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
