import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { computeNextSubtask, subtaskNotification } from "./subtask-update";
import type { Subtask } from "./types";

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  // Always mirrors the latest `tasks` (updated during render). `updateSubtask`
  // reads/writes through this instead of a closure snapshot so async callers
  // (e.g. a late-resolving backfill) merge into current state, not stale state.
  tasksRef: React.RefObject<Record<string, Subtask>>;
  setTasks: (tasks: Record<string, Subtask>) => void;
}

export const SubtaskContext = createContext<SubtaskContextValue>({
  tasks: {},
  tasksRef: { current: {} },
  setTasks: () => {
    /* noop */
  },
});

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  const tasksRef = useRef(tasks);
  // Keep the ref pointing at the freshest state on every render so reads in
  // async callbacks (backfill `.then`) never see a stale map.
  tasksRef.current = tasks;
  return (
    <SubtaskContext.Provider value={{ tasks, tasksRef, setTasks }}>
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
  const { tasksRef, setTasks } = useSubtaskContext();
  const shouldNotifyAfterRenderRef = useRef(false);
  // No deps: must run after every render to check the ref set during render.
  useEffect(() => {
    if (!shouldNotifyAfterRenderRef.current) {
      return;
    }
    shouldNotifyAfterRenderRef.current = false;
    setTasks({ ...tasksRef.current });
  });

  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      // Read the *latest* state via the ref, never a `tasks` snapshot captured in
      // this callback's closure. Without this, an in-flight
      // fetchSubtaskSteps().then(updateSubtask) resolving late would write a stale
      // map, clobbering SSE steps/status and sibling subtasks added meanwhile (#3779).
      const current = tasksRef.current;
      const { next, becameTerminal, changed } = computeNextSubtask(
        current[task.id],
        task,
      );

      current[task.id] = next;

      // Gate on an actual state change, not mere field presence. The terminal
      // ToolMessage is re-parsed on every MessageList render and always carries
      // modelName/usage, so a presence check would setTasks({...}) with a fresh
      // reference each render — an infinite loop. `subtaskNotification` routes a
      // terminal transition through the deferred (after-render) path and skips
      // no-op re-parses entirely.
      const notify = subtaskNotification(task, { becameTerminal, changed });
      if (notify === "eager") {
        setTasks({ ...current });
      } else if (notify === "deferred") {
        shouldNotifyAfterRenderRef.current = true;
      }
    },
    [tasksRef, setTasks],
  );

  return updateSubtask;
}
