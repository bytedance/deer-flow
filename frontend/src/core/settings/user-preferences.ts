import { fetch as apiFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import { safeLocalStorage, type LocalSettings } from "./local";
import {
  parsePreferences,
  PreferencesSync,
  type Preferences,
} from "./preferences-sync";
import { activatePreferences } from "./store";

const PREFIX = "deerflow.preferences.";

function readJSON(read: () => string | null): Preferences {
  try {
    return parsePreferences(JSON.parse(read() ?? "{}"));
  } catch {
    return {};
  }
}

export function preferencesFromSettings(settings: LocalSettings): Preferences {
  return {
    notification_enabled: settings.notification.enabled,
    model_name: settings.context.model_name ?? null,
    mode: settings.context.mode ?? null,
    reasoning_effort: settings.context.reasoning_effort ?? null,
  };
}

/** Network lifecycle is attached to the authenticated workspace, never render. */
export function startUserPreferences(userId: string) {
  const key = `${PREFIX}${userId}`;
  // sessionStorage is tab-local; a sibling tab cannot overwrite our outbox.
  const outbox = `${key}.pending`;
  const abort = new AbortController();
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let retryMs = 1000;
  let flushing = false;
  const request = async (method: "GET" | "PATCH", value?: Preferences) => {
    const response = await apiFetch(
      `${getBackendBaseURL()}/api/v1/auth/preferences`,
      {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-Expected-User-Id": userId,
        },
        body: value ? JSON.stringify(value) : undefined,
        signal: AbortSignal.any([abort.signal, AbortSignal.timeout(15000)]),
        cache: "no-store",
      },
    );
    if (response.status === 409 || response.status === 403) {
      // A cookie can switch accounts in another tab before useAuth updates.
      // Keep this account's outbox, but never retry it under the new identity.
      stop();
    }
    if (!response.ok)
      throw new Error(`Preferences request failed: ${response.status}`);
    return response;
  };
  let apply: (value: Preferences) => void = () => undefined;
  const cached = readJSON(() => safeLocalStorage.getItem(key));
  const pending = readJSON(() => window.sessionStorage.getItem(outbox));
  const sync = new PreferencesSync(
    {
      read: async () => parsePreferences(await (await request("GET")).json()),
      patch: async (value) => {
        await request("PATCH", value);
      },
      saveConfirmed: (value) => {
        const serialized = JSON.stringify(value);
        if (safeLocalStorage.getItem(key) !== serialized)
          safeLocalStorage.setItem(key, serialized);
      },
      apply: (value) => apply(value),
      savePending: (value) => {
        try {
          window.sessionStorage.setItem(outbox, JSON.stringify(value));
        } catch {}
      },
    },
    cached,
    pending,
  );

  const wake = () => {
    if (stopped || flushing) return;
    clearTimeout(timer);
    flushing = true;
    void sync
      .flush()
      .then(() => {
        retryMs = 1000;
      })
      .catch(() => {
        if (stopped) return;
        timer = setTimeout(wake, retryMs);
        retryMs = Math.min(retryMs * 2, 30000);
      })
      .finally(() => {
        flushing = false;
      });
  };
  const detach = activatePreferences(
    { ...cached, ...pending },
    (before, after) => {
      const oldValue = preferencesFromSettings(before);
      const newValue = preferencesFromSettings(after);
      const changes = Object.fromEntries(
        Object.entries(newValue).filter(
          ([field, value]) => oldValue[field as keyof Preferences] !== value,
        ),
      );
      if (Object.keys(changes).length) {
        sync.edit(parsePreferences(changes));
        wake();
      }
    },
  );
  apply = detach.apply;
  const onStorage = (event: StorageEvent) => {
    if (event.key === key || event.key === null) wake();
  };
  function stop() {
    if (stopped) return;
    stopped = true;
    clearTimeout(timer);
    abort.abort();
    sync.stop();
    detach.stop();
    window.removeEventListener("focus", wake);
    window.removeEventListener("online", wake);
    window.removeEventListener("storage", onStorage);
  }
  window.addEventListener("focus", wake);
  window.addEventListener("online", wake);
  window.addEventListener("storage", onStorage);
  wake();
  return stop;
}
