import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import type { Subtask } from "./types";

function isTerminalSubtaskStatus(status: Subtask["status"] | undefined) {
  return status === "completed" || status === "failed";
}

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: (tasks: Record<string, Subtask>) => void;
}

export const SubtaskContext = createContext<SubtaskContextValue>({
  tasks: {},
  setTasks: () => {
    /* noop */
  },
});

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  return (
    <SubtaskContext.Provider value={{ tasks, setTasks }}>
      {children}
    </SubtaskContext.Provider>
  );
}

export function useSubtaskContext() {
  const context = useContext(SubtaskContext);
  if (context === undefined) {
    throw new Error(
      "useSubtaskContext must be used within a SubtaskContext.Provider",
    );
  }
  return context;
}

export function useSubtask(id: string) {
  const { tasks } = useSubtaskContext();
  return tasks[id];
}

export function useUpdateSubtask() {
  const { tasks, setTasks } = useSubtaskContext();
  const shouldNotifyAfterRenderRef = useRef(false);
  // No deps: must run after every render to check the ref set during render.
  useEffect(() => {
    if (!shouldNotifyAfterRenderRef.current) {
      return;
    }
    shouldNotifyAfterRenderRef.current = false;
    setTasks({ ...tasks });
  });

  const updateSubtask = useCallback(
    (
      task: Partial<Subtask> & {
        id: string;
        latestMessageIndex?: number;
      },
    ) => {
      const previous = tasks[task.id];
      const previousStatus = previous?.status;
      // MessageList writes the pending task tool-call state before parsing the
      // matching ToolMessage in the same render. Keep terminal results stable
      // across the next render so the refresh notification does not loop.
      //
      // Exclude messageHistory / seenMessageIndices / latestMessageIndex from
      // the spread: they are managed separately below so that accumulated
      // intermediate messages survive re-renders.
      const {
        messageHistory: _ignoredHistory,
        seenMessageIndices: _ignoredIndices,
        latestMessageIndex,
        ...taskWithoutHistory
      } = task;
      const next = {
        ...previous,
        ...taskWithoutHistory,
        ...(task.status === "in_progress" &&
        isTerminalSubtaskStatus(previousStatus)
          ? { status: previousStatus }
          : {}),
      } as Subtask;

      // Accumulate intermediate messages so the subtask card can show the
      // full execution history instead of only the latest step.
      //
      // The stream re-emits `task_running` events on reconnect — see
      // `reconnectOnMount: true` + `streamResumable: true` on the useStream
      // call — so we deduplicate before appending. Identity is resolved in
      // this priority order:
      //   1. `AIMessage.id` if present (stable across re-emits).
      //   2. `message_index` from the backend (1-based, monotonic per task).
      //   3. Reference equality (rare same-session id-less repeats).
      const history = previous?.messageHistory ?? [];
      const seenIndices = previous?.seenMessageIndices ?? [];
      if (task.latestMessage) {
        const incoming = task.latestMessage;
        const incomingIndex = latestMessageIndex;
        let isDuplicate = false;
        if (incoming.id) {
          isDuplicate = history.some((m) => m.id === incoming.id);
        } else if (incomingIndex !== undefined) {
          isDuplicate = seenIndices.includes(incomingIndex);
        } else {
          isDuplicate = history.some((m) => m === incoming);
        }
        if (isDuplicate) {
          next.messageHistory = history;
          next.seenMessageIndices = seenIndices;
        } else {
          next.messageHistory = [...history, incoming];
          next.seenMessageIndices =
            incomingIndex !== undefined
              ? [...seenIndices, incomingIndex]
              : seenIndices;
        }
      } else {
        next.messageHistory = history;
        next.seenMessageIndices = seenIndices;
      }

      const becameTerminal =
        isTerminalSubtaskStatus(next.status) && previousStatus !== next.status;

      tasks[task.id] = next;

      if (task.latestMessage) {
        setTasks({ ...tasks });
      } else if (becameTerminal) {
        shouldNotifyAfterRenderRef.current = true;
      }
    },
    [tasks, setTasks],
  );

  return updateSubtask;
}
