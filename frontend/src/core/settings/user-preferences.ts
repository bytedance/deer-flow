import { useEffect } from "react";

import { fetch as apiFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import type { Locale } from "@/core/i18n/locale";

import { safeLocalStorage, type LocalSettings } from "./local";
import {
  parsePreferences,
  PreferencesSync,
  type Preferences,
} from "./preferences-sync";
import { activatePreferences } from "./store";

const PREFIX = "deerflow.preferences.";

// The UI language the user reads DeerFlow in, reported by the I18nProvider.
// The Gateway words scheduled-task IM notices in the account's `locale`
// preference, so a running preference session keeps that preference equal
// to this value (see `startUserPreferences`).
let uiLocale: Locale | null = null;
const uiLocaleListeners = new Set<() => void>();

/** Record the UI language; a signed-in session saves it as `locale` when the account's differs. */
export function reportUiLocale(locale: Locale) {
  if (uiLocale === locale) return;
  uiLocale = locale;
  for (const listener of uiLocaleListeners) listener();
}

/**
 * Keep the account's `locale` preference equal to the UI language: called by
 * the I18nProvider with its current locale (initial cookie/browser language
 * and every switch). Only a signed-in session with session auth writes it;
 * with auth disabled nothing is sent and the Gateway falls back to
 * `channel_connections.notification_locale`. Failures retry in the
 * background like the other preferences and never surface.
 */
export function useSyncLocalePreference(locale: Locale) {
  useEffect(() => {
    reportUiLocale(locale);
  }, [locale]);
}

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
  // What the account currently holds (confirmed plus pending edits), whether
  // the server's copy has been read at least once, and whether that Gateway
  // knows the `locale` preference (an older one rejects unknown fields, which
  // would hold every other preference edit in the outbox).
  let effective: Preferences = {};
  let remoteLoaded = false;
  let localeSupported = false;
  // The UI language this session last reconciled with the account.
  let syncedLocale: Locale | null = null;
  const syncLocale = () => {
    if (stopped || !remoteLoaded || !localeSupported || uiLocale === null)
      return;
    // Once per session (after the first read) and on every language switch.
    // A later read showing another device's language is not written back, so
    // two devices in different languages do not overwrite each other on
    // every focus.
    if (syncedLocale === uiLocale) return;
    syncedLocale = uiLocale;
    if (effective.locale === uiLocale) return;
    sync.edit({ locale: uiLocale });
    wake();
  };
  const cached = readJSON(() => safeLocalStorage.getItem(key));
  const pending = readJSON(() => window.sessionStorage.getItem(outbox));
  const sync = new PreferencesSync(
    {
      read: async () => {
        const body: unknown = await (await request("GET")).json();
        localeSupported =
          typeof body === "object" &&
          body !== null &&
          Object.hasOwn(body, "locale");
        remoteLoaded = true;
        return parsePreferences(body);
      },
      patch: async (value) => {
        await request("PATCH", value);
      },
      saveConfirmed: (value) => {
        const serialized = JSON.stringify(value);
        if (safeLocalStorage.getItem(key) !== serialized)
          safeLocalStorage.setItem(key, serialized);
      },
      apply: (value) => {
        effective = value;
        apply(value);
        // After the first read: save the UI language if the account differs.
        syncLocale();
      },
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
    uiLocaleListeners.delete(syncLocale);
  }
  window.addEventListener("focus", wake);
  window.addEventListener("online", wake);
  window.addEventListener("storage", onStorage);
  uiLocaleListeners.add(syncLocale);
  wake();
  return stop;
}
