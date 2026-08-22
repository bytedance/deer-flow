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
import {
  fromPersistedUserSettings,
  mergePersistedUserSettingsPatches,
  parsePersistedUserSettings,
  parsePersistedUserSettingsPatch,
  toFullUserSettingsPatch,
  toPersistedUserSettings,
  type PersistedUserSettings,
  type PersistedUserSettingsPatch,
} from "./persistence";

type Listener = () => void;

export type LocalSettingsSetter = <K extends keyof LocalSettings>(
  key: K,
  value: Partial<LocalSettings[K]>,
) => void;

const listeners = new Set<Listener>();
const mutationListeners = new Set<
  (patch: PersistedUserSettingsPatch) => void
>();
const threadModelNames = new Map<string, string | undefined>();
const USER_SETTINGS_CACHE_KEY_PREFIX = "deerflow.user-settings-cache.";
const LEGACY_SETTINGS_OWNER_KEY = "deerflow.local-settings-owner";
const LEGACY_SETTINGS_LOCK_NAME = "deerflow.user-settings-legacy-migration";
const USER_SETTINGS_PENDING_KEY_PREFIX = "deerflow.user-settings-pending.";

let baseSettings: LocalSettings = DEFAULT_LOCAL_SETTINGS;
let baseSettingsLoaded = false;
let storageListenerRegistered = false;
let baseSettingsMutationVersion = 0;
let activeBaseSettingsUserId: string | null = null;
let baseSettingsActivationVersion = 0;

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function emitBaseSettingsMutation(key?: keyof LocalSettings) {
  baseSettingsMutationVersion += 1;
  const fullPatch = toFullUserSettingsPatch(
    toPersistedUserSettings(baseSettings),
  );
  const patch: PersistedUserSettingsPatch =
    key === "notification"
      ? { notification: fullPatch.notification }
      : key === "tokenUsage"
        ? { tokenUsage: fullPatch.tokenUsage }
        : key === "context"
          ? { context: fullPatch.context }
          : fullPatch;
  if (activeBaseSettingsUserId !== null) {
    savePendingBaseSettingsPatch(
      activeBaseSettingsUserId,
      mergePersistedUserSettingsPatches(
        getPendingBaseSettingsPatch(activeBaseSettingsUserId),
        patch,
      ),
    );
  }
  for (const listener of mutationListeners) {
    listener(patch);
  }
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

function userSettingsCacheStorageKey(userId: string): string {
  return `${USER_SETTINGS_CACHE_KEY_PREFIX}${encodeURIComponent(userId)}`;
}

function readUserSettingsCache(userId: string): PersistedUserSettings | null {
  const json = safeLocalStorage.getItem(userSettingsCacheStorageKey(userId));
  if (!json) return null;
  try {
    return parsePersistedUserSettings(JSON.parse(json));
  } catch {
    return null;
  }
}

function saveBaseSettingsCache(settings: LocalSettings): void {
  if (activeBaseSettingsUserId === null) {
    saveLocalSettings(settings);
    return;
  }
  safeLocalStorage.setItem(
    userSettingsCacheStorageKey(activeBaseSettingsUserId),
    JSON.stringify(toPersistedUserSettings(settings)),
  );
}

async function claimLegacySettings(
  userId: string,
): Promise<PersistedUserSettings | null> {
  const existingOwner = safeLocalStorage.getItem(LEGACY_SETTINGS_OWNER_KEY);
  if (existingOwner === userId) {
    return toPersistedUserSettings(getLocalSettings());
  }
  if (existingOwner !== null || typeof navigator === "undefined") return null;

  const lockManager = navigator.locks;
  if (!lockManager) return null;
  try {
    return await lockManager.request(
      LEGACY_SETTINGS_LOCK_NAME,
      { mode: "exclusive" },
      () => {
        const owner = safeLocalStorage.getItem(LEGACY_SETTINGS_OWNER_KEY);
        if (owner !== null && owner !== userId) return null;
        if (
          owner === null &&
          !safeLocalStorage.setItem(LEGACY_SETTINGS_OWNER_KEY, userId)
        ) {
          return null;
        }
        return safeLocalStorage.getItem(LEGACY_SETTINGS_OWNER_KEY) === userId
          ? toPersistedUserSettings(getLocalSettings())
          : null;
      },
    );
  } catch {
    // Web Locks may be unavailable in hardened/embedded browsers. In that
    // case, defaults are safer than assigning one unscoped value twice.
    return null;
  }
}

/**
 * Bind the local fallback to one authenticated account for this tab.
 *
 * The historical cache was unscoped. The first authenticated account claims
 * that legacy value; later accounts start from their own cache (or defaults)
 * until the server handshake completes. This keeps tabs signed into different
 * accounts from forwarding each other's storage events to their own servers.
 */
export async function activateBaseSettingsPersistence(
  userId: string,
): Promise<() => void> {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();
  const activationVersion = ++baseSettingsActivationVersion;
  const activationMutationVersion = baseSettingsMutationVersion;
  activeBaseSettingsUserId = userId;

  let persisted = readUserSettingsCache(userId);
  if (persisted === null) {
    const claimedLegacy = await claimLegacySettings(userId);
    persisted =
      readUserSettingsCache(userId) ??
      claimedLegacy ??
      toPersistedUserSettings(DEFAULT_LOCAL_SETTINGS);
    safeLocalStorage.setItem(
      userSettingsCacheStorageKey(userId),
      JSON.stringify(persisted),
    );
  }

  if (
    activeBaseSettingsUserId === userId &&
    baseSettingsActivationVersion === activationVersion &&
    baseSettingsMutationVersion === activationMutationVersion
  ) {
    baseSettings = fromPersistedUserSettings(persisted);
    emitChange();
  }
  return () => {
    if (
      activeBaseSettingsUserId === userId &&
      baseSettingsActivationVersion === activationVersion
    ) {
      activeBaseSettingsUserId = null;
    }
  };
}

function mergeSettingsSection<K extends keyof LocalSettings>(
  settings: LocalSettings,
  key: K,
  value: Partial<LocalSettings[K]>,
): LocalSettings {
  return {
    ...settings,
    [key]: {
      ...settings[key],
      ...value,
    },
  } as LocalSettings;
}

function handleStorage(event: StorageEvent) {
  if (event.storageArea && event.storageArea !== localStorage) {
    return;
  }

  ensureBaseSettingsLoaded();

  if (event.key === null) {
    if (activeBaseSettingsUserId !== null) return;
    baseSettings = getLocalSettings();
    threadModelNames.clear();
    emitBaseSettingsMutation();
    emitChange();
    return;
  }

  if (event.key.startsWith(THREAD_MODEL_KEY_PREFIX)) {
    const threadId = event.key.slice(THREAD_MODEL_KEY_PREFIX.length);
    threadModelNames.set(threadId, getThreadModelName(threadId));
    emitChange();
    return;
  }

  if (activeBaseSettingsUserId !== null) {
    if (event.key !== userSettingsCacheStorageKey(activeBaseSettingsUserId)) {
      return;
    }
    const persisted = readUserSettingsCache(activeBaseSettingsUserId);
    if (persisted === null) return;
    baseSettings = fromPersistedUserSettings(persisted);
    emitBaseSettingsMutation();
    emitChange();
    return;
  }

  if (event.key === LOCAL_SETTINGS_KEY) {
    baseSettings = getLocalSettings();
    emitBaseSettingsMutation();
    emitChange();
  }
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

export function getPersistedBaseSettingsSnapshot(): PersistedUserSettings {
  ensureBaseSettingsLoaded();
  return toPersistedUserSettings(baseSettings);
}

export function getBaseSettingsMutationVersion(): number {
  return baseSettingsMutationVersion;
}

export function getBaseSettingsMutationBoundary(): {
  version: number;
  userId: string | null;
} {
  return {
    version: baseSettingsMutationVersion,
    userId: activeBaseSettingsUserId,
  };
}

export function hydrateBaseSettingsFromServer(
  settings: PersistedUserSettings,
  expectedVersion: number,
): boolean {
  ensureBaseSettingsLoaded();
  if (expectedVersion !== baseSettingsMutationVersion) return false;
  baseSettings = fromPersistedUserSettings(settings);
  saveBaseSettingsCache(baseSettings);
  emitChange();
  return true;
}

export function subscribeBaseSettingsMutations(
  listener: (patch: PersistedUserSettingsPatch) => void,
): () => void {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();
  mutationListeners.add(listener);
  return () => mutationListeners.delete(listener);
}

function pendingPatchStorageKey(userId: string): string {
  return `${USER_SETTINGS_PENDING_KEY_PREFIX}${encodeURIComponent(userId)}`;
}

export function getPendingBaseSettingsPatch(
  userId: string,
): PersistedUserSettingsPatch | null {
  const json = safeLocalStorage.getItem(pendingPatchStorageKey(userId));
  if (!json) return null;
  try {
    return parsePersistedUserSettingsPatch(JSON.parse(json));
  } catch {
    return null;
  }
}

export function savePendingBaseSettingsPatch(
  userId: string,
  patch: PersistedUserSettingsPatch | null,
): void {
  const key = pendingPatchStorageKey(userId);
  if (patch === null) {
    safeLocalStorage.removeItem(key);
    return;
  }
  const validated = parsePersistedUserSettingsPatch(patch);
  if (validated !== null) {
    safeLocalStorage.setItem(key, JSON.stringify(validated));
  }
}

export function seedPendingBaseSettingsFromCurrent(
  userId: string,
): PersistedUserSettingsPatch {
  const fullPatch = toFullUserSettingsPatch(getPersistedBaseSettingsSnapshot());
  const pendingPatch = mergePersistedUserSettingsPatches(
    getPendingBaseSettingsPatch(userId),
    fullPatch,
  );
  savePendingBaseSettingsPatch(userId, pendingPatch);
  return pendingPatch;
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

  baseSettings = mergeSettingsSection(baseSettings, key, value);
  saveBaseSettingsCache(baseSettings);
  emitBaseSettingsMutation(key);
  emitChange();
};

export function updateThreadSettings<K extends keyof LocalSettings>(
  threadId: string,
  key: K,
  value: Partial<LocalSettings[K]>,
) {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  const nextBaseSettings = mergeSettingsSection(baseSettings, key, value);
  baseSettings = nextBaseSettings;
  saveBaseSettingsCache(baseSettings);
  emitBaseSettingsMutation(key);

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
