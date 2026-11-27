import { getReasoningCapabilities } from "@/core/models/reasoning";
import type { Model } from "@/core/models/types";

import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  THREAD_MODEL_KEY_PREFIX,
  getLocalSettings,
  getThreadModelName,
  safeLocalStorage,
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
const THREAD_EFFORT_KEY_PREFIX = "deerflow.thread-reasoning-effort.";
const threadEfforts = new Map<string, string | undefined>();

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

function readSharedSettings(): LocalSettings {
  const local = getLocalSettings();
  if (!preferenceEdit) return local;
  // Device-local fields still follow other tabs, including key removal and
  // storage.clear(). The legacy key must never replace account preferences.
  return {
    ...local,
    notification: baseSettings.notification,
    context: {
      ...local.context,
      model_name: baseSettings.context.model_name,
      mode: baseSettings.context.mode,
      reasoning_effort: baseSettings.context.reasoning_effort,
    },
  };
}

function handleStorage(event: StorageEvent) {
  if (event.storageArea && event.storageArea !== localStorage) {
    return;
  }

  ensureBaseSettingsLoaded();

  if (event.key === null) {
    baseSettings = readSharedSettings();
    threadModelNames.clear();
    threadEfforts.clear();
    emitChange();
    return;
  }

  if (event.key === LOCAL_SETTINGS_KEY) {
    baseSettings = readSharedSettings();
    emitChange();
    return;
  }

  if (event.key.startsWith(THREAD_EFFORT_KEY_PREFIX)) {
    threadEfforts.delete(event.key.slice(THREAD_EFFORT_KEY_PREFIX.length));
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

export function getThreadEffortOverride(
  threadId?: string | null,
): string | undefined {
  if (!threadId) return undefined;
  const effort = threadEfforts.has(threadId)
    ? threadEfforts.get(threadId)
    : safeLocalStorage.getItem(THREAD_EFFORT_KEY_PREFIX + threadId);
  return effort?.length ? effort : undefined;
}

function rememberThreadEffortChoice(
  threadId: string,
  effort: string | undefined,
) {
  const key = THREAD_EFFORT_KEY_PREFIX + threadId;
  const saved =
    effort === undefined
      ? safeLocalStorage.removeItem(key)
      : safeLocalStorage.setItem(key, effort);
  if (saved) threadEfforts.delete(threadId);
  else threadEfforts.set(threadId, effort);
}

/** Another chat may have resolved the shared model before this one sees the catalog. */
export function reconcileThreadEffort(
  threadId: string,
  previousModel: string | undefined,
  model: Model,
) {
  if (!previousModel) return;
  const effort = getThreadEffortOverride(threadId);
  if (!effort) return;
  const options = getReasoningCapabilities(model).effort;
  const supported =
    options &&
    (options.values.includes(effort) || Object.hasOwn(options.aliases, effort));
  if (previousModel !== model.name || !supported) {
    rememberThreadEffortChoice(threadId, undefined);
    emitChange();
  }
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

/** Explicit conversation-only selection; never edits account/base preferences. */
export function selectThreadModel(threadId: string, modelName: string) {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();
  if (
    !safeLocalStorage.setItem(
      `${THREAD_MODEL_KEY_PREFIX}${threadId}`,
      modelName,
    )
  ) {
    throw new Error("Unable to save the conversation model in this browser.");
  }
  rememberThreadEffortChoice(threadId, undefined);
  threadModelNames.set(threadId, modelName);
  emitChange();
}

export function updateThreadSettings<K extends keyof LocalSettings>(
  threadId: string,
  key: K,
  value: Partial<LocalSettings[K]>,
  automatic = false,
) {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  const previous = baseSettings;
  if (key === "context" && !automatic) {
    const edit = value as Partial<LocalSettings["context"]>;
    if ("mode" in edit || "model_name" in edit) {
      rememberThreadEffortChoice(threadId, undefined);
    } else if ("reasoning_effort" in edit) {
      rememberThreadEffortChoice(threadId, edit.reasoning_effort);
    }
  }
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
    updateThreadSettings(threadId, "context", context, true);
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
