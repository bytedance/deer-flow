import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  THREAD_MODEL_KEY_PREFIX,
  getLocalSettings,
  getThreadModelName,
  saveLocalSettings,
  saveThreadModelName,
  type LocalSettings,
} from "./local";
import type { Preferences } from "./preferences-sync";

type Listener = () => void;

export type LocalSettingsSetter = <K extends keyof LocalSettings>(
  key: K,
  value: Partial<LocalSettings[K]>,
) => void;

const listeners = new Set<Listener>();
const threadModelNames = new Map<string, string | undefined>();

let baseSettings: LocalSettings = DEFAULT_LOCAL_SETTINGS;
let baseSettingsLoaded = false;
let storageListenerRegistered = false;
let preferenceEdit:
  | ((before: LocalSettings, after: LocalSettings) => void)
  | undefined;

/** Activate only after the workspace has identified the account. */
export function activatePreferences(
  initial: Preferences,
  edit: (before: LocalSettings, after: LocalSettings) => void,
) {
  ensureBaseSettingsLoaded();
  preferenceEdit = edit;
  const apply = (value: Preferences) => {
    if (preferenceEdit !== edit) return;
    baseSettings = {
      ...baseSettings,
      notification: { enabled: value.notification_enabled ?? true },
      context: {
        ...baseSettings.context,
        model_name: value.model_name ?? undefined,
        mode: value.mode ?? undefined,
        reasoning_effort: value.reasoning_effort ?? undefined,
      },
    };
    emitChange();
  };
  apply(initial);
  return {
    apply,
    stop: () => {
      if (preferenceEdit === edit) {
        apply({});
        preferenceEdit = undefined;
      }
    },
  };
}

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function persistLocalOnlySettings() {
  if (!preferenceEdit) {
    saveLocalSettings(baseSettings);
    return;
  }
  // Account preferences never leak back into the legacy shared-origin key.
  const legacy = getLocalSettings();
  saveLocalSettings({
    ...baseSettings,
    notification: legacy.notification,
    context: {
      ...baseSettings.context,
      model_name: legacy.context.model_name,
      mode: legacy.context.mode,
      reasoning_effort: legacy.context.reasoning_effort,
    },
  });
}

function ensureBaseSettingsLoaded() {
  if (baseSettingsLoaded || typeof window === "undefined") {
    return;
  }

  baseSettings = getLocalSettings();
  baseSettingsLoaded = true;
}

function ensureStorageListenerRegistered() {
  if (storageListenerRegistered || typeof window === "undefined") {
    return;
  }

  window.addEventListener("storage", handleStorage);
  storageListenerRegistered = true;
}

function mergeSettingsSection<K extends keyof LocalSettings>(
  settings: LocalSettings,
  key: K,
  value: Partial<LocalSettings[K]>,
): LocalSettings {
  const current = settings[key];
  if (
    current !== null &&
    typeof current === "object" &&
    value !== null &&
    typeof value === "object"
  ) {
    return {
      ...settings,
      [key]: {
        ...current,
        ...value,
      },
    } as LocalSettings;
  }
  return {
    ...settings,
    [key]: value,
  };
}

function handleStorage(event: StorageEvent) {
  if (event.storageArea && event.storageArea !== localStorage) {
    return;
  }

  ensureBaseSettingsLoaded();

  if (event.key === null) {
    if (!preferenceEdit) baseSettings = getLocalSettings();
    threadModelNames.clear();
    emitChange();
    return;
  }

  if (event.key === LOCAL_SETTINGS_KEY) {
    if (!preferenceEdit) baseSettings = getLocalSettings();
    emitChange();
    return;
  }

  if (!event.key.startsWith(THREAD_MODEL_KEY_PREFIX)) {
    return;
  }

  const threadId = event.key.slice(THREAD_MODEL_KEY_PREFIX.length);
  threadModelNames.set(threadId, getThreadModelName(threadId));
  emitChange();
}

export function subscribe(listener: Listener): () => void {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();
  listeners.add(listener);

  return () => {
    listeners.delete(listener);
  };
}

export function getBaseSettingsSnapshot(): LocalSettings {
  ensureBaseSettingsLoaded();
  return baseSettings;
}

export function getThreadModelSnapshot(threadId: string): string | undefined {
  ensureBaseSettingsLoaded();

  if (!threadModelNames.has(threadId)) {
    threadModelNames.set(threadId, getThreadModelName(threadId));
  }

  return threadModelNames.get(threadId);
}

export const updateLocalSettings: LocalSettingsSetter = (key, value) => {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  const previous = baseSettings;
  baseSettings = mergeSettingsSection(baseSettings, key, value);
  persistLocalOnlySettings();
  preferenceEdit?.(previous, baseSettings);
  emitChange();
};

export function updateThreadSettings<K extends keyof LocalSettings>(
  threadId: string,
  key: K,
  value: Partial<LocalSettings[K]>,
) {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  const previous = baseSettings;
  const nextBaseSettings = mergeSettingsSection(baseSettings, key, value);
  baseSettings = nextBaseSettings;
  persistLocalOnlySettings();
  preferenceEdit?.(previous, baseSettings);

  if (
    key === "context" &&
    Object.prototype.hasOwnProperty.call(value, "model_name")
  ) {
    const contextValue = value as Partial<LocalSettings["context"]>;
    const threadModelName = contextValue.model_name;
    threadModelNames.set(threadId, threadModelName);
    saveThreadModelName(threadId, threadModelName);
  }

  emitChange();
}

/** Model availability/default resolution is not an explicit account edit. */
export function resolveThreadContext(
  threadId: string,
  context: Partial<LocalSettings["context"]>,
) {
  if (!preferenceEdit) {
    updateThreadSettings(threadId, "context", context);
    return;
  }
  baseSettings = mergeSettingsSection(baseSettings, "context", context);
  // Preserve explicit thread overrides, but do not create one from a temporary
  // fallback: it would mask the account model when a slow GET finally arrives.
  if (getThreadModelSnapshot(threadId) && "model_name" in context) {
    threadModelNames.set(threadId, context.model_name);
    saveThreadModelName(threadId, context.model_name);
  }
  emitChange();
}
