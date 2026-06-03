"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, Loader2, Plus, Send, Trash2 } from "lucide-react";
import { api, ApiError, streamChat } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/markdown";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader } from "@/components/page-header";

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
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <PageHeader
        title="Mel"
        description="Your DataMETL database assistant — a senior Postgres DBA for schemas, migrations, and SQL. Read-only for now (no direct DB access yet)."
        actions={
          <div className="flex items-center gap-2">
            <Select value={model} onValueChange={setModel} disabled={streaming}>
              <SelectTrigger className="w-[200px]">
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
        }
      />

      {!keySet ? (
        <Card>
          <CardContent className="py-10 text-center space-y-3">
            <p className="text-sm text-muted-foreground">
              No Anthropic API key is configured. Add one to start chatting.
            </p>
            <Button asChild>
              <Link href="/settings">Go to Settings</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="flex min-h-0 flex-1 gap-4">
          {/* History rail */}
          <aside className="hidden w-60 shrink-0 flex-col overflow-y-auto border-r pr-2 md:flex">
            <div className="px-1 pb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              History
            </div>
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
          </aside>

          {/* Chat column */}
          <div className="flex min-h-0 flex-1 flex-col">
            <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto pr-1">
              {messages.length === 0 ? (
                <div className="py-10 text-center">
                  <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <Bot className="h-8 w-8" />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Hi, I&apos;m Mel — your database assistant. Ask me about your schemas, migrations, or SQL.
                  </p>
                </div>
              ) : (
                messages.map((m, i) => (
                  <div
                    key={i}
                    className={m.role === "user" ? "flex justify-end" : "flex justify-start gap-2"}
                  >
                    {m.role === "assistant" && (
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <Bot className="h-4 w-4" />
                      </div>
                    )}
                    <div
                      className={
                        m.role === "user"
                          ? "max-w-[80%] rounded-lg bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground"
                          : "max-w-[85%] min-w-0 rounded-lg bg-muted px-3 py-2 text-sm"
                      }
                    >
                      {m.role === "assistant" ? (
                        m.content ? (
                          <Markdown onSaveSql={saveToScripts}>{m.content}</Markdown>
                        ) : streaming && i === messages.length - 1 ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : null
                      ) : (
                        m.content
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Composer */}
            <div className="mt-3 border-t pt-3">
              <div className="flex items-end gap-2">
                <Textarea
                  className="min-h-[2.5rem] max-h-40 resize-none"
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
                <Button onClick={() => void send()} disabled={!input.trim() || streaming || !model}>
                  {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
