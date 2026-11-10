import { useCallback, useMemo, useSyncExternalStore } from "react";

import { safeLocalStorage } from "@/core/settings/local";

import { parseFavoriteNames, serializeFavoriteNames } from "./favorites";

const EVENT = "deerflow:model-recent";
const memory = new Map<string, string>();
export const recentKey = (userId: string) =>
  `deerflow.model-recent.v1:${encodeURIComponent(userId)}`;

export function rememberModel(userId: string | null, name: string) {
  if (!userId || !name.trim()) return;
  const key = recentKey(userId);
  const previous = parseFavoriteNames(
    memory.get(key) ?? safeLocalStorage.getItem(key),
  );
  const raw = serializeFavoriteNames(
    [name, ...previous.filter((item) => item !== name)].slice(0, 8),
  );
  if (!safeLocalStorage.setItem(key, raw)) memory.set(key, raw);
  else memory.delete(key);
  window.dispatchEvent(new Event(EVENT));
}

export function useRecentModels(userId: string | null) {
  const subscribe = useCallback((notify: () => void) => {
    window.addEventListener(EVENT, notify);
    window.addEventListener("storage", notify);
    return () => {
      window.removeEventListener(EVENT, notify);
      window.removeEventListener("storage", notify);
    };
  }, []);
  const snapshot = useCallback(
    () =>
      userId
        ? (memory.get(recentKey(userId)) ??
          safeLocalStorage.getItem(recentKey(userId)))
        : null,
    [userId],
  );
  const raw = useSyncExternalStore(subscribe, snapshot, () => null);
  return useMemo(() => parseFavoriteNames(raw), [raw]);
}
