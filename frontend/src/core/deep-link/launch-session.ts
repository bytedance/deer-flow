"use client";

const LAUNCH_SESSION_STORAGE_KEY = "deerflow_deep_link_launch_sessions";
const MAX_LAUNCH_SESSION_ENTRIES = 100;

interface LaunchSessionEntry {
  threadId: string;
  routeKey: string;
  updatedAt: number;
}

type LaunchSessionMap = Record<string, LaunchSessionEntry>;

function canUseSessionStorage() {
  return typeof window !== "undefined" && !!window.sessionStorage;
}

function readLaunchSessionMap(): LaunchSessionMap {
  if (!canUseSessionStorage()) return {};
  try {
    const raw = window.sessionStorage.getItem(LAUNCH_SESSION_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as LaunchSessionMap;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeLaunchSessionMap(entries: LaunchSessionMap) {
  if (!canUseSessionStorage()) return;
  window.sessionStorage.setItem(
    LAUNCH_SESSION_STORAGE_KEY,
    JSON.stringify(entries),
  );
}

function pruneLaunchSessionMap(entries: LaunchSessionMap): LaunchSessionMap {
  const sortedEntries = Object.entries(entries).sort(
    (a, b) => b[1].updatedAt - a[1].updatedAt,
  );
  return Object.fromEntries(sortedEntries.slice(0, MAX_LAUNCH_SESSION_ENTRIES));
}

export function getLaunchThread(
  launchId: string,
  routeKey: string,
): string | null {
  if (!launchId) return null;
  const entry = readLaunchSessionMap()[launchId];
  if (!entry || entry.routeKey !== routeKey) return null;
  return entry.threadId || null;
}

export function setLaunchThread(
  launchId: string,
  threadId: string,
  routeKey: string,
) {
  if (!launchId || !threadId || !routeKey) return;
  const entries = readLaunchSessionMap();
  entries[launchId] = {
    threadId,
    routeKey,
    updatedAt: Date.now(),
  };
  writeLaunchSessionMap(pruneLaunchSessionMap(entries));
}

export const __test_only = {
  readLaunchSessionMap,
  pruneLaunchSessionMap,
  MAX_LAUNCH_SESSION_ENTRIES,
};
