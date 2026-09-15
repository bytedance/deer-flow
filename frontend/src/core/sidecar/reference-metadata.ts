import type { SidecarContext, SidecarContextRole } from "./context";

export type ReferenceMessageContextMetadata = {
  label: string;
  message_id?: string;
  role: SidecarContextRole;
  content: string;
};

export type ReferenceMessageMetadata = {
  referenced_message_count: number;
  referenced_message_ids: string[];
  referenced_message_roles: SidecarContextRole[];
  referenced_message_contexts: ReferenceMessageContextMetadata[];
};

function isSidecarContextRole(value: unknown): value is SidecarContextRole {
  return value === "user" || value === "assistant";
}

export function buildReferenceMessageMetadata(
  contexts: SidecarContext[],
): ReferenceMessageMetadata {
  // `referenced_message_count`, `referenced_message_ids`, and
  // `referenced_message_roles` are kept 1:1 parallel with `contexts` so
  // consumers can safely zip them. Do not dedupe ids here: two fragments of the
  // same source message would otherwise leave the arrays non-parallel.
  return {
    referenced_message_count: contexts.length,
    referenced_message_ids: contexts.map((context) => context.messageId ?? ""),
    referenced_message_roles: contexts.map((context) => context.role),
    referenced_message_contexts: contexts.map((context) => ({
      label: context.label,
      ...(context.messageId ? { message_id: context.messageId } : {}),
      role: context.role,
      content: context.content,
    })),
  };
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function readReferenceMessageContexts(
  additionalKwargs: unknown,
): SidecarContext[] {
  if (!isObjectRecord(additionalKwargs)) {
    return [];
  }

  const rawContexts = additionalKwargs.referenced_message_contexts;
  if (!Array.isArray(rawContexts)) {
    return [];
  }

  return rawContexts.flatMap((rawContext) => {
    if (
      !isObjectRecord(rawContext) ||
      typeof rawContext.label !== "string" ||
      typeof rawContext.content !== "string" ||
      !isSidecarContextRole(rawContext.role)
    ) {
      return [];
    }

    return [
      {
        type: "referenced_message",
        label: rawContext.label,
        ...(typeof rawContext.message_id === "string"
          ? { messageId: rawContext.message_id }
          : {}),
        role: rawContext.role,
        content: rawContext.content,
      },
    ];
  });
}
