import { createContext, useCallback, useContext, useRef, useState } from "react";

import type { Subtask } from "./types";

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
  const pendingRef = useRef<Partial<Subtask> & { id: string } | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushPending = useCallback(() => {
    if (!pendingRef.current) return;
    const task = pendingRef.current;
    pendingRef.current = null;
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    const existing = tasks[task.id];
    const merged = { ...existing, ...task } as Subtask;
    // Only re-render if values actually changed
    if (existing?.latestMessage !== merged.latestMessage || existing?.status !== merged.status) {
      const newTasks = { ...tasks, [task.id]: merged };
      setTasks(newTasks);
    }
  }, [tasks, setTasks]);

  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      // Always update the pending ref (last write wins)
      pendingRef.current = { ...pendingRef.current, ...task } as Partial<Subtask> & { id: string };

      // Clear any existing flush timer
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      // Use 50ms debounce to batch rapid updates
      timeoutRef.current = setTimeout(flushPending, 50);
    },
    [flushPending],
  );

  return updateSubtask;
}
