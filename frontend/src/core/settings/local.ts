import type {
  AgentThreadContext,
  KnowledgeBaseSelection,
} from "../threads";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
  },
  onboarding: {
    industrialCompleted: false,
    industrialOperations: [],
  },
};

export const LOCAL_SETTINGS_KEY = "deerflow.local-settings";
export const THREAD_MODEL_KEY_PREFIX = "deerflow.thread-model.";
export const THREAD_KB_KEY_PREFIX = "deerflow.thread-kb.";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    | "thread_id"
    | "is_plan_mode"
    | "thinking_enabled"
    | "subagent_enabled"
    | "model_name"
    | "reasoning_effort"
  > & {
    model_name?: string | undefined;
    mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
    knowledge_base_selection?: KnowledgeBaseSelection;
  };
  onboarding: {
    industrialCompleted: boolean;
    industrialOperations: string[];
  };
}

export function mergeLocalSettings(settings?: Partial<LocalSettings>): LocalSettings {
  return {
    ...DEFAULT_LOCAL_SETTINGS,
    context: {
      ...DEFAULT_LOCAL_SETTINGS.context,
      ...settings?.context,
    },
    notification: {
      ...DEFAULT_LOCAL_SETTINGS.notification,
      ...settings?.notification,
    },
    onboarding: {
      ...DEFAULT_LOCAL_SETTINGS.onboarding,
      ...settings?.onboarding,
    },
  };
}

function getThreadModelStorageKey(threadId: string): string {
  return `${THREAD_MODEL_KEY_PREFIX}${threadId}`;
}

export function getThreadModelName(threadId: string): string | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  return localStorage.getItem(getThreadModelStorageKey(threadId)) ?? undefined;
}

export function saveThreadModelName(
  threadId: string,
  modelName: string | undefined,
) {
  if (!isBrowser()) {
    return;
  }
  const key = getThreadModelStorageKey(threadId);
  if (!modelName) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, modelName);
}

export function applyThreadModelOverride(
  settings: LocalSettings,
  threadModelName: string | undefined,
): LocalSettings {
  if (!threadModelName) {
    return settings;
  }
  return {
    ...settings,
    context: {
      ...settings.context,
      model_name: threadModelName,
    },
  };
}

function getThreadKBStorageKey(threadId: string): string {
  return `${THREAD_KB_KEY_PREFIX}${threadId}`;
}

export function getThreadKBSelection(
  threadId: string,
): KnowledgeBaseSelection | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  const json = localStorage.getItem(getThreadKBStorageKey(threadId));
  if (!json) return undefined;
  try {
    return JSON.parse(json) as KnowledgeBaseSelection;
  } catch {
    return undefined;
  }
}

export function saveThreadKBSelection(
  threadId: string,
  selection: KnowledgeBaseSelection | undefined,
) {
  if (!isBrowser()) {
    return;
  }
  const key = getThreadKBStorageKey(threadId);
  if (!selection?.enabled) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, JSON.stringify(selection));
}

export function applyThreadKBOverride(
  settings: LocalSettings,
  kbSelection: KnowledgeBaseSelection | undefined,
): LocalSettings {
  if (!kbSelection) {
    return settings;
  }
  return {
    ...settings,
    context: {
      ...settings.context,
      knowledge_base_selection: kbSelection,
    },
  };
}

export function getLocalSettings(): LocalSettings {
  if (!isBrowser()) {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json) as Partial<LocalSettings>;
      return mergeLocalSettings(settings);
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

export function saveLocalSettings(settings: LocalSettings) {
  if (!isBrowser()) {
    return;
  }
  localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
}
