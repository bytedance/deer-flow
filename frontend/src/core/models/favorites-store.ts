import { safeLocalStorage } from "@/core/settings/local";

import {
  favoritesKey,
  parseFavoriteNames,
  serializeFavoriteNames,
  updateFavoriteNames,
} from "./favorites";

export interface FavoritesSnapshot {
  names: readonly string[];
  persistence: "local" | "memory";
}

const EMPTY_NAMES: readonly string[] = Object.freeze([]);

export const EMPTY_FAVORITES: FavoritesSnapshot = Object.freeze({
  names: EMPTY_NAMES,
  persistence: "memory",
});

type Listener = () => void;

interface FavoritesEntry {
  userId: string;
  snapshot: FavoritesSnapshot;
  listeners: Set<Listener>;
}

type StorageRead = { ok: true; raw: string | null } | { ok: false };

const entries = new Map<string, FavoritesEntry>();
let activeSubscriptionCount = 0;
let storageListenerRegistered = false;

function readPersistedFavorites(userId: string): StorageRead {
  if (typeof window === "undefined") {
    return { ok: false };
  }

  try {
    return {
      ok: true,
      raw: window.localStorage.getItem(favoritesKey(userId)),
    };
  } catch {
    return { ok: false };
  }
}

function sameNames(left: readonly string[], right: readonly string[]): boolean {
  return (
    left.length === right.length &&
    left.every((name, index) => name === right[index])
  );
}

function emitChange(entry: FavoritesEntry) {
  for (const listener of entry.listeners) {
    listener();
  }
}

function replaceSnapshot(
  entry: FavoritesEntry,
  names: readonly string[],
  persistence: FavoritesSnapshot["persistence"],
): boolean {
  if (
    entry.snapshot.persistence === persistence &&
    sameNames(entry.snapshot.names, names)
  ) {
    return false;
  }

  entry.snapshot = { names, persistence };
  return true;
}

function createEntry(userId: string): FavoritesEntry {
  const persisted = readPersistedFavorites(userId);
  const entry: FavoritesEntry = {
    userId,
    snapshot: {
      names: persisted.ok ? parseFavoriteNames(persisted.raw) : EMPTY_NAMES,
      persistence: "local",
    },
    listeners: new Set(),
  };
  entries.set(userId, entry);
  return entry;
}

function getEntry(userId: string): FavoritesEntry {
  return entries.get(userId) ?? createEntry(userId);
}

function reloadEntry(entry: FavoritesEntry) {
  if (entry.snapshot.persistence === "memory") {
    return;
  }

  const persisted = readPersistedFavorites(entry.userId);
  if (!persisted.ok) {
    return;
  }

  if (replaceSnapshot(entry, parseFavoriteNames(persisted.raw), "local")) {
    emitChange(entry);
  }
}

function handleStorage(event: StorageEvent) {
  try {
    if (event.storageArea !== window.localStorage) {
      return;
    }
  } catch {
    return;
  }

  if (event.key === null) {
    for (const entry of entries.values()) {
      reloadEntry(entry);
    }
    return;
  }

  for (const entry of entries.values()) {
    if (
      entry.snapshot.persistence === "local" &&
      favoritesKey(entry.userId) === event.key
    ) {
      reloadEntry(entry);
      return;
    }
  }
}

function registerStorageListener() {
  if (storageListenerRegistered || typeof window === "undefined") {
    return;
  }
  window.addEventListener("storage", handleStorage);
  storageListenerRegistered = true;
}

function unregisterStorageListener() {
  if (!storageListenerRegistered || typeof window === "undefined") {
    return;
  }
  window.removeEventListener("storage", handleStorage);
  storageListenerRegistered = false;
}

export function getFavoritesSnapshot(userId: string | null): FavoritesSnapshot {
  return userId === null ? EMPTY_FAVORITES : getEntry(userId).snapshot;
}

export function subscribeFavorites(
  userId: string | null,
  listener: Listener,
): () => void {
  if (userId === null) {
    return () => undefined;
  }

  const alreadyCached = entries.has(userId);
  const entry = getEntry(userId);
  if (alreadyCached) {
    reloadEntry(entry);
  }
  entry.listeners.add(listener);
  activeSubscriptionCount += 1;
  registerStorageListener();

  let subscribed = true;
  return () => {
    if (!subscribed) {
      return;
    }
    subscribed = false;
    entry.listeners.delete(listener);
    activeSubscriptionCount -= 1;
    if (activeSubscriptionCount === 0) {
      unregisterStorageListener();
    }
  };
}

export function setModelFavorite(
  userId: string | null,
  name: string,
  favorite: boolean,
) {
  if (userId === null) {
    return;
  }

  const entry = getEntry(userId);
  const nextNames = updateFavoriteNames(entry.snapshot.names, name, favorite);
  if (nextNames === entry.snapshot.names) {
    return;
  }

  let persistence = entry.snapshot.persistence;
  if (
    persistence === "local" &&
    !safeLocalStorage.setItem(
      favoritesKey(userId),
      serializeFavoriteNames(nextNames),
    )
  ) {
    persistence = "memory";
  }

  replaceSnapshot(entry, nextNames, persistence);
  emitChange(entry);
}
