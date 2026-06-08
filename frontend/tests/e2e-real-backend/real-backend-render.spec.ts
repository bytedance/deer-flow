import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * Layer 2: drive the REAL frontend against the REAL gateway (replay model, no
 * API key) and assert the browser renders the backend's data correctly.
 *
 * The prompt is read from the same fixture the gateway replays, so the input
 * hash matches and the recorded turns (write_file -> auto-title -> read_file ->
 * final answer) reproduce deterministically.
 */
// Register through the frontend origin (same-origin proxy) so the auth cookies
// are stored for and sent to localhost:3000 — the gateway is reached via the
// next.config rewrite, never cross-origin from the browser.
const APP = "http://localhost:3000";
const fixture = JSON.parse(
  readFileSync(
    join(
      here,
      "../../../backend/tests/fixtures/replay/write_read_file.ultra.json",
    ),
    "utf-8",
  ),
) as {
  prompt: string;
  turns: Array<{ output: { data: { content?: unknown } } }>;
};

const PROMPT = fixture.prompt;
// Derive the assertions from the fixture so a re-record auto-updates them. Both
// are model-generated strings absent from the user prompt, so a pass proves the
// replay drove the render (not a prompt echo): the first plain-text turn is the
// in-graph auto-title; the JSON-array turn is the follow-up suggestions.
const textTurns = fixture.turns
  .map((t) => t.output?.data?.content)
  .filter((c): c is string => typeof c === "string" && c.trim().length > 0);
const suggestionsRaw = textTurns.find((c) => c.trim().startsWith("["));
// Guarded parse: a bracket-prefixed turn that isn't a valid JSON string array
// falls back to "" so the `not.toBe("")` assertion below fails with a clear
// message instead of a generic JSON.parse throw.
const EXPECTED_SUGGESTION = ((): string => {
  if (!suggestionsRaw) return "";
  try {
    const arr: unknown = JSON.parse(suggestionsRaw);
    return Array.isArray(arr) && typeof arr[0] === "string" ? arr[0] : "";
  } catch {
    return "";
  }
})();
const EXPECTED_TITLE = textTurns.find((c) => !c.trim().startsWith("[")) ?? "";

test.describe("real backend render (replay, no API key)", () => {
  test.beforeEach(async ({ context }) => {
    // Throwaway test account: register sets access_token + csrf_token cookies in
    // the browser context (host-scoped to localhost, shared across ports), so
    // the frontend's SDK (credentials:include + X-CSRF-Token) authenticates.
    const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
    const resp = await context.request.post(`${APP}/api/v1/auth/register`, {
      data: { email, password: "very-strong-password-123" },
    });
    expect(resp.status(), await resp.text()).toBe(201);
  });

  test("renders the replayed auto-title + suggestions from a real backend", async ({
    page,
  }) => {
    // ultra mode so the context the frontend sends (is_plan_mode + subagent_enabled)
    // matches the recorded fixture; otherwise the replay input hash would miss.
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({ context: { mode: "ultra" } }),
      );
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 30_000 });
    await textarea.fill(PROMPT);
    await textarea.press("Enter");

    // Replay-only DOM assertions (derived from the fixture): both are
    // model-generated strings absent from the user prompt, so they render only if
    // the recorded turns replayed AND the real frontend rendered them — the
    // in-graph auto-title and the post-answer follow-up suggestion. Together they
    // prove the whole pipeline (replay backend -> real frontend render). The
    // record spec waits for the /suggestions response, so a re-recorded fixture
    // always captures the suggestion turn — a missing one is a broken recording
    // and must fail loud here, not pass silently.
    expect(
      EXPECTED_TITLE,
      "fixture should contain an auto-title turn",
    ).not.toBe("");
    expect(
      EXPECTED_SUGGESTION,
      "fixture should contain a suggestions turn (re-record; the record spec waits for /suggestions)",
    ).not.toBe("");
    await expect(page.getByText(EXPECTED_TITLE)).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByText(EXPECTED_SUGGESTION)).toBeVisible({
      timeout: 30_000,
    });

    // Visual regression is OS-sensitive (a macOS baseline won't match CI's
    // Linux render), so it's a local dev gate only; in CI we capture the render
    // as an artifact for human review instead of hard-asserting a cross-OS
    // baseline. The DOM assertions above are the CI gate.
    if (process.env.CI) {
      await page.screenshot({
        path: "test-results/real-backend-render.png",
        fullPage: true,
      });
    } else {
      await expect(page).toHaveScreenshot("real-backend-render.png", {
        maxDiffPixelRatio: 0.02,
        fullPage: true,
      });
    }
  });
});
