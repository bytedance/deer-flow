import { useCallback, useSyncExternalStore } from "react";

import {
  getLocalSettings,
  saveLocalSettings,
  type LocalSettings,
} from "./local";

// Module-level shared snapshot so all useLocalSettings instances stay in sync.
const listeners = new Set<() => void>();
let snapshot: LocalSettings = getLocalSettings();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return snapshot;
}

function updateSnapshot(newSettings: LocalSettings) {
  saveLocalSettings(newSettings);
  snapshot = newSettings;
  for (const listener of listeners) {
    listener();
  }
}

export function reloadLocalSettingsSnapshot() {
  snapshot = getLocalSettings();
  for (const listener of listeners) {
    listener();
  }
}

export function useLocalSettings(): [
  LocalSettings,
  (
    key: keyof LocalSettings,
    value: Partial<LocalSettings[keyof LocalSettings]>,
  ) => void,
] {
  const state = useSyncExternalStore(subscribe, getSnapshot);
  const setter = useCallback(
    (
      key: keyof LocalSettings,
      value: Partial<LocalSettings[keyof LocalSettings]>,
    ) => {
      const prev = getSnapshot();
      const newState = {
        ...prev,
        [key]: {
          ...prev[key],
          ...value,
        },
      };
      updateSnapshot(newState);
    },
    [],
  );
  return [state, setter];
}
