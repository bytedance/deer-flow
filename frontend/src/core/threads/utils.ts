import type { Message } from "@langchain/langgraph-sdk";

import type { AgentThread, AgentThreadState } from "./types";

export function pathOfThread(threadId: string) {
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

export function notificationBodyOfThread(
  state: AgentThreadState,
  fallback = "New message received",
) {
  const body = fallback;
  const lastMessage = state.messages.at(-1);
  if (!lastMessage) {
    return body;
  }

  const textContent = textOfMessage(lastMessage);
  if (!textContent) {
    return body;
  }

  return textContent.length > 200
    ? textContent.substring(0, 200) + "..."
    : textContent;
}
