import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { mergeSteps } from "./steps";
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
    (task: Partial<Subtask> & { id: string }) => {
      const previous = tasks[task.id];
      const previousStatus = previous?.status;
      // MessageList writes the pending task tool-call state before parsing the
      // matching ToolMessage in the same render. Keep terminal results stable
      // across the next render so the refresh notification does not loop.
      const next = {
        ...previous,
        ...task,
        ...(task.status === "in_progress" &&
        isTerminalSubtaskStatus(previousStatus)
          ? { status: previousStatus }
          : {}),
      } as Subtask;

      // `steps` carries deltas to accumulate, not a replacement: merge them into
      // the existing history (deduped/ordered by message_index) so live SSE steps
      // and fetched-on-expand steps build one timeline (#3779).
      if (task.steps) {
        next.steps = mergeSteps(previous?.steps ?? [], task.steps);
      }

      const becameTerminal =
        isTerminalSubtaskStatus(next.status) && previousStatus !== next.status;

      tasks[task.id] = next;

      if (task.latestMessage || task.steps) {
        setTasks({ ...tasks });
      } else if (becameTerminal) {
        shouldNotifyAfterRenderRef.current = true;
      }
    },
    [tasks, setTasks],
  );

  return updateSubtask;
}
