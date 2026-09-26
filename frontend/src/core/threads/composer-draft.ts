const COMPOSER_DRAFT_VERSION = 1;
const COMPOSER_DRAFT_PREFIX = "deerflow:composer-draft:v1";

export type ComposerDraft = {
  text: string;
  skillName: string | null;
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
    };
    if (
      parsed.version !== COMPOSER_DRAFT_VERSION ||
      typeof parsed.text !== "string" ||
      !(parsed.skillName === null || typeof parsed.skillName === "string")
    ) {
      return null;
    }

    return {
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
    if (!draft.text && !draft.skillName) {
      storage.removeItem(key);
      return;
    }

    storage.setItem(
      key,
      JSON.stringify({
        version: COMPOSER_DRAFT_VERSION,
        text: draft.text,
        skillName: draft.skillName,
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

export function resolveComposerDraft(
  draft: ComposerDraft,
  enabledSkillNames: ReadonlySet<string>,
): ComposerDraft {
  if (!draft.skillName || enabledSkillNames.has(draft.skillName)) {
    return draft;
  }

  return {
    text: `/${draft.skillName}${draft.text ? ` ${draft.text}` : ""}`,
    skillName: null,
  };
}
