/**
 * Cookie utilities for locale management
 * Works on both client and server side
 */

const LOCALE_COOKIE_NAME = "locale";

/**
 * Get locale from cookie (client-side)
 */
export function getLocaleFromCookie(): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const cookies = document.cookie.split(";");
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split("=");
    if (name === LOCALE_COOKIE_NAME) {
      return decodeURIComponent(value ?? "");
    }
  }
  return null;
}

/**
 * Set locale in cookie (client-side)
 */
export function setLocaleInCookie(locale: string): void {
  if (typeof document === "undefined") {
    return;
  }

  // Set cookie with 1 year expiration
  const maxAge = 365 * 24 * 60 * 60; // 1 year in seconds
  document.cookie = `${LOCALE_COOKIE_NAME}=${encodeURIComponent(locale)}; max-age=${maxAge}; path=/; SameSite=Lax`;
}

/**
 * Get locale from cookie (server-side)
 * Use this in server components or API routes
 */
export async function getLocaleFromCookieServer(): Promise<string | null> {
  try {
    const { cookies } = await import("next/headers");
    const cookieStore = await cookies();
    return cookieStore.get(LOCALE_COOKIE_NAME)?.value ?? null;
  } catch {
    // Fallback if cookies() is not available (e.g., in middleware)
    return null;
  }
}
