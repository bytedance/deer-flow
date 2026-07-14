import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import type { ToolStreamOutput } from "./types";

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
}

const ToolStreamingContext = createContext<ToolStreamingContextValue>({
  state: { outputs: {} },
  updateToolStream: () => {
    /* noop */
  },
});

export function ToolStreamingProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<ToolStreamingState>({ outputs: {} });
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const updateToolStream = useCallback(
    (toolCallId: string, output: ToolStreamOutput | null) => {
      setState((prev) => {
        if (output === null) {
          // Remove this tool's entry from the map.
          if (!(toolCallId in prev.outputs)) {
            return prev;
          }
          const next = { ...prev.outputs };
          delete next[toolCallId];
          return { outputs: next };
        }
        const existing = prev.outputs[toolCallId];
        // If a late partial chunk arrives for a call that already received its
        // final output, drop it — the completed entry must not regress.
        if (existing && output.isPartial && !existing.isPartial) {
          return prev;
        }
        // Accumulate partial chunks so the streaming preview grows with each
        // intermediate dispatch rather than flashing the last fragment only.
        if (existing && output.isPartial && existing.isPartial) {
          return {
            outputs: {
              ...prev.outputs,
              [toolCallId]: {
                ...existing,
                text: existing.text + output.text,
                isPartial: true,
              },
            },
          };
        }
        return {
          outputs: { ...prev.outputs, [toolCallId]: output },
        };
      });
    },
    [],
  );

  return (
    <ToolStreamingContext.Provider value={{ state, updateToolStream }}>
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
