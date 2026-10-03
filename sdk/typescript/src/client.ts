import { parseSSEStream } from "./sse.js";
import type {
  DeerFlowClientOptions,
  MessageChunk,
  MessagesTupleEvent,
  StreamEvent,
  StreamEventName,
  ThreadInfo,
  ValuesEvent,
} from "./types.js";

const KNOWN_STREAM_EVENTS = new Set<StreamEventName>([
  "values",
  "messages",
  "messages-tuple",
  "custom",
  "metadata",
  "error",
  "end",
]);

type RunStreamRequest = {
  assistant_id: string;
  input: {
    messages: Array<{
      type: "human";
      content: Array<{
        type: "text";
        text: string;
      }>;
    }>;
  };
  stream_mode: Array<"values" | "messages-tuple" | "custom">;
  stream_subgraphs: boolean;
  context: {
    thread_id: string;
  };
};

export class DeerFlowClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;

  constructor(options: DeerFlowClientOptions) {
    if (!options.baseUrl) {
      throw new Error("DeerFlowClient requires a baseUrl");
    }

    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.headers = {
      ...(options.headers ?? {}),
    };
  }

  async createThread(metadata: Record<string, unknown> = {}): Promise<ThreadInfo> {
    return this.requestJson<ThreadInfo>("/threads", {
      method: "POST",
      body: JSON.stringify({ metadata }),
    });
  }

  async getThreadState(threadId: string): Promise<ValuesEvent> {
    const state = await this.requestJson<{ values?: ValuesEvent }>(`/threads/${encodeURIComponent(threadId)}/state`, {
      method: "GET",
    });

    return state.values ?? ({ messages: [] } as ValuesEvent);
  }

  async *stream(message: string, threadId?: string): AsyncGenerator<StreamEvent> {
    const resolvedThreadId = threadId ?? (await this.createThread()).thread_id;
    const payload: RunStreamRequest = {
      assistant_id: "lead_agent",
      input: {
        messages: [
          {
            type: "human",
            content: [{ type: "text", text: message }],
          },
        ],
      },
      stream_mode: ["values", "messages-tuple", "custom"],
      stream_subgraphs: true,
      context: {
        thread_id: resolvedThreadId,
      },
    };

    const response = await fetch(this.resolve(`/threads/${encodeURIComponent(resolvedThreadId)}/runs/stream`), {
      method: "POST",
      headers: this.requestHeaders(),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Failed to stream run (${response.status}): ${detail || response.statusText}`);
    }

    if (!response.body) {
      throw new Error("SSE stream response has no body");
    }

    for await (const rawEvent of parseSSEStream(response.body)) {
      if (!KNOWN_STREAM_EVENTS.has(rawEvent.event as StreamEventName)) {
        continue;
      }

      let parsed: unknown = rawEvent.data;
      try {
        parsed = JSON.parse(rawEvent.data);
      } catch {
        // Keep original string when server sends non-JSON payload.
      }

      yield {
        event: rawEvent.event,
        data: parsed,
      } as StreamEvent;
    }
  }

  async chat(message: string, threadId?: string): Promise<string> {
    let lastValues: ValuesEvent | null = null;
    const textByMessageId = new Map<string, string>();

    for await (const event of this.stream(message, threadId)) {
      if (event.event === "values" && isValuesEvent(event.data)) {
        lastValues = event.data;
        continue;
      }

      let chunk: MessageChunk | undefined;

      if (event.event === "messages-tuple" && Array.isArray(event.data)) {
        chunk = (event.data as MessagesTupleEvent)[0];
      } else if (event.event === "messages" && event.data && typeof event.data === "object") {
        chunk = event.data as MessageChunk;
      }

      if (!chunk || chunk.type !== "ai" || typeof chunk.content !== "string") {
        continue;
      }

      const id = typeof chunk.id === "string" ? chunk.id : "_final";
      textByMessageId.set(id, (textByMessageId.get(id) ?? "") + chunk.content);
    }

    if (textByMessageId.size > 0) {
      return Array.from(textByMessageId.values()).join("\n").trim();
    }

    if (!lastValues?.messages?.length) {
      return "";
    }

    for (let i = lastValues.messages.length - 1; i >= 0; i -= 1) {
      const msg = lastValues.messages[i];
      if (msg?.type !== "ai" && msg?.role !== "assistant") {
        continue;
      }

      if (typeof msg.content === "string") {
        return msg.content;
      }

      if (Array.isArray(msg.content)) {
        const text = msg.content
          .map((part) => (part && typeof part === "object" && "text" in part ? String((part as { text?: unknown }).text ?? "") : ""))
          .join("")
          .trim();

        if (text) {
          return text;
        }
      }
    }

    return "";
  }

  private resolve(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private requestHeaders(): Record<string, string> {
    return {
      "Content-Type": "application/json",
      ...this.headers,
    };
  }

  private async requestJson<T>(path: string, init: RequestInit): Promise<T> {
    const response = await fetch(this.resolve(path), {
      ...init,
      headers: {
        ...this.requestHeaders(),
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`Request failed (${response.status}): ${detail || response.statusText}`);
    }

    return (await response.json()) as T;
  }
}

function isValuesEvent(value: unknown): value is ValuesEvent {
  return typeof value === "object" && value !== null && Array.isArray((value as ValuesEvent).messages);
}
