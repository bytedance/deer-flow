import type { BaseMessage } from "@langchain/core/messages";

import type { AgentThread } from "./types";

export function pathOfThread(threadId: string) {
  return `/workspace/chats/${threadId}`;
}

export function textOfMessage(message: BaseMessage) {
  if (typeof message.content === "string") {
    return message.content;
  } else if (Array.isArray(message.content)) {
    return message.content.find((part) => part.type === "text" && part.text)
      ?.text as string;
  }
  return null;
}

export function titleOfThread(thread: AgentThread) {
  if (thread.values && "title" in thread.values) {
    return thread.values.title;
  }
  return "Untitled";
}
