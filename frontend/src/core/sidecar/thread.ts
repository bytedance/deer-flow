import type { AgentThread } from "@/core/threads";

import { normalizeSidecarContexts, type SidecarContext } from "./context";

export const SIDECAR_METADATA_KEY = "deerflow_sidecar";

export type SidecarThreadMetadata = {
  [SIDECAR_METADATA_KEY]: true;
  parent_thread_id: string;
  sidecar_context_type: SidecarContext["type"];
  sidecar_context_label: string;
  sidecar_context_count: number;
  referenced_message_id?: string;
  referenced_message_ids: string[];
  referenced_message_role: SidecarContext["role"];
  referenced_message_roles: SidecarContext["role"][];
};

export function buildSidecarThreadMetadata(
  parentThreadId: string,
  contextOrContexts: SidecarContext | SidecarContext[],
): SidecarThreadMetadata {
  const contexts = normalizeSidecarContexts(contextOrContexts);
  const primaryContext = contexts[0];
  if (!primaryContext) {
    throw new Error("At least one sidecar context is required.");
  }

  // Keep `referenced_message_ids`, `referenced_message_roles`, and
  // `sidecar_context_count` 1:1 parallel with `contexts` so consumers can zip
  // them safely (two fragments of the same source message would otherwise make
  // a deduped id array shorter than the role array).
  const referencedMessageIds = contexts.map(
    (context) => context.messageId ?? "",
  );

  return {
    [SIDECAR_METADATA_KEY]: true,
    parent_thread_id: parentThreadId,
    sidecar_context_type: primaryContext.type,
    sidecar_context_label: primaryContext.label,
    sidecar_context_count: contexts.length,
    referenced_message_id: primaryContext.messageId,
    referenced_message_ids: referencedMessageIds,
    referenced_message_role: primaryContext.role,
    referenced_message_roles: contexts.map((context) => context.role),
  };
}

export function isSidecarThread(
  thread:
    | Pick<AgentThread, "metadata">
    | { metadata?: Record<string, unknown> },
) {
  return thread.metadata?.[SIDECAR_METADATA_KEY] === true;
}

export function shouldShowInPrimaryThreadLists(
  thread:
    | Pick<AgentThread, "metadata">
    | { metadata?: Record<string, unknown> },
) {
  return !isSidecarThread(thread);
}
