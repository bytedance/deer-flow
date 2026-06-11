/**
 * Regression tests for the shared auth fetcher (`@/core/api/fetcher`).
 *
 * Issue #3264: auth requests in `AuthProvider` used raw `fetch`, bypassing the
 * centralized credentials / CSRF / 401 handling. These tests pin the contracts
 * every auth call site relies on:
 *
 * 1. `credentials: "include"` is always sent.
 * 2. State-changing methods (POST/PUT/DELETE/PATCH) carry `X-CSRF-Token`
 *    echoed from the `csrf_token` cookie, so the gateway's CSRFMiddleware
 *    does not reject them with 403.
 * 3. GET/HEAD skip the CSRF header (mirrors the gateway's `should_check_csrf`).
 * 4. A 401 auto-redirects to `/login` and throws, unless the caller opts out
 *    via `redirectOnUnauthorized: false` (the documented exception used by
 *    `AuthProvider.refreshUser` / `logout`).
 */
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { fetch as fetchWithAuth } from "@/core/api/fetcher";

let globalFetch: ReturnType<typeof vi.fn>;
let assignedHref: string[];

function stubCookie(token: string | null): void {
  vi.stubGlobal("document", {
    cookie: token === null ? "" : `csrf_token=${token}; other=1`,
  });
}

function stubWindow(pathname: string): void {
  assignedHref = [];
  vi.stubGlobal("window", {
    location: {
      pathname,
      set href(value: string) {
        assignedHref.push(value);
      },
    },
  });
}

beforeEach(() => {
  globalFetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
  vi.stubGlobal("fetch", globalFetch);
  stubCookie("csrf-abc");
  stubWindow("/workspace/chats");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("always sends credentials: include", async () => {
  await fetchWithAuth("/api/v1/auth/me");

  expect(globalFetch).toHaveBeenCalledTimes(1);
  const init = globalFetch.mock.calls[0]![1] as RequestInit;
  expect(init.credentials).toBe("include");
});

test("injects X-CSRF-Token on state-changing methods from the cookie", async () => {
  await fetchWithAuth("/api/v1/auth/logout", { method: "POST" });

  const init = globalFetch.mock.calls[0]![1] as RequestInit;
  const headers = new Headers(init.headers);
  expect(headers.get("X-CSRF-Token")).toBe("csrf-abc");
});

test("does not add X-CSRF-Token on GET requests", async () => {
  await fetchWithAuth("/api/v1/auth/me", { method: "GET" });

  const init = globalFetch.mock.calls[0]![1] as RequestInit;
  const headers = new Headers(init.headers);
  expect(headers.has("X-CSRF-Token")).toBe(false);
});

test("does not overwrite a caller-supplied X-CSRF-Token", async () => {
  await fetchWithAuth("/api/v1/auth/logout", {
    method: "POST",
    headers: { "X-CSRF-Token": "explicit" },
  });

  const init = globalFetch.mock.calls[0]![1] as RequestInit;
  const headers = new Headers(init.headers);
  expect(headers.get("X-CSRF-Token")).toBe("explicit");
});

test("redirects to /login and throws on 401 by default", async () => {
  globalFetch.mockResolvedValueOnce(new Response(null, { status: 401 }));

  await expect(fetchWithAuth("/api/v1/auth/me")).rejects.toThrow(
    "Unauthorized",
  );
  expect(assignedHref).toHaveLength(1);
  expect(assignedHref[0]).toContain("/login");
});

test("does not redirect on 401 when redirectOnUnauthorized is false", async () => {
  globalFetch.mockResolvedValueOnce(new Response(null, { status: 401 }));

  const res = await fetchWithAuth("/api/v1/auth/me", {
    redirectOnUnauthorized: false,
  });

  expect(res.status).toBe(401);
  expect(assignedHref).toHaveLength(0);
});

test("does not forward redirectOnUnauthorized to the underlying fetch init", async () => {
  await fetchWithAuth("/api/v1/auth/me", { redirectOnUnauthorized: false });

  const init = globalFetch.mock.calls[0]![1] as Record<string, unknown>;
  expect("redirectOnUnauthorized" in init).toBe(false);
});
