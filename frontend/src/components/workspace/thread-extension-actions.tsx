"use client";

import type { AgentThread } from "@/core/threads/types";

import { ConversationExtensionActions } from "./conversation-extension-actions";
import { useThread } from "./messages/context";

export function ThreadExtensionActions({ threadId }: { threadId: string }) {
  const { thread } = useThread();
  const agentThread = {
    thread_id: threadId,
    updated_at: new Date().toISOString(),
    values: thread.values,
  } as AgentThread;
  return (
    <ConversationExtensionActions
      context={{ thread: agentThread, messages: thread.messages }}
    />
  );
}
