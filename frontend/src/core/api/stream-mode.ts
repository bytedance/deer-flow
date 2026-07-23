const SUPPORTED_RUN_STREAM_MODES = new Set([
  "values",
  "messages",
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
    `[deer-flow] Dropped unsupported LangGraph stream mode(s): ${unseenModes.join(", ")}`,
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
  const sanitizedModes = requestedModes.filter((mode) =>
    SUPPORTED_RUN_STREAM_MODES.has(mode),
  );

  if (sanitizedModes.length === requestedModes.length) {
    return sanitizedOptions;
  }

  const droppedModes = requestedModes.filter(
    (mode) => !SUPPORTED_RUN_STREAM_MODES.has(mode),
  );
  warnUnsupportedStreamModes(droppedModes);

  if (sanitizedModes.length === 0) {
    throw new Error(
      `[deer-flow] No supported LangGraph stream modes remain after rejecting: ${droppedModes.join(", ")}`,
    );
  }

  return {
    ...sanitizedOptions,
    streamMode: Array.isArray(streamMode) ? sanitizedModes : sanitizedModes[0],
  };
}
