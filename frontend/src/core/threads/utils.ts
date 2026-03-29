import type { Message } from "@langchain/langgraph-sdk";

import type { AgentThreadWithExtractedTitle } from "./types";

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

export function titleOfThread(thread: AgentThreadWithExtractedTitle) {
  if (
    thread.extracted &&
    typeof thread.extracted.title === "string" &&
    thread.extracted.title.trim()
  ) {
    return thread.extracted.title;
  }
  return thread.values?.title ?? "Untitled";
}
