import {
  DEFAULT_TENANT_ID,
  TENANT_SEARCH_PARAM,
  TENANT_STORAGE_KEY,
  validateTenantId,
} from "./types";

type Listener = () => void;

const listeners = new Set<Listener>();

let _currentTenantId: string = DEFAULT_TENANT_ID;
let _loaded = false;

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function resolveFromURL(): string | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const raw = params.get(TENANT_SEARCH_PARAM);
  if (!raw) return null;
  try {
    const cleaned = validateTenantId(raw);
    try {
      localStorage.setItem(TENANT_STORAGE_KEY, cleaned);
    } catch {
      // localStorage unavailable
    }
    return cleaned;
  } catch {
    return null;
  }
}

function resolveFromStorage(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = localStorage.getItem(TENANT_STORAGE_KEY);
    if (stored) {
      return validateTenantId(stored);
    }
  } catch {
    // localStorage unavailable or invalid stored value
  }
  return null;
}

function ensureLoaded() {
  if (_loaded || typeof window === "undefined") return;

  // Priority: URL param > localStorage > default
  const fromURL = resolveFromURL();
  if (fromURL) {
    _currentTenantId = fromURL;
  } else {
    const fromStorage = resolveFromStorage();
    if (fromStorage) {
      _currentTenantId = fromStorage;
    }
  }
  _loaded = true;
}

export function getCurrentTenantId(): string {
  ensureLoaded();
  return _currentTenantId;
}

export function setCurrentTenantId(tenantId: string) {
  const cleaned = validateTenantId(tenantId);
  _currentTenantId = cleaned;
  _loaded = true;
  try {
    localStorage.setItem(TENANT_STORAGE_KEY, cleaned);
  } catch {
    // localStorage unavailable
  }
  emitChange();
}

export function subscribe(listener: Listener): () => void {
  ensureLoaded();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getTenantHeaders(): Record<string, string> {
  const tid = getCurrentTenantId();
  if (tid === DEFAULT_TENANT_ID) return {};
  return { "X-DeerFlow-Tenant": tid };
}
