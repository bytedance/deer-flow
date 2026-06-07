import { createContext, useCallback, useContext, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { Subtask } from "./types";

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: Dispatch<SetStateAction<Record<string, Subtask>>>;
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

export function mergeSubtaskUpdate(
  tasks: Record<string, Subtask>,
  task: Partial<Subtask> & { id: string },
): Record<string, Subtask> {
  const current = tasks[task.id];
  const next = { ...current, ...task } as Subtask;
  const unchanged =
    current !== undefined &&
    Object.entries(next).every(
      ([key, value]) => current[key as keyof Subtask] === value,
    ) &&
    Object.keys(current).length === Object.keys(next).length;

  if (unchanged) {
    return tasks;
  }

  return {
    ...tasks,
    [task.id]: next,
  };
}

export function useUpdateSubtask() {
  const { setTasks } = useSubtaskContext();
  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      setTasks((tasks) => mergeSubtaskUpdate(tasks, task));
    },
    [setTasks],
  );
  return updateSubtask;
}
