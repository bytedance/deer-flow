import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { createContext, useContext } from "react";

import type { AgentThreadState } from "@/core/threads";

export interface ThreadContextType {
  thread: BaseStream<AgentThreadState>;
  editHumanMessage: (
    threadId: string,
    messageId: string,
    text: string,
  ) => Promise<void>;
  regenerateTurn: (threadId: string, messageId: string) => Promise<void>;
  selectAssistantVersion: (
    threadId: string,
    messageId: string,
    versionId: string,
  ) => Promise<void>;
  stopThread: () => Promise<void>;
  isThreadStreaming: boolean;
  isMock?: boolean;
}

export const ThreadContext = createContext<ThreadContextType | undefined>(
  undefined,
);

export function useThread() {
  const context = useContext(ThreadContext);
  if (context === undefined) {
    throw new Error("useThread must be used within a ThreadContext");
  }
  return context;
}
