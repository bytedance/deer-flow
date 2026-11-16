import {
  readConversationReferences,
  type ConversationReference,
} from "@/core/conversation-references";

const COMPOSER_DRAFT_VERSION = 1;
const COMPOSER_DRAFT_PREFIX = "deerflow:composer-draft:v1";

export type ComposerDraft = {
  text: string;
  skillName: string | null;
  conversationReferences?: ConversationReference[];
};

export type ComposerDraftStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>;

export function getSessionComposerDraftStorage(): ComposerDraftStorage | null {
  try {
    if (typeof window === "undefined") {
      return null;
    }
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function buildComposerDraftKey({
  userId,
  agentName,
  threadId,
}: {
  userId: string;
  agentName?: string | null;
  threadId: string;
}) {
  return [
    COMPOSER_DRAFT_PREFIX,
    encodeURIComponent(userId ? userId : "anonymous"),
    encodeURIComponent(agentName ?? "lead-agent"),
    encodeURIComponent(threadId),
  ].join(":");
}

export function readComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  key: string,
): ComposerDraft | null {
  try {
    if (!storage) {
      return null;
    }
    const raw = storage.getItem(key);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as {
      version?: unknown;
      text?: unknown;
      skillName?: unknown;
      conversationReferences?: unknown;
    };
    if (
      parsed.version !== COMPOSER_DRAFT_VERSION ||
      typeof parsed.text !== "string" ||
      !(parsed.skillName === null || typeof parsed.skillName === "string")
    ) {
      return null;
    }

    const references = Array.isArray(parsed.conversationReferences)
      ? readConversationReferences({
          conversation_references: parsed.conversationReferences.map(
            (item: unknown) => {
              if (!item || typeof item !== "object") return null;
              const value = item as Record<string, unknown>;
              return {
                thread_id: value.threadId,
                title: value.title,
                agent_name: value.agentName,
              };
            },
          ),
        })
      : [];
    return {
      ...(references.length ? { conversationReferences: references } : {}),
      text: parsed.text,
      skillName: parsed.skillName,
    };
  } catch {
    return null;
  }
}

export function writeComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  key: string,
  draft: ComposerDraft,
) {
  try {
    if (!storage) {
      return;
    }
    if (
      !draft.text &&
      !draft.skillName &&
      !draft.conversationReferences?.length
    ) {
      storage.removeItem(key);
      return;
    }

    storage.setItem(
      key,
      JSON.stringify({
        version: COMPOSER_DRAFT_VERSION,
        text: draft.text,
        skillName: draft.skillName,
        ...(draft.conversationReferences?.length
          ? { conversationReferences: draft.conversationReferences }
          : {}),
      }),
    );
  } catch {
    // Browser storage can be disabled or full; drafting must keep working.
  }
}

export function clearComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  key: string,
) {
  try {
    if (!storage) {
      return;
    }
    storage.removeItem(key);
  } catch {
    // Browser storage can be disabled; sending must keep working.
  }
}

/**
 * Clear a stored draft only while it still holds the text that was sent.
 * A send can be dispatched after its composer is gone, by which time another
 * composer may have saved a different draft under the same key.
 */
export function retireSentComposerDraft(
  storage: ComposerDraftStorage | null | undefined,
  key: string,
  sentTexts: readonly string[],
) {
  const stored = readComposerDraft(storage, key);
  if (stored && (stored.skillName || !sentTexts.includes(stored.text))) {
    return;
  }
  clearComposerDraft(storage, key);
}

export function resolveComposerDraft(
  draft: ComposerDraft,
  enabledSkillNames: ReadonlySet<string>,
): ComposerDraft {
  if (!draft.skillName || enabledSkillNames.has(draft.skillName)) {
    return draft;
  }

  return {
    ...draft,
    text: `/${draft.skillName}${draft.text ? ` ${draft.text}` : ""}`,
    skillName: null,
  };
}
