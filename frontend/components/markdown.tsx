"use client";

import { useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, Loader2, Save } from "lucide-react";

/** Clipboard write with a fallback for non-secure (plain-http) contexts where
 * navigator.clipboard is unavailable. */
function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      resolve();
    } catch (e) {
      reject(e);
    }
  });
}

function CodeBlock({
  code,
  lang,
  onSave,
}: {
  code: string;
  lang?: string;
  onSave?: (code: string) => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function onCopy() {
    try {
      await copyText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — nothing we can do */
    }
  }

  async function handleSave() {
    if (!onSave) return;
    setSaving(true);
    try {
      await onSave(code);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      /* the caller surfaces a toast on error */
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="my-2 overflow-hidden rounded-md border bg-background">
      <div className="flex items-center justify-between gap-3 border-b bg-muted px-3 py-1">
        <span className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
          {lang || "code"}
        </span>
        <div className="flex items-center gap-3">
          {onSave && (
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              title="Save to the SQL Scripts page"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : saved ? (
                <Check className="h-3 w-3" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              {saved ? "Saved" : "Save to Scripts"}
            </button>
          )}
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      <pre className="overflow-x-auto p-3">
        <code className="font-mono text-xs leading-relaxed">{code}</code>
      </pre>
    </div>
  );
}

// Static (no-closure) element overrides shared across renders.
const BASE_COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>,
  h1: ({ children }) => <h3 className="mb-1 mt-3 font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1 mt-3 font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 mt-2 font-semibold first:mt-0">{children}</h4>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="underline">
      {children}
    </a>
  ),
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border px-2 py-1 text-left font-medium">{children}</th>,
  td: ({ children }) => <td className="border px-2 py-1 align-top">{children}</td>,
  // Block code renders via CodeBlock (which supplies its own <pre>); unwrap react-markdown's <pre>.
  pre: ({ children }) => <>{children}</>,
};

/** `onSaveSql`, when provided, adds a "Save to Scripts" button to ```sql blocks. */
export function Markdown({
  children,
  onSaveSql,
}: {
  children: string;
  onSaveSql?: (code: string) => Promise<void>;
}) {
  const components = useMemo<Components>(
    () => ({
      ...BASE_COMPONENTS,
      code: ({ className, children }) => {
        const text = String(children ?? "");
        const lang = /language-(\w+)/.exec(className || "")?.[1];
        // Fenced blocks carry a language- class or span multiple lines; everything else is inline.
        if (!lang && !text.includes("\n")) {
          return (
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
          );
        }
        return (
          <CodeBlock
            code={text.replace(/\n$/, "")}
            lang={lang}
            onSave={onSaveSql && lang === "sql" ? onSaveSql : undefined}
          />
        );
      },
    }),
    [onSaveSql],
  );

  return (
    <div className="text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
