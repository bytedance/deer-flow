export const CONVERSATION_REFERENCES_KWARG = "conversation_references";

/** A conversation the user attached to the next message. Display data only. */
export type ConversationReference = {
  threadId: string;
  title: string;
};

type ConversationReferenceMetadata = {
  thread_id: string;
  title: string;
};

export type ConversationReferencesMetadata = {
  [CONVERSATION_REFERENCES_KWARG]: ConversationReferenceMetadata[];
};

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Display-only metadata stored on the visible human message so the transcript
 * can show which conversations were attached. It grants nothing: read access
 * comes only from `conversation_references` in the run request context, which
 * the Gateway consumes at admission and never persists in the chat history.
 */
export function buildConversationReferenceMetadata(
  references: ConversationReference[],
): ConversationReferencesMetadata {
  return {
    [CONVERSATION_REFERENCES_KWARG]: references.map((reference) => ({
      thread_id: reference.threadId,
      title: reference.title,
    })),
  };
}

export function readConversationReferences(
  additionalKwargs: unknown,
): ConversationReference[] {
  if (!isObjectRecord(additionalKwargs)) {
    return [];
  }
  const raw = additionalKwargs[CONVERSATION_REFERENCES_KWARG];
  if (!Array.isArray(raw)) {
    return [];
  }
  const seen = new Set<string>();
  const references: ConversationReference[] = [];
  for (const entry of raw) {
    if (
      !isObjectRecord(entry) ||
      typeof entry.thread_id !== "string" ||
      entry.thread_id.length === 0 ||
      seen.has(entry.thread_id)
    ) {
      continue;
    }
    seen.add(entry.thread_id);
    references.push({
      threadId: entry.thread_id,
      title: typeof entry.title === "string" ? entry.title : "",
    });
  }
  return references;
}
