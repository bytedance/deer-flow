import { useEffect, useSyncExternalStore } from "react";

let activeStreamCount = 0;
const listeners = new Set<() => void>();

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getCount() {
  return activeStreamCount;
}

export function useActiveStreamCount(): number {
  return useSyncExternalStore(subscribe, getCount, getCount);
}

export function useRegisterActiveStream(isActive: boolean) {
  useEffect(() => {
    if (!isActive) return;
    activeStreamCount += 1;
    emitChange();
    return () => {
      activeStreamCount = Math.max(0, activeStreamCount - 1);
      emitChange();
    };
  }, [isActive]);

  return useActiveStreamCount();
}
