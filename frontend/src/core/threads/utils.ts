import type { Message } from "@langchain/langgraph-sdk";

import type { AgentThread, AgentThreadContext } from "./types";

type ThreadRouteTarget =
  | string
  | Pick<AgentThread, "thread_id" | "context">
  | {
      thread_id: string;
      context?: Pick<AgentThreadContext, "agent_name"> | null;
    };

export function pathOfThread(
  thread: ThreadRouteTarget,
  context?: Pick<AgentThreadContext, "agent_name"> | null,
) {
  const threadId = typeof thread === "string" ? thread : thread.thread_id;
  const agentName =
    typeof thread === "string"
      ? context?.agent_name
      : thread.context?.agent_name;

  return agentName
    ? `/workspace/agents/${encodeURIComponent(agentName)}/chats/${threadId}`
    : `/workspace/chats/${threadId}`;
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
