// Last-known persistence for the agents_api feature flag.
//
// /api/features is fail-open by design so an outage can never hide a working
// feature. The symmetric risk is that when the feature is genuinely disabled
// and /api/features is down, failing open re-mounts the agents UI and brings
// back the 403 storm (#3757). Persisting the last definitive answer lets a
// cold start during an outage fall back to it instead of failing open.

const AGENTS_API_ENABLED_KEY = "deerflow.features.agents_api";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/** The last definitive value observed from /api/features, or undefined. */
export function readCachedAgentsApiEnabled(): boolean | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  try {
    const raw = window.localStorage.getItem(AGENTS_API_ENABLED_KEY);
    if (raw === "true") return true;
    if (raw === "false") return false;
  } catch {}
  return undefined;
}

export function writeCachedAgentsApiEnabled(value: boolean): void {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.setItem(AGENTS_API_ENABLED_KEY, String(value));
  } catch {}
}

/**
 * Resolve the effective flag from the live query value and the last-known
 * cached value:
 * - a live answer always wins;
 * - otherwise fall back to the last value we successfully observed (sticky),
 *   so a transient /api/features outage cannot flip a disabled feature back on;
 * - only fail open (true) when we have never had a definitive answer, so a
 *   genuinely working feature is never hidden by an outage.
 */
export function resolveAgentsApiEnabled(
  live: boolean | undefined,
  cached: boolean | undefined,
): boolean {
  return live ?? cached ?? true;
}
