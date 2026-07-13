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
  output: ToolStreamOutput | null;
}

export interface ToolStreamingContextValue {
  state: ToolStreamingState;
  updateToolStream: (output: ToolStreamOutput | null) => void;
}

const ToolStreamingContext = createContext<ToolStreamingContextValue>({
  state: { output: null },
  updateToolStream: () => {
    /* noop */
  },
});

export function ToolStreamingProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<ToolStreamingState>({ output: null });
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const updateToolStream = useCallback((output: ToolStreamOutput | null) => {
    setState((prev) => {
      // Don't replace a streaming output from a different tool with null
      // (a late-arriving start→final sequence could race).
      if (output === null && prev.output !== null) {
        return { output: null };
      }
      // When the same tool sends multiple updates, merge them.
      return { output };
    });
  }, []);

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
 * Hook that returns true while any tool is streaming output.
 * The subtask card uses this to show a streaming indicator.
 */
export function useIsToolStreaming(): boolean {
  const { state } = useToolStreaming();
  return state.output?.isPartial === true;
}
