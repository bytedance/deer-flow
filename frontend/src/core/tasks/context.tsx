import type { AIMessage } from "@langchain/langgraph-sdk";
import { createContext, useCallback, useContext, useState } from "react";

export interface SubtaskContextValue {
  latestMessages: Record<string, AIMessage>;
  setLatestMessages: React.Dispatch<
    React.SetStateAction<Record<string, AIMessage>>
  >;
}

export const SubtaskContext = createContext<SubtaskContextValue>({
  latestMessages: {},
  setLatestMessages: () => {
    /* noop */
  },
});

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [latestMessages, setLatestMessages] = useState<Record<string, AIMessage>>(
    {},
  );
  return (
    <SubtaskContext.Provider value={{ latestMessages, setLatestMessages }}>
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

export function useLatestSubtaskMessage(id: string) {
  const { latestMessages } = useSubtaskContext();
  return latestMessages[id];
}

export function useUpdateLatestMessage() {
  const { setLatestMessages } = useSubtaskContext();
  const updateLatestMessage = useCallback(
    (taskId: string, message: AIMessage) => {
      setLatestMessages((current) => ({
        ...current,
        [taskId]: message,
      }));
    },
    [setLatestMessages],
  );
  return updateLatestMessage;
}
