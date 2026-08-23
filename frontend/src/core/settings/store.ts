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
  applyPersistedUserSettingsPatch,
  diffPersistedUserSettings,
  fromPersistedUserSettings,
  mergePersistedUserSettingsPatches,
  parsePersistedUserSettings,
  parsePersistedUserSettingsPatch,
  toPersistedUserSettings,
  type PersistedUserSettings,
  type PersistedUserSettingsPatch,
} from "./persistence";
import type {
  UserSettingsMutationPersistence,
  UserSettingsPatchLeaf,
  VolatileUserSettingsPatchLeaf,
} from "./sync";

type Listener = () => void;

export type LocalSettingsSetter = <K extends keyof LocalSettings>(
  key: K,
  value: Partial<LocalSettings[K]>,
) => void;

const listeners = new Set<Listener>();
const mutationListeners = new Set<
  (
    patch: PersistedUserSettingsPatch,
    persistence: UserSettingsMutationPersistence,
  ) => void
>();
const threadModelNames = new Map<string, string | undefined>();
const USER_SETTINGS_CACHE_KEY_PREFIX = "deerflow.user-settings-cache.";
const LEGACY_SETTINGS_OWNER_KEY = "deerflow.local-settings-owner";
const LEGACY_SETTINGS_LOCK_NAME = "deerflow.user-settings-legacy-migration";
const USER_SETTINGS_WRITE_LOCK_PREFIX = "deerflow.user-settings-write.";
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

function emitBaseSettingsMutation(
  patch: PersistedUserSettingsPatch | null,
  persist = true,
): void {
  if (patch === null) return;
  baseSettingsMutationVersion += 1;
  const persistence =
    persist && activeBaseSettingsUserId !== null
      ? appendPendingBaseSettingsPatch(activeBaseSettingsUserId, patch)
      : { durableLeaves: [], volatileLeaves: [] };
  for (const listener of mutationListeners) {
    listener(patch, persistence);
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

export async function withBaseSettingsWriteLock(
  userId: string,
  task: () => Promise<void>,
): Promise<boolean> {
  if (typeof navigator === "undefined" || !navigator.locks) return false;
  const encodedUserId = encodeURIComponent(userId);
  const lockName = `${USER_SETTINGS_WRITE_LOCK_PREFIX}${encodedUserId.length}.${encodedUserId}`;
  try {
    return await navigator.locks.request(
      lockName,
      { mode: "exclusive" },
      async () => {
        await task();
        return true;
      },
    );
  } catch {
    return false;
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
    const previous = toPersistedUserSettings(baseSettings);
    baseSettings = getLocalSettings();
    threadModelNames.clear();
    emitBaseSettingsMutation(
      diffPersistedUserSettings(
        previous,
        toPersistedUserSettings(baseSettings),
      ),
      false,
    );
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
    const previous = toPersistedUserSettings(baseSettings);
    baseSettings = fromPersistedUserSettings(persisted);
    emitBaseSettingsMutation(
      diffPersistedUserSettings(previous, persisted),
      false,
    );
    emitChange();
    return;
  }

  if (event.key === LOCAL_SETTINGS_KEY) {
    const previous = toPersistedUserSettings(baseSettings);
    baseSettings = getLocalSettings();
    emitBaseSettingsMutation(
      diffPersistedUserSettings(
        previous,
        toPersistedUserSettings(baseSettings),
      ),
      false,
    );
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

export function getBaseSettingsMutationBoundary(userId: string): {
  version: number;
  userId: string | null;
  snapshot: PersistedUserSettings;
  durableLeafOpIds: Record<UserSettingsPatchLeaf, string | null>;
} {
  return {
    version: baseSettingsMutationVersion,
    userId: activeBaseSettingsUserId,
    snapshot: getPersistedBaseSettingsSnapshot(),
    durableLeafOpIds: Object.fromEntries(
      PENDING_PATCH_LEAVES.map((leaf) => [
        leaf,
        getPendingBaseSettingsLeafOpId(userId, leaf),
      ]),
    ) as Record<UserSettingsPatchLeaf, string | null>,
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
  listener: (
    patch: PersistedUserSettingsPatch,
    persistence: UserSettingsMutationPersistence,
  ) => void,
): () => void {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();
  mutationListeners.add(listener);
  return () => mutationListeners.delete(listener);
}

function pendingPatchStorageKey(userId: string): string {
  return `${USER_SETTINGS_PENDING_KEY_PREFIX}${encodeURIComponent(userId)}`;
}

function pendingPatchLeafPrefix(userId: string): string {
  const encodedUserId = encodeURIComponent(userId);
  return `${USER_SETTINGS_PENDING_KEY_PREFIX}leaf.${encodedUserId.length}.${encodedUserId}.`;
}

const PENDING_PATCH_LEAVES = [
  "notification.enabled",
  "tokenUsage.headerTotal",
  "tokenUsage.inlineMode",
  "context.model_name",
  "context.mode",
  "context.reasoning_effort",
] as const satisfies readonly UserSettingsPatchLeaf[];

interface PendingPatchEntry {
  ackKey: string;
  ackValue: string;
  patch: PersistedUserSettingsPatch;
}

export interface PendingBaseSettingsPatchBatch {
  patch: PersistedUserSettingsPatch;
  acknowledge: () => boolean;
}

function pendingPatchLeafStorageKey(
  userId: string,
  leaf: UserSettingsPatchLeaf,
): string {
  return `${pendingPatchLeafPrefix(userId)}${leaf}`;
}

function pendingPatchLeafAckStorageKey(
  userId: string,
  leaf: UserSettingsPatchLeaf,
): string {
  return `${pendingPatchLeafStorageKey(userId, leaf)}.ack`;
}

function pendingPatchLegacyAckStorageKey(userId: string): string {
  const encodedUserId = encodeURIComponent(userId);
  return `${USER_SETTINGS_PENDING_KEY_PREFIX}legacy-ack.${encodedUserId.length}.${encodedUserId}`;
}

function splitPendingPatchLeaves(
  patch: PersistedUserSettingsPatch,
): Array<{ leaf: UserSettingsPatchLeaf; patch: PersistedUserSettingsPatch }> {
  const leaves: Array<{
    leaf: UserSettingsPatchLeaf;
    patch: PersistedUserSettingsPatch;
  }> = [];
  if (patch.notification?.enabled !== undefined) {
    leaves.push({
      leaf: "notification.enabled",
      patch: { notification: { enabled: patch.notification.enabled } },
    });
  }
  if (patch.tokenUsage?.headerTotal !== undefined) {
    leaves.push({
      leaf: "tokenUsage.headerTotal",
      patch: { tokenUsage: { headerTotal: patch.tokenUsage.headerTotal } },
    });
  }
  if (patch.tokenUsage?.inlineMode !== undefined) {
    leaves.push({
      leaf: "tokenUsage.inlineMode",
      patch: { tokenUsage: { inlineMode: patch.tokenUsage.inlineMode } },
    });
  }
  if (patch.context?.model_name !== undefined) {
    leaves.push({
      leaf: "context.model_name",
      patch: { context: { model_name: patch.context.model_name } },
    });
  }
  if (patch.context?.mode !== undefined) {
    leaves.push({
      leaf: "context.mode",
      patch: { context: { mode: patch.context.mode } },
    });
  }
  if (patch.context?.reasoning_effort !== undefined) {
    leaves.push({
      leaf: "context.reasoning_effort",
      patch: { context: { reasoning_effort: patch.context.reasoning_effort } },
    });
  }
  return leaves;
}

function parsePendingLeafEnvelope(
  serialized: string,
  expectedLeaf: UserSettingsPatchLeaf,
): { opId: string; patch: PersistedUserSettingsPatch } | null {
  try {
    const value = JSON.parse(serialized) as unknown;
    if (
      typeof value !== "object" ||
      value === null ||
      Array.isArray(value) ||
      Object.keys(value).length !== 2 ||
      !("opId" in value) ||
      !("patch" in value) ||
      typeof value.opId !== "string" ||
      value.opId.length === 0 ||
      value.opId.length > 128
    ) {
      return null;
    }
    const patch = parsePersistedUserSettingsPatch(value.patch);
    if (patch === null) return null;
    const split = splitPendingPatchLeaves(patch);
    return split.length === 1 && split[0]?.leaf === expectedLeaf
      ? { opId: value.opId, patch }
      : null;
  } catch {
    return null;
  }
}

function readPendingLeafEnvelope(
  userId: string,
  leaf: UserSettingsPatchLeaf,
): { opId: string; patch: PersistedUserSettingsPatch } | null {
  const serialized = safeLocalStorage.getItem(
    pendingPatchLeafStorageKey(userId, leaf),
  );
  return serialized === null
    ? null
    : parsePendingLeafEnvelope(serialized, leaf);
}

function readPendingPatchEntries(userId: string): PendingPatchEntry[] {
  const entries: PendingPatchEntry[] = [];
  const legacyKey = pendingPatchStorageKey(userId);
  const keys: Array<{ key: string; leaf: UserSettingsPatchLeaf | null }> = [
    { key: legacyKey, leaf: null },
    ...PENDING_PATCH_LEAVES.map((leaf) => ({
      key: pendingPatchLeafStorageKey(userId, leaf),
      leaf,
    })),
  ];
  for (const { key, leaf } of keys) {
    const serialized = safeLocalStorage.getItem(key);
    if (serialized === null) continue;
    if (leaf !== null) {
      const envelope = parsePendingLeafEnvelope(serialized, leaf);
      const ackKey = pendingPatchLeafAckStorageKey(userId, leaf);
      if (
        envelope !== null &&
        safeLocalStorage.getItem(ackKey) !== envelope.opId
      ) {
        entries.push({
          ackKey,
          ackValue: envelope.opId,
          ...envelope,
        });
      }
      continue;
    }
    try {
      const patch = parsePersistedUserSettingsPatch(JSON.parse(serialized));
      const ackKey = pendingPatchLegacyAckStorageKey(userId);
      if (patch !== null && safeLocalStorage.getItem(ackKey) !== serialized) {
        entries.push({
          ackKey,
          ackValue: serialized,
          patch,
        });
      }
    } catch {}
  }
  return entries;
}

export function getPendingBaseSettingsPatchBatch(
  userId: string,
): PendingBaseSettingsPatchBatch | null {
  const entries = readPendingPatchEntries(userId);
  if (entries.length === 0) return null;
  const patch = entries.reduce<PersistedUserSettingsPatch | null>(
    (merged, entry) => mergePersistedUserSettingsPatches(merged, entry.patch),
    null,
  );
  if (patch === null) return null;
  return {
    patch,
    acknowledge: () => {
      let acknowledged = true;
      for (const entry of entries) {
        if (!safeLocalStorage.setItem(entry.ackKey, entry.ackValue)) {
          acknowledged = false;
        }
      }
      return acknowledged;
    },
  };
}

export function getPendingBaseSettingsPatch(
  userId: string,
): PersistedUserSettingsPatch | null {
  return getPendingBaseSettingsPatchBatch(userId)?.patch ?? null;
}

export function getPendingBaseSettingsLeafOpId(
  userId: string,
  leaf: UserSettingsPatchLeaf,
): string | null {
  return readPendingLeafEnvelope(userId, leaf)?.opId ?? null;
}

export function appendPendingBaseSettingsPatch(
  userId: string,
  patch: PersistedUserSettingsPatch,
): UserSettingsMutationPersistence {
  const validated = parsePersistedUserSettingsPatch(patch);
  const persistence: UserSettingsMutationPersistence = {
    durableLeaves: [],
    volatileLeaves: [],
  };
  if (validated === null) return persistence;
  for (const { leaf, patch: leafPatch } of splitPendingPatchLeaves(validated)) {
    const observedDurableOpId =
      readPendingLeafEnvelope(userId, leaf)?.opId ?? null;
    const opId =
      globalThis.crypto?.randomUUID?.() ??
      `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    if (
      safeLocalStorage.setItem(
        pendingPatchLeafStorageKey(userId, leaf),
        JSON.stringify({ opId, patch: leafPatch }),
      )
    ) {
      persistence.durableLeaves.push(leaf);
    } else {
      persistence.volatileLeaves.push({
        leaf,
        patch: leafPatch,
        observedDurableOpId,
      });
    }
  }
  return persistence;
}

export function savePendingBaseSettingsPatch(
  userId: string,
  patch: PersistedUserSettingsPatch | null,
): void {
  if (patch === null) {
    for (const key of [
      pendingPatchStorageKey(userId),
      pendingPatchLegacyAckStorageKey(userId),
      ...PENDING_PATCH_LEAVES.flatMap((leaf) => [
        pendingPatchLeafStorageKey(userId, leaf),
        pendingPatchLeafAckStorageKey(userId, leaf),
      ]),
    ]) {
      safeLocalStorage.removeItem(key);
    }
    return;
  }
  appendPendingBaseSettingsPatch(userId, patch);
}

export function seedPendingBaseSettingsFromCurrent(
  userId: string,
  baseline: PersistedUserSettings,
  boundaryLeafOpIds: Record<UserSettingsPatchLeaf, string | null>,
): VolatileUserSettingsPatchLeaf[] {
  const patch = diffPersistedUserSettings(
    baseline,
    getPersistedBaseSettingsSnapshot(),
  );
  if (patch === null) return [];
  let eligiblePatch: PersistedUserSettingsPatch | null = null;
  for (const { leaf, patch: leafPatch } of splitPendingPatchLeaves(patch)) {
    if (
      getPendingBaseSettingsLeafOpId(userId, leaf) === boundaryLeafOpIds[leaf]
    ) {
      eligiblePatch = mergePersistedUserSettingsPatches(
        eligiblePatch,
        leafPatch,
      );
    }
  }
  return eligiblePatch === null
    ? []
    : appendPendingBaseSettingsPatch(userId, eligiblePatch).volatileLeaves;
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

  const previous = toPersistedUserSettings(baseSettings);
  const locallyMerged = mergeSettingsSection(baseSettings, key, value);
  const patch = diffPersistedUserSettings(
    previous,
    toPersistedUserSettings(locallyMerged),
  );
  const latestPersisted =
    activeBaseSettingsUserId === null
      ? null
      : readUserSettingsCache(activeBaseSettingsUserId);
  baseSettings =
    patch !== null && latestPersisted !== null
      ? fromPersistedUserSettings(
          applyPersistedUserSettingsPatch(latestPersisted, patch),
        )
      : locallyMerged;
  emitBaseSettingsMutation(patch);
  saveBaseSettingsCache(baseSettings);
  emitChange();
};

export function updateThreadSettings<K extends keyof LocalSettings>(
  threadId: string,
  key: K,
  value: Partial<LocalSettings[K]>,
) {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  const previous = toPersistedUserSettings(baseSettings);
  const locallyMerged = mergeSettingsSection(baseSettings, key, value);
  const patch = diffPersistedUserSettings(
    previous,
    toPersistedUserSettings(locallyMerged),
  );
  const latestPersisted =
    activeBaseSettingsUserId === null
      ? null
      : readUserSettingsCache(activeBaseSettingsUserId);
  baseSettings =
    patch !== null && latestPersisted !== null
      ? fromPersistedUserSettings(
          applyPersistedUserSettingsPatch(latestPersisted, patch),
        )
      : locallyMerged;
  emitBaseSettingsMutation(patch);
  saveBaseSettingsCache(baseSettings);

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
