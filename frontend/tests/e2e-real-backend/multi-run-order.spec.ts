import { expect, test } from "@playwright/test";

/**
 * Layer 2 (cross-stack contract): reproduces upstream issue #3352 — after the
 * checkpoint no longer holds the older messages (post context-compression), the
 * frontend rebuilds thread history from the per-run endpoints, and the order it
 * rebuilds them in must stay chronological.
 *
 * The dangerous class this guards: a BACKEND change to run ordering silently
 * breaks a FRONTEND assumption. Backend `list_by_thread` returns runs
 * NEWEST-FIRST (PR #2932); the pre-#3354 frontend iterated runs from the end and
 * PREPENDED each loaded page (`core/threads/hooks.ts`), which inverts order. A
 * backend-only ordering test was green the whole time #3352 was live, and the
 * frontend regression unit test hardcodes "backend returns newest-first" in a
 * mock — so only a real frontend against a real backend catches the desync.
 *
 * This drives the REAL frontend against a REAL gateway with two seeded runs and
 * NO checkpoint (the seeder forces the per-run reload path to be the sole source
 * of truth), then asserts the first run's message renders ABOVE the second's.
 * No model, no recording, no API key — the runs are seeded via a test-only
 * endpoint mounted only on the replay gateway.
 */
const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;

// Distinctive markers so getByText can't collide with UI chrome.
const ALPHA = "ALPHA-FIRST-QUESTION-7f3a2c";
const OMEGA = "OMEGA-SECOND-QUESTION-9b21d4";

test.describe("multi-run thread renders chronologically (replay, no API key)", () => {
  test("first run renders above second run after history rebuild (#3352)", async ({
    page,
    context,
  }) => {
    const uniq = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
    const threadId = `e2e-multi-run-${uniq}`;
    const email = `e2e-${uniq}@example.com`;

    // Register through the frontend origin (same-origin proxy) so the auth
    // cookies are stored for localhost and forwarded to the gateway via the
    // next.config rewrite — never cross-origin from the browser.
    const reg = await context.request.post(`${APP}/api/v1/auth/register`, {
      data: { email, password: "very-strong-password-123" },
    });
    expect(reg.status(), await reg.text()).toBe(201);

    const cookies = await context.cookies();
    const csrf = cookies.find((c) => c.name === "csrf_token")?.value;
    expect(csrf, "register must set csrf_token cookie").toBeTruthy();

    // Seed two runs in one thread: run-1 (ALPHA) older, run-2 (OMEGA) newer, so
    // the real backend's list_by_thread returns them newest-first. No checkpoint
    // is seeded — that is the #3352 precondition.
    const seed = await context.request.post(`${APP}/api/test-only/seed-runs`, {
      headers: { "X-CSRF-Token": csrf! },
      data: {
        thread_id: threadId,
        runs: [
          {
            run_id: `${threadId}-r1`,
            created_at: "2026-01-01T00:00:00+00:00",
            messages: [
              { role: "human", content: ALPHA, id: `${threadId}-a-h` },
              { role: "ai", content: "ALPHA reply", id: `${threadId}-a-a` },
            ],
          },
          {
            run_id: `${threadId}-r2`,
            created_at: "2026-01-01T00:01:00+00:00",
            messages: [
              { role: "human", content: OMEGA, id: `${threadId}-o-h` },
              { role: "ai", content: "OMEGA reply", id: `${threadId}-o-a` },
            ],
          },
        ],
      },
    });
    expect(seed.status(), await seed.text()).toBe(200);

    // Load the thread fresh — triggers useThreadHistory's per-run reload path.
    await page.goto(`/workspace/chats/${threadId}`);

    const alpha = page.getByText(ALPHA, { exact: false });
    const omega = page.getByText(OMEGA, { exact: false });
    await expect(alpha).toBeVisible({ timeout: 60_000 });
    await expect(omega).toBeVisible({ timeout: 30_000 });
    // Each marker renders exactly once (guards against accidental duplicate matches).
    expect(await alpha.count(), "ALPHA should render exactly once").toBe(1);
    expect(await omega.count(), "OMEGA should render exactly once").toBe(1);

    // The contract: ALPHA (first run) must render ABOVE OMEGA (second run). With
    // the #3352 bug the per-run rebuild inverts this and OMEGA renders first.
    const alphaBox = await alpha.first().boundingBox();
    const omegaBox = await omega.first().boundingBox();
    expect(alphaBox, "ALPHA must have a layout box").toBeTruthy();
    expect(omegaBox, "OMEGA must have a layout box").toBeTruthy();
    expect(
      alphaBox!.y,
      `chronological order broken: ALPHA(first run) rendered at y=${alphaBox!.y}, OMEGA(second run) at y=${omegaBox!.y} — backend list_by_thread ordering and frontend history rebuild are out of sync (#3352)`,
    ).toBeLessThan(omegaBox!.y);
  });
});
