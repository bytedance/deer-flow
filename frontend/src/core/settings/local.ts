import type { AgentThreadContext } from "../threads";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
  },
  layout: {
    sidebar_collapsed: false,
  },
};

const LOCAL_SETTINGS_KEY = "deerflow.local-settings";
const THREAD_CONTEXT_KEY_PREFIX = "deerflow.thread-context.";

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
  > & {
    mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
  };
  layout: {
    sidebar_collapsed: boolean;
  };
}

function getThreadContextKey(threadId: string) {
  return `${THREAD_CONTEXT_KEY_PREFIX}${threadId}`;
}

function mergeContext(
  baseContext: LocalSettings["context"],
  context: Partial<LocalSettings["context"]> | null | undefined,
): LocalSettings["context"] {
  return {
    ...baseContext,
    ...context,
  };
}

function getStoredThreadContext(
  threadId: string | null | undefined,
): Partial<LocalSettings["context"]> | null {
  if (!threadId) {
    return null;
  }
  try {
    const json = localStorage.getItem(getThreadContextKey(threadId));
    return json ? (JSON.parse(json) as Partial<LocalSettings["context"]>) : null;
  } catch {
    return null;
  }
}

export function getLocalSettings(threadId?: string | null): LocalSettings {
  if (typeof window === "undefined") {
    return DEFAULT_LOCAL_SETTINGS;
  }
  try {
    const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
    if (json) {
      const settings = JSON.parse(json);
      const mergedSettings: LocalSettings = {
        ...DEFAULT_LOCAL_SETTINGS,
        context: mergeContext(DEFAULT_LOCAL_SETTINGS.context, settings.context),
        layout: {
          ...DEFAULT_LOCAL_SETTINGS.layout,
          ...settings.layout,
        },
        notification: {
          ...DEFAULT_LOCAL_SETTINGS.notification,
          ...settings.notification,
        },
      };
      return {
        ...mergedSettings,
        context: mergeContext(
          mergedSettings.context,
          getStoredThreadContext(threadId),
        ),
      };
    }
  } catch {}
  return {
    ...DEFAULT_LOCAL_SETTINGS,
    context: mergeContext(
      DEFAULT_LOCAL_SETTINGS.context,
      getStoredThreadContext(threadId),
    ),
  };
}

export function saveLocalSettings(
  settings: LocalSettings,
  threadId?: string | null,
) {
  try {
    const globalSettings: LocalSettings = {
      ...settings,
      context: threadId ? getLocalSettings().context : settings.context,
    };
    localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(globalSettings));
    if (threadId) {
      localStorage.setItem(
        getThreadContextKey(threadId),
        JSON.stringify(settings.context),
      );
    }
  } catch {}
}
