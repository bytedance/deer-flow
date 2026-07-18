import { existsSync, readFileSync, writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * RECORD driver (Plan A): drive the real frontend through the write/read-file
 * scenario against the real-model gateway. The gateway captures every model
 * call to DEERFLOW_RECORD_OUT; this just needs to drive the flow and wait until
 * the captures stop arriving (main turns + follow-up suggestions all fired;
 * the default auto-title is local state). It asserts nothing about content —
 * it produces the fixture, it doesn't verify it.
 */
const APP = "http://localhost:3000";
const SCENARIO = "write_read_file";
const MODE = "ultra";
const PROMPT =
  "Using your own file tools directly, create the file /mnt/user-data/outputs/note.txt " +
  "with exactly this content: hi from replay. Then read that same file back and reply with its " +
  "exact contents. Do NOT delegate to a subagent and do NOT use the task tool — do it yourself. " +
  "Do not ask any clarifying questions.";

function countLines(path: string): number {
  return existsSync(path)
    ? readFileSync(path, "utf-8")
        .split("\n")
        .filter((l) => l.trim()).length
    : 0;
}

async function waitForCaptureStable(
  path: string,
  { stableMs = 12_000, maxMs = 160_000 } = {},
): Promise<number> {
  const start = Date.now();
  let last = -1;
  let lastChange = Date.now();
  while (Date.now() - start < maxMs) {
    const n = countLines(path);
    if (n !== last) {
      last = n;
      lastChange = Date.now();
    } else if (n > 0 && Date.now() - lastChange > stableMs) {
      return n;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  // Hard failure on timeout: returning the last count here would let a
  // truncated/partial recording pass silently (captured > 0). A recording must
  // stabilize, or it is not trustworthy.
  throw new Error(
    `[record] captures never stabilized within ${maxMs}ms (last count=${last}); ` +
      `the recording may be truncated — raise maxMs or check the record gateway.`,
  );
}

test.describe.configure({ timeout: 220_000 });

test("record write/read-file run through the real frontend", async ({
  page,
  context,
}) => {
  const out = process.env.DEERFLOW_RECORD_OUT;
  expect(out, "DEERFLOW_RECORD_OUT must be set").toBeTruthy();
  // The context the frontend derives for ultra mode (core/threads/hooks.ts). The
  // backend-direct golden test (Layer 1) POSTs this so its prompt — hence the
  // recorded input hashes — matches the browser run. thinking/reasoning don't
  // affect the prompt; is_plan_mode + subagent_enabled add the todo/task tools.
  const CONTEXT = {
    is_bootstrap: false,
    mode: MODE,
    thinking_enabled: true,
    is_plan_mode: true,
    subagent_enabled: true,
  };
  writeFileSync(
    `${out}.meta.json`,
    JSON.stringify({
      scenario: SCENARIO,
      mode: MODE,
      prompt: PROMPT,
      context: CONTEXT,
    }),
    "utf-8",
  );

  const reg = await context.request.post(`${APP}/api/v1/auth/register`, {
    data: {
      email: `rec-${Date.now()}@example.com`,
      password: "very-strong-password-123",
    },
  });
  expect(reg.status(), await reg.text()).toBe(201);

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

  // Suggestions fire only AFTER the run completes (input-box.tsx POSTs
  // /suggestions). Wait for that response so its model call lands in the capture
  // before we check for stability — otherwise the stability window can return
  // first and the recorded fixture would be missing the suggestions turn.
  await page
    .waitForResponse((r) => r.url().includes("/suggestions"), {
      timeout: 90_000,
    })
    .catch(() => undefined);

  const captured = await waitForCaptureStable(out!);
  console.log(
    `[record] captures stabilized at ${captured} model call(s) -> ${out}`,
  );
  expect(
    captured,
    "expected at least the agent turns to be captured",
  ).toBeGreaterThan(0);
});
