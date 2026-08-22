export type MessageContentPart = {
  type?: string;
  text?: string;
  [key: string]: unknown;
};

export type Message = {
  id?: string;
  type?: string;
  role?: string;
  name?: string;
  content?: string | MessageContentPart[];
  tool_calls?: unknown[];
  tool_call_id?: string;
  usage_metadata?: Record<string, unknown>;
  [key: string]: unknown;
};

export type MessageChunk = {
  id?: string;
  type?: string;
  role?: string;
  content?: string;
  name?: string;
  tool_calls?: unknown[];
  tool_call_id?: string;
  usage_metadata?: Record<string, unknown>;
  [key: string]: unknown;
};

export type Artifact = {
  id?: string;
  name?: string;
  path?: string;
  mime_type?: string;
  size?: number;
  [key: string]: unknown;
};

export type ValuesEvent = {
  messages: Message[];
  title?: string;
  artifacts?: Artifact[];
  [key: string]: unknown;
};

export type MessagesTupleEvent = [message: MessageChunk, metadata: Record<string, unknown>];

/**
 * SSE event names emitted by DeerFlow's LangGraph gateway. The set depends on
 * the requested `stream_mode`:
 *   - `values`: full state snapshots (stream_mode=values)
 *   - `messages`: plain message chunks (stream_mode=messages)
 *   - `messages-tuple`: [chunk, metadata] tuples (stream_mode=messages-tuple, the useStream default)
 *   - `custom`: user-dispatched custom payloads
 *   - `metadata`: run metadata (gateway-compatible streams)
 *   - `error`: per-chunk error frames (gateway-compatible streams)
 *   - `end`: terminal frame signaling the stream has closed
 */
export type StreamEventName =
  | "values"
  | "messages"
  | "messages-tuple"
  | "custom"
  | "metadata"
  | "error"
  | "end";

export type StreamEvent =
  | { event: "values"; data: ValuesEvent }
  | { event: "messages"; data: MessageChunk }
  | { event: "messages-tuple"; data: MessagesTupleEvent }
  | { event: "custom"; data: unknown }
  | { event: "metadata"; data: Record<string, unknown> }
  | { event: "error"; data: { message?: string; [key: string]: unknown } }
  | { event: "end"; data: unknown };

export type ThreadInfo = {
  thread_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type DeerFlowClientOptions = {
  baseUrl: string;
  headers?: Record<string, string>;
};
