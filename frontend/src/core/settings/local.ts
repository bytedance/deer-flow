import type { TokenUsageInlineMode } from "../messages/usage-model";
import type { AgentThreadContext } from "../threads";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  projectsDisplayMode: "flat",
  tokenUsage: {
    headerTotal: true,
    inlineMode: "per_turn",
  },
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
  },
};

export const LOCAL_SETTINGS_KEY = "deerflow.local-settings";
export const THREAD_MODEL_KEY_PREFIX = "deerflow.thread-model.";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/**
 * Best-effort localStorage facade.
 *
 * Safari private mode, Firefox strict containers, some embedded WebViews, and
 * quotas already filled by sibling tabs throw ``SecurityError`` or
 * ``QuotaExceededError`` from ``getItem``/``setItem``. Without a guard those
 * exceptions bubble into React render handlers and break the composer /
 * settings panel. This wrapper traps every storage exception so callers can
 * always fall back to a sane default.
 */
export const safeLocalStorage = {
  getItem(key: string): string | null {
    if (!isBrowser()) return null;
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string): boolean {
    if (!isBrowser()) return false;
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  },
  removeItem(key: string): boolean {
    if (!isBrowser()) return false;
    try {
      window.localStorage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  },
};

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  projectsDisplayMode: "flat" | "grouped";
  tokenUsage: {
    headerTotal: boolean;
    inlineMode: TokenUsageInlineMode;
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
  };
}

function mergeLocalSettings(settings?: Partial<LocalSettings>): LocalSettings {
  return {
    ...DEFAULT_LOCAL_SETTINGS,
    context: {
      ...DEFAULT_LOCAL_SETTINGS.context,
      ...settings?.context,
    },
    tokenUsage: {
      ...DEFAULT_LOCAL_SETTINGS.tokenUsage,
      ...settings?.tokenUsage,
    },
    notification: {
      ...DEFAULT_LOCAL_SETTINGS.notification,
      ...settings?.notification,
    },
    projectsDisplayMode:
      settings?.projectsDisplayMode ??
      DEFAULT_LOCAL_SETTINGS.projectsDisplayMode,
  };
}

function getThreadModelStorageKey(threadId: string): string {
  return `${THREAD_MODEL_KEY_PREFIX}${threadId}`;
}

export function getThreadModelName(threadId: string): string | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  return (
    safeLocalStorage.getItem(getThreadModelStorageKey(threadId)) ?? undefined
  );
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
    safeLocalStorage.removeItem(key);
    return;
  }
  safeLocalStorage.setItem(key, modelName);
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

export function getLocalSettings(): LocalSettings {
  if (!isBrowser()) {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = safeLocalStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json) as Partial<LocalSettings> & {
        context?: Record<string, unknown>;
      };
      // Legacy localStorage shape (pre-mode migration) may carry
      // `thinking_enabled` / `is_plan_mode` directly under `context` instead of
      // the consolidated `mode: "flash" | "thinking" | "pro" | "ultra"` field.
      // Without this one-shot migration the threads hooks would silently leave
      // `mode` undefined and pick the wrong reasoning_effort branch.
      const context = settings.context ?? {};
      if (
        typeof context.mode !== "string" &&
        (typeof context.thinking_enabled === "boolean" ||
          typeof context.is_plan_mode === "boolean")
      ) {
        const thinking = context.thinking_enabled === true;
        const plan = context.is_plan_mode === true;
        // Priority: is_plan_mode (most explicit) > thinking_enabled > flash.
        const derivedMode: "flash" | "thinking" | "pro" = plan
          ? "pro"
          : thinking
            ? "thinking"
            : "flash";
        delete context.thinking_enabled;
        delete context.is_plan_mode;
        context.mode = derivedMode;
        settings.context = context;
        // Persist the cleaned shape so we only pay the migration cost once.
        try {
          safeLocalStorage.setItem(
            LOCAL_SETTINGS_KEY,
            JSON.stringify(settings),
          );
        } catch {
          /* fall back silently; mergeLocalSettings still produces a sane value */
        }
      }
      return mergeLocalSettings(settings);
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

export function saveLocalSettings(settings: LocalSettings) {
  if (!isBrowser()) {
    return;
  }
  safeLocalStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
}
