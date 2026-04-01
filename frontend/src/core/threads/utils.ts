import type { Message } from "@langchain/langgraph-sdk";

import type { AgentThread } from "./types";

export function pathOfThread(threadId: string, agentName?: string | null) {
  if (agentName) {
    return `/workspace/agents/${agentName}/chats/${threadId}`;
  }
  return `/workspace/chats/${threadId}`;
}

export function textOfMessage(message: Message) {
  if (typeof message.content === "string") {
    return message.content;
  } else if (Array.isArray(message.content)) {
    for (const part of message.content) {
      if (part.type === "text") {
        return part.text;
      }
    }
  }
  return null;
}

export function titleOfThread(thread: AgentThread) {
  return thread.values?.title ?? "Untitled";
}
