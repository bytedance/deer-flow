import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { fetch as apiFetch } from "@/core/api/fetcher";
import {
  adjustLoginRedirectDeferral,
  setDeferredUnauthorizedHandler,
} from "@/core/auth/login-redirect-deferral";

describe("api fetcher unauthorized redirect", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    globalThis.fetch = rs.fn(
      async () => new Response("", { status: 401 }),
    ) as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns the caller to the full URL, query string included", async () => {
    window.history.replaceState(
      {},
      "",
      "/artifacts/view?path=%2Fmnt%2Fuser-data%2Foutputs%2Freport.md&thread_id=t-1",
    );

    // The wrapper redirects and then throws UnauthorizedError; the redirect
    // target is what this test is about.
    await expect(
      apiFetch("/api/threads/t-1/artifacts/mnt/user-data/outputs/report.md"),
    ).rejects.toThrow();

    expect(window.location.href).toContain("/login?next=");
    const next = new URL(
      window.location.href,
      "http://localhost",
    ).searchParams.get("next");
    expect(next).toBe(
      "/artifacts/view?path=%2Fmnt%2Fuser-data%2Foutputs%2Freport.md&thread_id=t-1",
    );
  });

  it("hands the suppressed login redirect to the deferral machinery", async () => {
    // Skipping the hard navigation alone strands the 401: every other
    // consumer of UnauthorizedError trusts that a login redirect is underway
    // (the banner withholds its warning, the models hook declines to
    // retry), so "suppress" must mean "hand over", not "drop" — the armed
    // target fires the moment the last deferral clears.
    window.history.replaceState({}, "", "/workspace/settings?x=1");
    const handed: string[] = [];
    setDeferredUnauthorizedHandler((target) => handed.push(target));
    adjustLoginRedirectDeferral(true);
    try {
      const hrefBefore = window.location.href;
      await expect(apiFetch("/api/v1/auth/pats")).rejects.toThrow();
      expect(window.location.href).toBe(hrefBefore);
      expect(handed).toHaveLength(1);
      expect(handed[0]).toContain("/login?next=");
      expect(handed[0]).toContain(
        encodeURIComponent("/workspace/settings?x=1"),
      );
    } finally {
      adjustLoginRedirectDeferral(false);
      setDeferredUnauthorizedHandler(null);
      window.history.replaceState({}, "", "/workspace");
    }
  });

  it("suppresses the hard 401 navigation while a login-redirect deferral holds", async () => {
    // The deferral exists so the PAT show-once window cannot be navigated
    // away from — but this fetcher's 401 branch is a hard
    // window.location.href write that bypasses the provider's held
    // redirect entirely (a reconnect-triggered list refetch while the
    // session already expired would discard the credential's only copy).
    // The count gates the hard navigation too; the error still throws.
    window.history.replaceState({}, "", "/workspace/settings");
    adjustLoginRedirectDeferral(true);
    try {
      const hrefBefore = window.location.href;
      await expect(apiFetch("/api/v1/auth/pats")).rejects.toThrow();
      expect(window.location.href).toBe(hrefBefore);

      // After the deferral clears, the automatic navigation is back.
      adjustLoginRedirectDeferral(false);
      await expect(apiFetch("/api/v1/auth/pats")).rejects.toThrow();
      expect(window.location.href).toContain("/login?next=");
    } finally {
      // Never leak an armed deferral into other tests.
      if (window.location.href.includes("/login")) {
        window.history.replaceState({}, "", "/workspace");
      }
      while (adjustLoginRedirectDeferral(false) > 0) {
        // drain
      }
    }
  });
});
