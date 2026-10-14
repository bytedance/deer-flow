import { reconnectRunStorageKey } from "@/core/api/api-client";

import {
  captureWorkspaceRequestScope,
  type WorkspaceRequestScope,
} from "./request-scope";

/** The narrow storage contract supported by the native React SDK. */
export interface WorkspaceRunStorage {
  getItem(key: `lg:stream:${string}`): string | null;
  setItem(key: `lg:stream:${string}`, value: string): void;
  removeItem(key: `lg:stream:${string}`): void;
}

export function createWorkspaceRunStorage(
  scope: WorkspaceRequestScope,
): WorkspaceRunStorage {
  const captured = captureWorkspaceRequestScope(scope);
  const keyFor = (key: string) => {
    const prefix = "lg:stream:";
    return key.startsWith(prefix) && key.length > prefix.length
      ? reconnectRunStorageKey(key.slice(prefix.length), captured)
      : null;
  };
  return Object.freeze({
    getItem(key: `lg:stream:${string}`) {
      if (captured.signal.aborted) return null;
      const scopedKey = keyFor(key);
      try {
        return scopedKey ? window.sessionStorage.getItem(scopedKey) : null;
      } catch {
        return null;
      }
    },
    setItem(key: `lg:stream:${string}`, value: string) {
      if (captured.signal.aborted) return;
      const scopedKey = keyFor(key);
      try {
        if (scopedKey) window.sessionStorage.setItem(scopedKey, value);
      } catch {
        /* Reconnection remains available from the durable Runs list. */
      }
    },
    removeItem(key: `lg:stream:${string}`) {
      if (captured.signal.aborted) return;
      const scopedKey = keyFor(key);
      try {
        if (scopedKey) window.sessionStorage.removeItem(scopedKey);
      } catch {
        /* A marker never grants permission to read or cancel a Run. */
      }
    },
  });
}
