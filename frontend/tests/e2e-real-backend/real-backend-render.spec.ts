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
 * hash matches and the recorded model turns reproduce deterministically. The
 * default auto-title is local fallback state, not a replayed model turn.
 */
// Register through the frontend origin (same-origin proxy) so the auth cookies
// are stored for and sent to the browser origin — the gateway is reached via the
// next.config rewrite, never cross-origin from the browser.
const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;
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
const FALLBACK_TITLE_MAX_CHARS = 50;

function fallbackTitle(userMsg: string): string {
  if (!userMsg) return "New Conversation";
  if (userMsg.length <= FALLBACK_TITLE_MAX_CHARS) return userMsg;
  return `${userMsg.slice(0, FALLBACK_TITLE_MAX_CHARS).trimEnd()}...`;
}

// Suggestions still come from the recorded model fixture. The default title no
// longer does: TitleMiddleware uses a local fallback when title.model_name is
// unset, so derive that expected title from the prompt.
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
const EXPECTED_TITLE = fallbackTitle(PROMPT);

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

  test("renders the local auto-title + replayed suggestions from a real backend", async ({
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

    // The title is the default local fallback, while the suggestion is a
    // replayed model output absent from the prompt. Together they prove the
    // backend state update and the replayed post-answer model call both render
    // through the real frontend.
    expect(
      EXPECTED_TITLE,
      "default local fallback title should be derived from the prompt",
    ).not.toBe("");
    expect(
      EXPECTED_SUGGESTION,
      "fixture should contain a suggestions turn (re-record; the record spec waits for /suggestions)",
    ).not.toBe("");
    const chat = page.locator("#chat");
    await expect(chat.getByText(EXPECTED_TITLE)).toBeVisible({
      timeout: 60_000,
    });
    await expect(chat.getByText(EXPECTED_SUGGESTION)).toBeVisible({
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
