import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { fetch as apiFetch } from "@/core/api/fetcher";

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

  it("redirects an account_disabled 401 to a login page that states the reason", async () => {
    globalThis.fetch = rs.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: { code: "account_disabled", message: "Account disabled" },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
    ) as unknown as typeof globalThis.fetch;
    window.history.replaceState({}, "", "/workspace");

    await expect(apiFetch("/api/v1/auth/me")).rejects.toThrow();

    expect(window.location.href).toContain("/login?error=account_disabled");
    // A disabled account cannot sign back in, so no return target is kept.
    expect(window.location.href).not.toContain("next=");
  });
});
