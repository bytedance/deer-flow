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

export type StreamEvent = {
  event: "values" | "messages-tuple" | "custom" | "end";
  data: unknown;
};

export type ThreadInfo = {
  thread_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type DeerFlowClientOptions = {
  baseUrl: string;
  headers?: Record<string, string>;
};
