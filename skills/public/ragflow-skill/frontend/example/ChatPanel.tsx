"use client";

/**
 * Minimal example — copy into your DeerFlow / Next.js frontend.
 *
 * Prerequisites:
 *   - User logged in (access_token + csrf_token cookies)
 *   - ragflow-retrieval skill enabled in DeerFlow
 *   - setDeerFlowBaseUrl() if Gateway is not localhost:2026
 */

import { useState } from "react";

import { setDeerFlowBaseUrl, useDeerFlowChat } from "../lib";

// setDeerFlowBaseUrl("https://your-deerflow-host");

export function RagflowChatPanel() {
  const [input, setInput] = useState("");
  const { ask, answer, citations, summary, loading, error } = useDeerFlowChat();

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <header className="text-sm text-muted-foreground">
        {summary?.ok && (
          <span>
            {summary.label ?? summary.intent}
            {summary.departments?.length
              ? ` · ${summary.departments.join("、")}`
              : ""}
          </span>
        )}
      </header>

      <main className="flex-1 overflow-auto whitespace-pre-wrap rounded-md border p-4">
        {error && <p className="text-destructive">{error}</p>}
        {!error && (answer || (loading && "思考中…"))}
      </main>

      {citations.length > 0 && (
        <aside className="max-h-48 overflow-auto rounded-md border p-3 text-sm">
          <h3 className="mb-2 font-medium">参考来源</h3>
          <ul className="space-y-2">
            {citations.map((c) => (
              <li key={c.ref}>
                <strong>
                  [{c.ref}] {c.document_name}
                </strong>
                {typeof c.similarity === "number" && (
                  <span className="ml-2 text-muted-foreground">
                    {c.similarity.toFixed(4)}
                  </span>
                )}
                <p className="mt-1 line-clamp-3 text-muted-foreground">
                  {c.snippet ?? c.content}
                </p>
              </li>
            ))}
          </ul>
        </aside>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(input);
        }}
      >
        <input
          className="flex-1 rounded-md border px-3 py-2"
          placeholder="例如：办公室考勤制度怎么规定？"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
        />
        <button
          type="submit"
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
          disabled={loading || !input.trim()}
        >
          {loading ? "检索中…" : "提问"}
        </button>
      </form>
    </div>
  );
}
