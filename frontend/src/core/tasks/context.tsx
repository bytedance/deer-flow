import type { Message } from "@langchain/langgraph-sdk";
import { createContext, useCallback, useContext, useRef, useState } from "react";

import type { Subtask } from "./types";

/** Extra fields accepted by updateSubtask but not stored in the Subtask record */
export interface SubtaskUpdateExtras {
  /** A trajectory message (AI or tool) to push into messageHistory */
  _trajectoryMessage?: Message;
}

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: (tasks: Record<string, Subtask>) => void;
  selectedTaskId: string | null;
  setSelectedTaskId: (id: string | null) => void;
}

export const SubtaskContext = createContext<SubtaskContextValue>({
  tasks: {},
  setTasks: () => {
    /* noop */
  },
  selectedTaskId: null,
  setSelectedTaskId: () => {
    /* noop */
  },
});

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  return (
    <SubtaskContext.Provider
      value={{ tasks, setTasks, selectedTaskId, setSelectedTaskId }}
    >
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
  // Use ref to always read latest tasks without making updateSubtask unstable
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;

  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string } & SubtaskUpdateExtras) => {
      const currentTasks = tasksRef.current;
      const existing = currentTasks[task.id];
      // Strip extra fields before merging into the stored record
      const { _trajectoryMessage, ...taskFields } = task;
      const merged = { ...existing, ...taskFields } as Subtask;

      // Preserve live runtime fields when task metadata is re-synced from thread
      // messages (which may only carry static args and no streaming progress).
      if (existing && !task.latestMessage) {
        if ((task.messageHistory?.length ?? 0) === 0 && existing.messageHistory) {
          merged.messageHistory = existing.messageHistory;
        }
        if ((task.messageIndex ?? 0) === 0 && (existing.messageIndex ?? 0) > 0) {
          merged.messageIndex = existing.messageIndex;
        }
        if ((task.totalMessages ?? 0) === 0 && (existing.totalMessages ?? 0) > 0) {
          merged.totalMessages = existing.totalMessages;
        }
        if (existing.latestMessage != null && task.latestMessage === undefined) {
          merged.latestMessage = existing.latestMessage;
        }
      }

      // Accumulate messageHistory when a new trajectory message arrives.
      // _trajectoryMessage is the primary source (supports both AI and tool messages).
      // Falls back to latestMessage for backward compatibility.
      const messageToAccumulate = _trajectoryMessage ?? task.latestMessage;
      if (messageToAccumulate) {
        const history = existing?.messageHistory ?? [];
        const lastHistory = history[history.length - 1];
        const incomingId = messageToAccumulate.id;
        const lastHistoryId = lastHistory?.id;
        const incomingIndex = task.messageIndex ?? 0;
        const existingIndex = existing?.messageIndex ?? 0;

        // Prefer stable message IDs. If IDs are absent (common in LangChain AIMessage
        // dumps), fall back to message index to avoid dropping all history entries.
        let isDuplicate = false;
        if (incomingId) {
          isDuplicate = incomingId === lastHistoryId;
        } else if (incomingIndex > 0) {
          isDuplicate = existingIndex >= incomingIndex;
        }

        if (!isDuplicate) {
          merged.messageHistory = [...history, messageToAccumulate];
        } else {
          merged.messageHistory = history;
        }
      }

      // Prevent status downgrade (completed/failed → in_progress).
      // This happens when message-list.tsx re-creates tasks during re-render.
      if (
        existing &&
        (existing.status === "completed" || existing.status === "failed") &&
        merged.status === "in_progress"
      ) {
        merged.status = existing.status;
        if (existing.result !== undefined) merged.result = existing.result;
        if (existing.error !== undefined) merged.error = existing.error;
      }

      // Skip if no meaningful change (prevents infinite render loops
      // when called during render in message-list.tsx)
      if (
        existing?.status === merged.status &&
        existing?.description === merged.description &&
        existing?.subagent_type === merged.subagent_type &&
        existing?.prompt === merged.prompt &&
        existing?.messageIndex === merged.messageIndex &&
        existing?.result === merged.result &&
        existing?.error === merged.error &&
        !task.latestMessage &&
        !_trajectoryMessage
      ) {
        return;
      }

      const nextTasks = { ...currentTasks, [task.id]: merged };
      tasksRef.current = nextTasks;
      setTasks(nextTasks);
    },
    [setTasks],
  );
  return updateSubtask;
}

export function useSelectedSubtask() {
  const { tasks, selectedTaskId, setSelectedTaskId } = useSubtaskContext();
  return {
    selectedTask: selectedTaskId ? tasks[selectedTaskId] ?? null : null,
    selectedTaskId,
    setSelectedTaskId,
  };
}
