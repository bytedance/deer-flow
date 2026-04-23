/**
 * Canonical OAuth ``redirect_uri`` (authorize + token must match exactly).
 * Common invalid cases include trailing ``/``, hash fragments, or using the
 * backend callback path instead of the Next.js route.
 */
export function normalizeOAuthCallbackUrl(raw: string): string {
  const u = new URL(raw.trim());
  u.hash = "";
  const path = u.pathname.replace(/\/+$/, "") || "/";
  return `${u.origin}${path}${u.search}`;
}

/** Detects the legacy backend callback pathname that should not be used here. */
export function isLegacyApiAuthCallbackPathname(pathname: string): boolean {
  return pathname === "/api/auth/callback";
}
