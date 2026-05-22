import type { AIMessage } from "@langchain/langgraph-sdk";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

/**
 * Bytedance/deer-flow issue #3147: the `task` subtask state used to live
 * entirely on a mutable React context — `MessageList` wrote into it
 * during render and `SubtaskCard` read it back through `useSubtask`.
 * Render-time mutation broke React 19 Strict Mode and hid card lifecycle
 * regressions because only the SSE-driven `latestMessage` path actually
 * called `setState`.
 *
 * The new shape splits responsibilities by data origin:
 *
 * 1. **Base fields** (`status` / `result` / `error` / `description` / ...)
 *    are derived from the thread's message list with
 *    `buildSubtaskMapFromMessages(messages)` and passed to `SubtaskCard`
 *    directly as a `task` prop. They no longer round-trip through the
 *    context, so the first render after a new message arrives is already
 *    correct — no `useEffect` lag, no `!`-asserted undefined.
 *
 * 2. **Latest streaming AIMessage** comes from the `task_running` custom
 *    SSE event handled in `useThreadStream`. That handler fires outside
 *    React render, so writing to context state there is safe. The
 *    Provider in this file owns that map and `SubtaskCard` reads it via
 *    `useLatestSubtaskMessage(taskId)`.
 */
interface LatestMessageContextValue {
  latestMessages: Record<string, AIMessage>;
  setLatestMessage: (taskId: string, message: AIMessage) => void;
}

const LatestMessageContext = createContext<
  LatestMessageContextValue | undefined
>(undefined);

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [latestMessages, setLatestMessages] = useState<
    Record<string, AIMessage>
  >({});

  const setLatestMessage = useCallback((taskId: string, message: AIMessage) => {
    setLatestMessages((prev) =>
      prev[taskId] === message ? prev : { ...prev, [taskId]: message },
    );
  }, []);

  const value = useMemo<LatestMessageContextValue>(
    () => ({ latestMessages, setLatestMessage }),
    [latestMessages, setLatestMessage],
  );

  return (
    <LatestMessageContext.Provider value={value}>
      {children}
    </LatestMessageContext.Provider>
  );
}

function useLatestMessageContext(): LatestMessageContextValue {
  const context = useContext(LatestMessageContext);
  if (context === undefined) {
    throw new Error(
      "useLatestMessageContext must be used within a SubtasksProvider",
    );
  }
  return context;
}

/** Read the latest `task_running` AIMessage emitted for *taskId*, or `undefined`. */
export function useLatestSubtaskMessage(taskId: string): AIMessage | undefined {
  return useLatestMessageContext().latestMessages[taskId];
}

/**
 * Register the latest streaming AIMessage for a task. Call this from a
 * stream event handler (e.g. `onCustomEvent`), not from render.
 */
export function useUpdateLatestMessage(): (
  taskId: string,
  message: AIMessage,
) => void {
  return useLatestMessageContext().setLatestMessage;
}
