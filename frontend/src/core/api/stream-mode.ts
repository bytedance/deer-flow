/**
 * Stream mode compatibility layer for LangGraph SDK + langgraph-api 0.7.x.
 *
 * @langchain/langgraph-sdk can expand streamMode based on subscribed handlers
 * (onLangChainEvent, onUpdateEvent, etc.), sending values like "tools",
 * "updates", "events" that langgraph-api 0.7.x does not recognize, causing
 * 422 validation errors. This sanitizer filters to a supported allowlist.
 *
 * @see https://github.com/bytedance/deer-flow/issues/1043
 * @see https://github.com/bytedance/deer-flow/pull/1050
 */

/**
 * Modes supported by langgraph-api 0.7.x. Excludes: tools, events
 * which cause 422 validation errors.
 */
const SUPPORTED_STREAM_MODES = new Set([
  "values",
  "messages-tuple",
  "messages",
  "custom",
  "updates",
  "checkpoints",
  "debug",
  "tasks",
]);

const droppedWarned = new Set<string>();

function warnOnce(mode: string) {
  if (droppedWarned.has(mode)) return;
  droppedWarned.add(mode);
  console.warn(
    `[deer-flow] Dropping unsupported stream_mode "${mode}" for langgraph-api compatibility`,
  );
}

export type RunStreamOptions = {
  streamMode?: string[] | string;
  [key: string]: unknown;
};

/**
 * Sanitize stream_mode in run options to only include values supported by
 * langgraph-api 0.7.x. Drops unsupported modes and logs a one-time warning.
 */
export function sanitizeRunStreamOptions<T extends RunStreamOptions>(
  options: T | undefined,
): T | undefined {
  if (!options || !("streamMode" in options)) return options;

  const raw = options.streamMode;
  if (raw === undefined) return options;

  const modes = Array.isArray(raw) ? raw : [raw];
  const sanitized = modes.filter((m) => {
    const supported = SUPPORTED_STREAM_MODES.has(m);
    if (!supported) warnOnce(m);
    return supported;
  });

  if (sanitized.length === modes.length) return options;

  if (sanitized.length === 0) {
    return { ...options, streamMode: ["values"] };
  }

  return { ...options, streamMode: sanitized };
}
