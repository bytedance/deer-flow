import type { Message } from "@langchain/langgraph-sdk";

import type {
  AgentThread,
  AgentThreadContext,
  ThreadBranchMetadata,
} from "./types";

type ThreadRouteTarget =
  | string
  | {
      thread_id: string;
      context?: Pick<AgentThreadContext, "agent_name"> | null;
      metadata?: Record<string, unknown> | null;
    };

function normalizeCustomAgentName(agentName: string | null | undefined) {
  if (typeof agentName !== "string") {
    return undefined;
  }

  const normalized = agentName.trim();
  if (!normalized || normalized === "default") {
    return undefined;
  }

  return normalized;
}

function resolveRouteAgentName(
  thread: ThreadRouteTarget,
  context?: Pick<AgentThreadContext, "agent_name"> | string | null,
) {
  if (typeof thread === "string") {
    return normalizeCustomAgentName(
      typeof context === "string" ? context : context?.agent_name,
    );
  }

  const contextAgentName = normalizeCustomAgentName(thread.context?.agent_name);
  if (contextAgentName) {
    return contextAgentName;
  }

  const metadataAgentName =
    typeof thread.metadata?.agent_name === "string"
      ? normalizeCustomAgentName(thread.metadata.agent_name)
      : undefined;
  if (metadataAgentName) {
    return metadataAgentName;
  }

  return normalizeCustomAgentName(
    typeof context === "string" ? context : context?.agent_name,
  );
}

export function pathOfThread(
  thread: ThreadRouteTarget,
  context?: Pick<AgentThreadContext, "agent_name"> | string | null,
) {
  const threadId = typeof thread === "string" ? thread : thread.thread_id;
  const routeAgentName = resolveRouteAgentName(thread, context);
  if (routeAgentName) {
    return `/workspace/agents/${encodeURIComponent(routeAgentName)}/chats/${threadId}`;
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

export function agentNameOfThreadMetadata(
  metadata: ThreadBranchMetadata | null | undefined,
) {
  return normalizeCustomAgentName(metadata?.agent_name);
}

export function isBranchThreadMetadata(
  metadata: ThreadBranchMetadata | null | undefined,
) {
  return metadata?.branch_role === "branch";
}
