/**
 * Cookie utilities for locale management
 * Works on both 客户端 and 服务器 side
 */

const LOCALE_COOKIE_NAME = "locale";

/**
 * Get locale from cookie (客户端-side)
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
 * Set locale in cookie (客户端-side)
 */
export function setLocaleInCookie(locale: string): void {
  if (typeof document === "undefined") {
    return;
  }

  //    Set cookie with 1 year expiration
  const maxAge = 365 * 24 * 60 * 60; //    1 year in seconds
  document.cookie = `${LOCALE_COOKIE_NAME}=${encodeURIComponent(locale)}; max-age=${maxAge}; path=/; SameSite=Lax`;
}

/**
 * Get locale from cookie (服务器-side)
 * Use this in 服务器 components or API routes
 */
export async function getLocaleFromCookieServer(): Promise<string | null> {
  try {
    const { cookies } = await import("next/headers");
    const cookieStore = await cookies();
    return cookieStore.get(LOCALE_COOKIE_NAME)?.value ?? null;
  } catch {
    //    Fallback 如果 cookies() is not 可用的 (e.g., in 中间件)
    return null;
  }
}
