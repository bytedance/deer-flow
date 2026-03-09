import type { Message } from "@langchain/langgraph-sdk";


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

export function titleOfThread(thread: { values?: { title?: string | null } | null }) {
  return thread.values?.title ?? "Untitled";
}
