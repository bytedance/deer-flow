const SUPPORTED_RUN_STREAM_MODES = new Set([
  "values",
  "messages-tuple",
  "updates",
  "debug",
  "tasks",
  "checkpoints",
  "custom",
] as const);

const warnedUnsupportedStreamModes = new Set<string>();
let warnedUnsupportedStreamResumable = false;

export function warnUnsupportedStreamModes(
  modes: string[],
  warn: (message: string) => void = console.warn,
) {
  const unseenModes = modes.filter((mode) => {
    if (warnedUnsupportedStreamModes.has(mode)) {
      return false;
    }
    warnedUnsupportedStreamModes.add(mode);
    return true;
  });

  if (unseenModes.length === 0) {
    return;
  }

  warn(
    `[deer-flow] Rejected unsupported LangGraph stream mode(s): ${unseenModes.join(", ")}`,
  );
}

export function sanitizeRunStreamOptions<T>(options: T): T {
  if (typeof options !== "object" || options === null) {
    return options;
  }

  let sanitizedOptions: T = options;
  if ("streamResumable" in options) {
    const withoutStreamResumable = { ...options };
    delete withoutStreamResumable.streamResumable;
    sanitizedOptions = withoutStreamResumable as T;

    if (!warnedUnsupportedStreamResumable) {
      warnedUnsupportedStreamResumable = true;
      console.warn(
        "[deer-flow] Dropped unsupported LangGraph run option: streamResumable",
      );
    }
  }

  if (!("streamMode" in options)) {
    return sanitizedOptions;
  }

  const streamMode = options.streamMode;
  if (streamMode == null) {
    return sanitizedOptions;
  }

  const requestedModes = Array.isArray(streamMode) ? streamMode : [streamMode];
  const droppedModes = requestedModes.filter(
    (mode) => !SUPPORTED_RUN_STREAM_MODES.has(mode),
  );
  if (droppedModes.length > 0) {
    warnUnsupportedStreamModes(droppedModes);
    throw new Error(
      `[deer-flow] Unsupported LangGraph stream mode(s): ${droppedModes.join(", ")}`,
    );
  }

  return sanitizedOptions;
}
