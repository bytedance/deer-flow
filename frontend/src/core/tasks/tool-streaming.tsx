import { createContext, useCallback, useContext, useState } from "react";

import type { ToolStreamOutput } from "./types";

/**
 * Wire shape of a ``tool_output_chunk`` custom stream event.  Contract owner:
 * `backend/packages/harness/deerflow/agents/middlewares/tool_streaming_middleware.py`.
 */
export interface ToolOutputChunkEvent {
  type: "tool_output_chunk";
  tool_call_id: string;
  tool_name: string;
  chunk: string;
  is_partial: boolean;
  is_final: boolean;
  error?: boolean;
}

export interface ToolStreamingState {
  /** Streaming outputs keyed by ``tool_call_id`` (globally unique UUID). */
  outputs: Readonly<Record<string, ToolStreamOutput>>;
}

export interface ToolStreamingContextValue {
  state: ToolStreamingState;
  /** Upsert or remove a streaming output entry. */
  updateToolStream: (
    toolCallId: string,
    output: ToolStreamOutput | null,
  ) => void;
  /**
   * Drop the named streaming output entries.  Deliberately scoped rather than
   * a whole-map reset: the provider is mounted once for a whole route, and
   * more than one stream can run through it at the same time (the main
   * conversation and the sidecar panel), so a run-end teardown must not remove
   * another stream's in-flight entries.
   */
  clearToolStream: (toolCallIds: Iterable<string>) => void;
}

/**
 * Map a ``tool_output_chunk`` event to a store update.
 *
 * Final chunks — success or error — map to ``null`` (teardown): the complete
 * result arrives via the canonical ToolMessage in the message stream, so
 * keeping the entry would leak one map entry per tool call for the lifetime
 * of the thread and keep the streaming indicator rendered for a finished
 * tool.  The store therefore only ever holds actively-streaming calls;
 * ``clearToolStreamState`` handles the case where the final chunk never
 * arrives because the run ended first.
 */
export function toolStreamUpdateFromEvent(
  e: ToolOutputChunkEvent,
): ToolStreamOutput | null {
  if (e.is_final) {
    return null;
  }
  return {
    toolName: e.tool_name,
    text: e.chunk,
    isPartial: e.is_partial,
    isError: !!e.error,
  };
}

/**
 * Pure reducer for the streaming-output map.  This is the exact logic the
 * provider runs — exported so unit tests exercise the production reducer
 * rather than a re-implementation.  Returns the input map (same reference)
 * for no-op updates so the provider can skip a render.
 */
export function applyToolStreamUpdate(
  outputs: Readonly<Record<string, ToolStreamOutput>>,
  toolCallId: string,
  output: ToolStreamOutput | null,
): Readonly<Record<string, ToolStreamOutput>> {
  if (output === null) {
    // Teardown: remove this tool call's entry from the map.
    if (!(toolCallId in outputs)) {
      return outputs;
    }
    const next = { ...outputs };
    delete next[toolCallId];
    return next;
  }
  const existing = outputs[toolCallId];
  // If a late partial chunk arrives for a call that already received its
  // final output, drop it — the completed entry must not regress.
  if (existing && output.isPartial && !existing.isPartial) {
    return outputs;
  }
  // Accumulate partial chunks so the streaming preview grows with each
  // intermediate dispatch rather than flashing the last fragment only.
  if (existing && output.isPartial && existing.isPartial) {
    return {
      ...outputs,
      [toolCallId]: {
        ...existing,
        text: existing.text + output.text,
        isPartial: true,
      },
    };
  }
  return { ...outputs, [toolCallId]: output };
}

/**
 * Pure teardown for the streaming-output entries named by ``toolCallIds``.
 * Scoping the teardown to the caller's own entries is what keeps a run ending
 * on one stream from erasing another stream's in-flight output when both share
 * the provider.  Returns the input map (same reference) when nothing was
 * removed so the provider can skip a render — mirroring
 * ``applyToolStreamUpdate``.
 */
export function clearToolStreamState(
  outputs: Readonly<Record<string, ToolStreamOutput>>,
  toolCallIds: Iterable<string>,
): Readonly<Record<string, ToolStreamOutput>> {
  let next: Record<string, ToolStreamOutput> | null = null;
  for (const toolCallId of toolCallIds) {
    if (!(toolCallId in outputs)) {
      continue;
    }
    next ??= { ...outputs };
    delete next[toolCallId];
  }
  return next ?? outputs;
}

const ToolStreamingContext = createContext<ToolStreamingContextValue>({
  state: { outputs: {} },
  updateToolStream: () => {
    /* noop */
  },
  clearToolStream: () => {
    /* noop */
  },
});

export function ToolStreamingProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<ToolStreamingState>({ outputs: {} });

  const updateToolStream = useCallback(
    (toolCallId: string, output: ToolStreamOutput | null) => {
      setState((prev) => {
        const next = applyToolStreamUpdate(prev.outputs, toolCallId, output);
        return next === prev.outputs ? prev : { outputs: next };
      });
    },
    [],
  );

  const clearToolStream = useCallback((toolCallIds: Iterable<string>) => {
    setState((prev) => {
      const next = clearToolStreamState(prev.outputs, toolCallIds);
      return next === prev.outputs ? prev : { outputs: next };
    });
  }, []);

  return (
    <ToolStreamingContext.Provider
      value={{ state, updateToolStream, clearToolStream }}
    >
      {children}
    </ToolStreamingContext.Provider>
  );
}

export function useToolStreaming() {
  return useContext(ToolStreamingContext);
}

/**
 * Return the streaming output for a specific tool call, or ``null``.
 * Subtask cards call this with the tool_call_ids they are interested in
 * so that two parallel in-progress subtasks never render each other's output.
 */
export function useToolCallStream(
  toolCallId: string | undefined,
): ToolStreamOutput | null {
  const { state } = useToolStreaming();
  if (!toolCallId) {
    return null;
  }
  return state.outputs[toolCallId] ?? null;
}

/**
 * Return ``true`` while *any* tool is still streaming, keyed by its call id.
 */
export function useIsToolStreaming(toolCallId?: string): boolean {
  const { state } = useToolStreaming();
  if (toolCallId) {
    return state.outputs[toolCallId]?.isPartial === true;
  }
  return Object.values(state.outputs).some((o) => o.isPartial === true);
}
