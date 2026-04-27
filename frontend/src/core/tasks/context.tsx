import type { AIMessage } from "@langchain/langgraph-sdk";
import { createContext, useCallback, useContext, useState } from "react";

import type { Subtask } from "./types";

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: React.Dispatch<React.SetStateAction<Record<string, Subtask>>>;
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
  const { setTasks } = useSubtaskContext();
  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      setTasks((prev) => {
        const current = prev[task.id];
        const updated = { ...current, ...task } as Subtask;
        return { ...prev, [task.id]: updated };
      });
    },
    [setTasks],
  );
  return updateSubtask;
}

export function useAppendMessage() {
  const { setTasks } = useSubtaskContext();
  const appendMessage = useCallback(
    (taskId: string, message: AIMessage) => {
      setTasks((prev) => {
        const current = prev[taskId];
        if (!current) return prev;
        const history = [...(current.messageHistory ?? [])];
        if (history.some((m) => m.id === message.id)) return prev;
        history.push(message);
        return { ...prev, [taskId]: { ...current, messageHistory: history } };
      });
    },
    [setTasks],
  );
  return appendMessage;
}
