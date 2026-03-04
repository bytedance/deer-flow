import { getAccessToken } from "../auth/token";
import type { ProviderId } from "../models/types";
import type { AgentThreadContext } from "../threads";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  context: {
    model_name: undefined,
    thinking_effort: "medium",
    mode: undefined,
  },
  models: {
    providers: {
      openai: {
        enabled: false,
        has_key: false,
      },
      anthropic: {
        enabled: false,
        has_key: false,
      },
      gemini: {
        enabled: false,
        has_key: false,
      },
      deepseek: {
        enabled: false,
        has_key: false,
      },
      kimi: {
        enabled: false,
        has_key: false,
      },
      zai: {
        enabled: false,
        has_key: false,
      },
      minimax: {
        enabled: false,
        has_key: false,
      },
      "epfl-rcp": {
        enabled: false,
        has_key: false,
      },
    },
    enabled_models: {},
  },
  layout: {
    sidebar_collapsed: false,
  },
};

const LOCAL_SETTINGS_BASE_KEY = "thinktank.local-settings";

/**
 * Get a user-scoped localStorage key for settings.
 * Extracts the user ID from the JWT token so each user gets
 * their own settings on the same browser.
 */
function getLocalSettingsKey(): string {
  const token = getAccessToken();
  if (token) {
    try {
      const parts = token.split(".");
      if (parts.length === 3) {
        const payload = JSON.parse(
          atob(parts[1]!.replace(/-/g, "+").replace(/_/g, "/")),
        );
        if (payload.sub) {
          return `${LOCAL_SETTINGS_BASE_KEY}.${payload.sub}`;
        }
      }
    } catch {
      // Fall through to default key
    }
  }
  return LOCAL_SETTINGS_BASE_KEY;
}

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
  > & {
    mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
  };
  models: {
    providers: Record<
      ProviderId,
      {
        enabled: boolean;
        has_key: boolean;
        api_key?: string;
        last_validated_at?: string;
        last_validation_status?: "valid" | "invalid" | "unknown";
        last_validation_message?: string;
      }
    >;
    enabled_models: Record<string, boolean>;
  };
  layout: {
    sidebar_collapsed: boolean;
  };
}

export function getLocalSettings(): LocalSettings {
  if (typeof window === "undefined") {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const key = getLocalSettingsKey();
  const json = localStorage.getItem(key);
  try {
    if (json) {
      const settings = JSON.parse(json);
      const mergedSettings = {
        ...DEFAULT_LOCAL_SETTINGS,
        context: {
          ...DEFAULT_LOCAL_SETTINGS.context,
          ...settings.context,
        },
        models: {
          ...DEFAULT_LOCAL_SETTINGS.models,
          ...settings.models,
          providers: {
            ...DEFAULT_LOCAL_SETTINGS.models.providers,
            ...(settings.models?.providers ?? {}),
          },
          enabled_models: {
            ...DEFAULT_LOCAL_SETTINGS.models.enabled_models,
            ...(settings.models?.enabled_models ?? {}),
          },
        },
        layout: {
          ...DEFAULT_LOCAL_SETTINGS.layout,
          ...settings.layout,
        },
        notification: {
          ...DEFAULT_LOCAL_SETTINGS.notification,
          ...settings.notification,
        },
      };
      return mergedSettings;
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

export function saveLocalSettings(settings: LocalSettings) {
  const key = getLocalSettingsKey();
  localStorage.setItem(key, JSON.stringify(settings));
}
