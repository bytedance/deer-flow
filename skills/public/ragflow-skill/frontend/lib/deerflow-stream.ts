/**
 * DeerFlow 2.0 LangGraph SSE client for custom frontends.
 *
 * Usage:
 *   1. Log in via DeerFlow Gateway (sets access_token + csrf_token cookies).
 *   2. streamDeerFlowAnswer(question, handlers) → streamed assistant markdown.
 *   3. After stream ends, fetchQuerySummary(threadId) for ragflow-retrieval citations.
 *
 * Copy this file into your frontend project (e.g. src/lib/deerflow-stream.ts).
 */

/** DeerFlow Gateway base URL — override via setDeerFlowBaseUrl() or env. */
let deerFlowBaseUrl = "http://localhost:2026";

export function setDeerFlowBaseUrl(url: string): void {
  deerFlowBaseUrl = url.replace(/\/$/, "");
}

function langGraphBase(): string {
  return `${deerFlowBaseUrl}/api/langgraph`;
}

function gatewayBase(): string {
  return `${deerFlowBaseUrl}/api`;
}

/** DeerFlow 2.0 default lead agent id. */
export const DEERFLOW_ASSISTANT_ID = "lead_agent";

/** LangGraph-supported stream modes (do not include "tools"). */
export const DEERFLOW_STREAM_MODES = [
  "values",
  "messages-tuple",
  "custom",
] as const;

// ─── Types ───────────────────────────────────────────────────────────────────

export interface DeerFlowStreamHandlers {
  /** Incremental assistant text delta. */
  onDelta?: (delta: string, fullText: string) => void;
  /** Thread / run metadata. */
  onStart?: (meta: { threadId: string; runId?: string }) => void;
  /** Custom graph events (task_running, llm_retry, …). */
  onCustom?: (event: unknown) => void;
  /** Stream finished successfully. */
  onFinish?: (fullText: string) => void;
  /** Stream or network error. */
  onError?: (error: Error) => void;
}

export interface StreamDeerFlowAnswerOptions {
  threadId?: string;
  modelName?: string;
  recursionLimit?: number;
  assistantId?: string;
}

export interface CitationItem {
  ref: number;
  document_name: string;
  content: string;
  snippet?: string;
  similarity?: number;
  document_id?: string;
  chunk_id?: string;
  meta_fields?: Record<string, unknown>;
}

export interface QuerySummary {
  ok: boolean;
  intent?: string;
  label?: string;
  departments?: string[];
  citation_count?: number;
  citations?: CitationItem[];
}

// ─── Auth ────────────────────────────────────────────────────────────────────

export function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const prefix = "csrf_token=";
  for (const pair of document.cookie.split("; ")) {
    if (pair.startsWith(prefix)) {
      return decodeURIComponent(pair.slice(prefix.length));
    }
  }
  return null;
}

export async function fetchWithAuth(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();

  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = readCsrfCookie();
    if (csrf && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRF-Token", csrf);
    }
  }

  const res = await fetch(input, {
    ...init,
    headers,
    credentials: "include",
  });

  if (res.status === 401) {
    throw new Error("Unauthorized — please log in to DeerFlow first");
  }
  return res;
}

// ─── Threads ─────────────────────────────────────────────────────────────────

export async function createDeerFlowThread(): Promise<string> {
  const res = await fetchWithAuth(`${langGraphBase()}/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ metadata: {} }),
  });

  if (!res.ok) {
    throw new Error(`Create thread failed: ${res.status} ${await res.text()}`);
  }

  const data = (await res.json()) as { thread_id: string };
  return data.thread_id;
}

// ─── SSE parsing ─────────────────────────────────────────────────────────────

interface SseFrame {
  event: string;
  data: string;
}

async function* readSseFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let sep = buffer.indexOf("\n\n");
    while (sep !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      let event = "message";
      const dataLines: string[] = [];

      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }

      if (dataLines.length > 0) {
        yield { event, data: dataLines.join("\n") };
      }

      sep = buffer.indexOf("\n\n");
    }
  }
}

function safeJsonParse(raw: string): unknown {
  if (!raw || raw === "[DONE]") return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

function extractTextContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "string") return block;
        if (
          block &&
          typeof block === "object" &&
          "type" in block &&
          (block as { type?: string }).type === "text" &&
          "text" in block
        ) {
          return String((block as { text?: string }).text ?? "");
        }
        return "";
      })
      .join("");
  }
  return "";
}

function handleMessagesTuple(
  payload: unknown,
  prevFullText: string,
): { delta: string; fullText: string } {
  if (!Array.isArray(payload) || payload.length === 0) {
    return { delta: "", fullText: prevFullText };
  }

  const message = payload[0] as {
    type?: string;
    role?: string;
    content?: unknown;
  };

  const isAssistant =
    message?.type === "ai" ||
    message?.type === "AIMessageChunk" ||
    message?.role === "assistant";

  if (!isAssistant) {
    return { delta: "", fullText: prevFullText };
  }

  const nextFull = extractTextContent(message.content);
  const delta = nextFull.startsWith(prevFullText)
    ? nextFull.slice(prevFullText.length)
    : nextFull;

  return { delta, fullText: nextFull };
}

function handleValues(
  payload: unknown,
  prevFullText: string,
): { delta: string; fullText: string } {
  const values = payload as {
    messages?: Array<{ type?: string; content?: unknown }>;
  };
  const messages = values?.messages ?? [];
  const lastAi = [...messages]
    .reverse()
    .find((m) => m.type === "ai" || m.type === "AIMessage");

  if (!lastAi) return { delta: "", fullText: prevFullText };

  const nextFull = extractTextContent(lastAi.content);
  const delta = nextFull.startsWith(prevFullText)
    ? nextFull.slice(prevFullText.length)
    : nextFull;

  return { delta, fullText: nextFull };
}

// ─── Main stream API ─────────────────────────────────────────────────────────

export async function streamDeerFlowAnswer(
  question: string,
  handlers: DeerFlowStreamHandlers = {},
  options: StreamDeerFlowAnswerOptions = {},
): Promise<{ threadId: string; fullText: string }> {
  const threadId = options.threadId ?? (await createDeerFlowThread());
  const assistantId = options.assistantId ?? DEERFLOW_ASSISTANT_ID;

  const res = await fetchWithAuth(
    `${langGraphBase()}/threads/${threadId}/runs/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        assistant_id: assistantId,
        input: {
          messages: [{ role: "user", content: question }],
        },
        config: {
          recursion_limit: options.recursionLimit ?? 100,
          configurable: {
            ...(options.modelName ? { model_name: options.modelName } : {}),
          },
        },
        stream_mode: DEERFLOW_STREAM_MODES,
      }),
    },
  );

  if (!res.ok || !res.body) {
    throw new Error(`Stream failed: ${res.status} ${await res.text()}`);
  }

  handlers.onStart?.({ threadId });

  let fullText = "";

  try {
    for await (const frame of readSseFrames(res.body)) {
      const payload = safeJsonParse(frame.data);
      if (payload == null) continue;

      switch (frame.event) {
        case "metadata": {
          const meta = payload as { run_id?: string };
          if (meta.run_id) {
            handlers.onStart?.({ threadId, runId: meta.run_id });
          }
          break;
        }

        case "messages":
        case "messages-tuple": {
          const { delta, fullText: next } = handleMessagesTuple(
            payload,
            fullText,
          );
          fullText = next;
          if (delta) handlers.onDelta?.(delta, fullText);
          break;
        }

        case "values": {
          const { delta, fullText: next } = handleValues(payload, fullText);
          fullText = next;
          if (delta) handlers.onDelta?.(delta, fullText);
          break;
        }

        case "custom":
          handlers.onCustom?.(payload);
          break;

        case "error": {
          const err = payload as { message?: string };
          throw new Error(err?.message ?? "Stream error");
        }

        case "end":
          break;
      }
    }
  } catch (err) {
    const error = err instanceof Error ? err : new Error(String(err));
    handlers.onError?.(error);
    throw error;
  }

  handlers.onFinish?.(fullText);
  return { threadId, fullText };
}

// ─── ragflow-retrieval artifacts ─────────────────────────────────────────────

const SUMMARY_ARTIFACT =
  "mnt/user-data/outputs/query.summary.json";
const CITATIONS_ARTIFACT =
  "mnt/user-data/outputs/query.retrieval.citations.json";

export async function fetchQuerySummary(
  threadId: string,
): Promise<QuerySummary | null> {
  const url = `${gatewayBase()}/threads/${threadId}/artifacts/${SUMMARY_ARTIFACT}`;
  const res = await fetchWithAuth(url);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Fetch summary failed: ${res.status}`);
  }
  return (await res.json()) as QuerySummary;
}

export async function fetchCitations(
  threadId: string,
): Promise<CitationItem[]> {
  const url = `${gatewayBase()}/threads/${threadId}/artifacts/${CITATIONS_ARTIFACT}`;
  const res = await fetchWithAuth(url);
  if (res.status === 404) return [];
  if (!res.ok) {
    throw new Error(`Fetch citations failed: ${res.status}`);
  }
  const data = (await res.json()) as { citations?: CitationItem[] };
  return data.citations ?? [];
}
