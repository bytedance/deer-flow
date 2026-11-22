import { expect, test, type Page } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

// Real Chromium MediaRecorder, with a synthetic microphone. Only the remote
// feature/transcription endpoints are replaced; no speech service is required.
test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  },
});

async function configure(
  page: Page,
  voice: unknown = {
    enabled: true,
    max_audio_bytes: 10485760,
    max_duration_seconds: 120,
  },
) {
  await page.route("**/api/features", (route) =>
    route.fulfill({
      json: {
        agents_api: { enabled: true },
        browser_control: { enabled: false },
        mcp_tasks: { enabled: false },
        knowledge_base: { scope_selection_enabled: false },
        voice_input: voice,
      },
    }),
  );
}

async function startRecording(page: Page) {
  await page.getByTestId("voice-input-button").click();
  await expect(page.getByTestId("voice-input-status")).toContainText(
    "Recording",
  );
  // Wait for a real encoded chunk, not just an empty MediaRecorder header.
  await page.waitForTimeout(400);
}

test.beforeEach(async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Another conversation" }],
  });
});

for (const [name, feature] of [
  ["missing", undefined],
  ["disabled", { enabled: false }],
  ["invalid", { enabled: true }],
] as const) {
  test(`${name} configuration hides the microphone and disables its shortcut`, async ({
    page,
  }) => {
    // Explicit undefined would select configure's default.
    await configure(page, feature ?? null);
    let uploads = 0;
    page.on("request", (r) => {
      if (r.url().endsWith("/voice-input/transcribe")) uploads++;
    });
    await page.goto("/workspace/chats/new");
    const input = page.getByPlaceholder(/how can i assist you/i);
    await input.fill("Draft");
    await input.press("Control+m");
    await expect(page.getByTestId("voice-input-button")).toHaveCount(0);
    await expect(page.getByTestId("voice-input-status")).toHaveCount(0);
    await expect(input).toHaveValue("Draft");
    expect(uploads).toBe(0);
  });
}

test("feature request failure hides the microphone", async ({ page }) => {
  await page.route("**/api/features", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/workspace/chats/new");
  await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible();
  await expect(page.getByTestId("voice-input-button")).toHaveCount(0);
});

test("records beside Send, uploads real audio once, then polishes the transcript", async ({
  page,
}, testInfo) => {
  await configure(page);
  let uploads = 0;
  let audioBytes = 0;
  let audioType = "";
  let polishedText: string | undefined;
  await page.route("**/api/voice-input/transcribe", (route) => {
    uploads++;
    audioBytes = route.request().postDataBuffer()?.length ?? 0;
    audioType = route.request().headers()["content-type"] ?? "";
    return route.fulfill({ json: { text: "research energy storage" } });
  });
  await page.route("**/api/input-polish", (route) => {
    polishedText = (route.request().postDataJSON() as { text: string }).text;
    return route.fulfill({
      json: {
        rewritten_text:
          "Please research energy storage and provide a structured report.",
        changed: true,
      },
    });
  });
  await page.goto("/workspace/chats/new");
  const input = page.getByPlaceholder(/how can i assist you/i);
  await input.fill("Task:");
  await expect(page.getByTestId("voice-input-button")).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("voice-input-entry.png") });
  await testInfo.attach("Configured voice input beside Send", {
    path: testInfo.outputPath("voice-input-entry.png"),
    contentType: "image/png",
  });
  await startRecording(page);
  await page.screenshot({
    path: testInfo.outputPath("voice-input-recording.png"),
  });
  await testInfo.attach("Recording status and cancel", {
    path: testInfo.outputPath("voice-input-recording.png"),
    contentType: "image/png",
  });
  await expect(input).toHaveValue("Task:");
  await expect(page.getByTestId("polish-input-button")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Submit", exact: true }),
  ).toBeDisabled();
  await input.press("Enter");
  await expect(input).toHaveValue("Task: research energy storage");
  expect(uploads).toBe(1);
  expect(audioBytes).toBeGreaterThan(100);
  expect(audioType).toContain("audio/webm");
  await page.getByTestId("polish-input-button").click();
  await expect.poll(() => polishedText).toBe("Task: research energy storage");
  await expect(input).toHaveValue(
    "Please research energy storage and provide a structured report.",
  );
  await page.getByTestId("polish-input-button").click();
  await expect(input).toHaveValue("Task: research energy storage");
  const micBox = (await page.getByTestId("voice-input-button").boundingBox())!;
  const sendBox = (await page
    .getByRole("button", { name: "Submit", exact: true })
    .boundingBox())!;
  expect(micBox.x + micBox.width).toBeLessThanOrEqual(sendBox.x);
  expect(sendBox.x - micBox.x).toBeLessThan(65);
});

test("cancel releases the microphone and preserves the draft without upload", async ({
  page,
}) => {
  await configure(page);
  let uploads = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/voice-input/transcribe")) uploads++;
  });
  await page.goto("/workspace/chats/new");
  const input = page.getByPlaceholder(/how can i assist you/i);
  await input.fill("Keep my draft");
  await startRecording(page);
  await input.press("Escape");
  await expect(page.getByTestId("voice-input-status")).toBeHidden();
  await expect(input).toHaveValue("Keep my draft");
  expect(uploads).toBe(0);
  await startRecording(page);
  await page.getByRole("button", { name: "Cancel voice input" }).click();
  await expect(page.getByTestId("voice-input-status")).toBeHidden();
});

test("transcription failure preserves the draft and allows retry", async ({
  page,
}) => {
  await configure(page);
  await page.route("**/api/voice-input/transcribe", (route) =>
    route.fulfill({ status: 502, json: { detail: "unavailable" } }),
  );
  await page.goto("/workspace/chats/new");
  const input = page.getByPlaceholder(/how can i assist you/i);
  await input.fill("Original");
  await startRecording(page);
  await input.press("Control+m");
  await expect(
    page.getByText("Voice input failed. Please try again."),
  ).toBeVisible();
  await expect(input).toHaveValue("Original");
  await expect(page.getByTestId("voice-input-status")).toBeHidden();
  await startRecording(page);
});

for (const action of ["edit", "navigate"] as const) {
  test(`${action} while transcribing ignores the late response`, async ({
    page,
  }) => {
    await configure(page);
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    await page.route("**/api/voice-input/transcribe", async (route) => {
      await pending;
      await route
        .fulfill({ json: { text: "stale result" } })
        .catch(() => undefined);
    });
    await page.goto("/workspace/chats/new");
    const input = page.getByPlaceholder(/how can i assist you/i);
    await input.fill("Draft");
    await startRecording(page);
    await input.press("Enter");
    await expect(page.getByTestId("voice-input-status")).toContainText(
      "Transcribing",
    );
    if (action === "edit") await input.fill("My edited draft");
    else {
      await page
        .getByRole("link", { name: "Another conversation", exact: true })
        .click();
      await expect(page).toHaveURL(new RegExp(`/chats/${MOCK_THREAD_ID}$`));
    }
    finish();
    await expect(page.getByTestId("voice-input-status")).toBeHidden();
    await expect(input).toHaveValue(action === "edit" ? "My edited draft" : "");
  });
}

test("recording stops automatically at the configured duration", async ({
  page,
}) => {
  await configure(page, {
    enabled: true,
    max_audio_bytes: 10485760,
    max_duration_seconds: 1,
  });
  await page.route("**/api/voice-input/transcribe", (route) =>
    route.fulfill({ json: { text: "Automatic stop" } }),
  );
  await page.goto("/workspace/chats/new");
  await startRecording(page);
  await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
    "Automatic stop",
  );
});

test("mobile recording and cancel remain accessible in both themes", async ({
  page,
}, testInfo) => {
  await configure(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/workspace/chats/new");
  expect(
    (await page.getByTestId("voice-input-button").boundingBox())!.height,
  ).toBeGreaterThanOrEqual(44);
  await startRecording(page);
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await expect(page.locator("html")).toHaveCSS("color-scheme", theme);
    const cancel = page.getByRole("button", { name: "Cancel voice input" });
    expect((await cancel.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(390);
    await page.screenshot({ path: testInfo.outputPath(`voice-${theme}.png`) });
  }
  await page.getByRole("button", { name: "Cancel voice input" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("voice-input-status")).toBeHidden();
});
