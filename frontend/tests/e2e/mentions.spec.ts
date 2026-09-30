import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const composer = (page: Page) =>
  page.getByRole("textbox", { name: /how can i assist you/i });
const nextRun = (page: Page) =>
  page.waitForRequest(
    (r) => r.method() === "POST" && r.url().includes("/runs/stream"),
  );
test.beforeEach(async ({ page }) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Writer brief",
        updated_at: "2026-09-01T00:00:00Z",
      },
    ],
    skills: [
      { name: "research", description: "Research a topic", enabled: true },
      { name: "writing", description: "Write a report", enabled: true },
    ],
    projects: [{ id: "proj-1", name: "Research project" }],
    projectDocuments: [
      { id: "doc-1", project_id: "proj-1", name: "report.pdf", size_bytes: 10 },
    ],
  });
  await page.route("**/api/features", (route) =>
    route.fulfill({
      json: {
        agents_api: { enabled: true },
        browser_control: { enabled: false },
        mcp_tasks: { enabled: false },
        knowledge_base: { scope_selection_enabled: false },
        conversation_references: { enabled: true, max_references: 3 },
      },
    }),
  );
});
test("mid-draft skill selection preserves both text and caret and submits the activation", async ({
  page,
}) => {
  await page.goto("/workspace/chats/new");
  const input = composer(page);
  await input.fill("Use  carefully");
  await input.press("Home");
  for (let i = 0; i < 4; i++) await input.press("ArrowRight");
  await input.pressSequentially("@res");
  await expect(
    page.getByRole("option", { name: "research Research a topic" }),
  ).toBeVisible();
  await input.press("Enter");
  await expect(page.getByTestId("inline-skill-reference")).toBeVisible();
  await expect(input).toHaveText("Use ✦research  carefully");
  await input.pressSequentially("it");
  await expect(input).toHaveText("Use ✦research it carefully");
  const request = nextRun(page);
  await input.press("Enter");
  expect(
    JSON.stringify((await request).postDataJSON().input.messages),
  ).toContain("Use @research it carefully");
});
test("keeps multiple inline skills and restores their positions on reload", async ({
  page,
}) => {
  await page.goto("/workspace/chats/new");
  const input = composer(page);
  await input.fill("@res");
  await page.getByRole("option", { name: "research Research a topic" }).click();
  await input.pressSequentially("Keep this @wri");
  await page.getByRole("option", { name: "writing Write a report" }).click();
  await expect(input).toHaveText("✦research Keep this ✦writing ");
  await page.reload();
  await expect(input).toHaveText("✦research Keep this ✦writing ");
  const request = nextRun(page);
  await input.press("Enter");
  const message = (await request).postDataJSON().input.messages.at(-1);
  expect(message.additional_kwargs.skill_references).toEqual([
    "research",
    "writing",
  ]);
});
test("emails and dismissed queries stay literal", async ({ page }) => {
  await page.goto("/workspace/chats/new");
  const input = composer(page);
  await input.fill("a@example.com");
  await expect(page.getByTestId("mention-picker")).toBeHidden();
  await input.fill("@res");
  await expect(page.getByTestId("mention-picker")).toBeVisible();
  await input.press("Escape");
  await expect(page.getByTestId("mention-picker")).toBeHidden();
  await expect(input).toHaveValue("@res");
});
test("attaches a document to a new project thread and submits its confirmed file", async ({
  page,
}) => {
  await page.goto("/workspace/chats/new?project=proj-1");
  const input = composer(page);
  await input.fill("Read @report");
  await page.getByRole("option", { name: "report.pdf" }).click();
  await expect(page.getByTestId("project-attachment-chip")).toContainText(
    "report.pdf",
  );
  await expect(input).toHaveText("Read ▤report.pdf ");
  await expect(page).not.toHaveURL(/\/new/);
  await page.reload();
  await expect(page.getByTestId("project-attachment-chip")).toContainText(
    "report.pdf",
  );
  await expect(input).toHaveText("Read ▤report.pdf ");
  const request = nextRun(page);
  await input.press("Enter");
  expect(
    JSON.stringify((await request).postDataJSON().input.messages),
  ).toContain("/mnt/user-data/uploads/report.pdf");
});
test("restores a conversation reference and sends its run-scoped ID", async ({
  page,
}) => {
  await page.goto("/workspace/chats/new");
  const input = composer(page);
  await input.fill("Summarize @Writer");
  await page.getByRole("option", { name: "Writer brief" }).click();
  await expect(page.getByTestId("conversation-reference-chip")).toContainText(
    "Writer brief",
  );
  await page.reload();
  await expect(page.getByTestId("conversation-reference-chip")).toContainText(
    "Writer brief",
  );
  const request = nextRun(page);
  await input.press("Enter");
  expect(
    (await request).postDataJSON().context.conversation_references,
  ).toEqual([MOCK_THREAD_ID]);
});
test("mouse upload entry and mobile picker stay usable", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/workspace/chats/new");
  await page.getByTestId("mention-button").click();
  const picker = page.getByTestId("mention-picker");
  await expect(picker).toBeVisible();
  const box = await picker.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("mentions-mobile.png") });
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("option", { name: "Upload a file" }).click();
  await (
    await chooser
  ).setFiles({
    name: "note.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("hello"),
  });
  await expect(page.getByText("note.txt", { exact: true })).toBeVisible();
});

for (const metadataState of ["pending", "failed"] as const) {
  test(`keeps confirmed project files after materialization when metadata is ${metadataState}`, async ({
    page,
  }) => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      /\/api\/(?:langgraph\/)?threads\/[^/]+$/,
      async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        if (metadataState === "pending") await pending;
        return route.fulfill({
          status: 503,
          json: { detail: "metadata unavailable" },
        });
      },
    );
    try {
      await page.goto("/workspace/chats/new?project=proj-1");
      await composer(page).fill("Read @report");
      await page.getByRole("option", { name: "report.pdf" }).click();
      await expect(page).not.toHaveURL(/\/new/);
      await expect(page.getByTestId("project-attachment-chip")).toBeVisible();
      await page.getByTestId("mention-button").click();
      await expect(
        page.getByRole("option", { name: "report.pdf" }),
      ).toBeVisible();
      await expect(
        page.getByText("Open a project chat to reference project files."),
      ).toBeHidden();
    } finally {
      release();
    }
  });
}

for (const enabledAfterRetry of [true, false]) {
  test(`preserves references across a failed discovery and retries to enabled=${enabledAfterRetry}`, async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");
    const input = composer(page);
    await input.fill("Summarize @Writer");
    await page.getByRole("option", { name: "Writer brief" }).click();
    await expect(page.getByTestId("conversation-reference-chip")).toBeVisible();
    let failed = true;
    await page.route("**/api/features", (route) =>
      failed
        ? route.fulfill({ status: 503, body: "Temporarily unavailable" })
        : enabledAfterRetry
          ? route.fallback()
          : route.fulfill({
              json: {
                agents_api: { enabled: true },
                conversation_references: { enabled: false, max_references: 0 },
              },
            }),
    );
    await page.reload();
    const retry = page.getByTestId("retry-conversation-capability");
    await expect(retry).toBeVisible();
    await expect(page.getByTestId("conversation-reference-chip")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Submit", exact: true }),
    ).toBeDisabled();
    await input.press("End");
    await input.pressSequentially("after retry");
    await expect
      .poll(() =>
        page.evaluate(() =>
          Object.values(sessionStorage).some(
            (value) =>
              value.includes("after retry") &&
              value.includes("ref:conversation:"),
          ),
        ),
      )
      .toBe(true);
    await page.reload();
    await expect(retry).toBeVisible();
    await expect(page.getByTestId("conversation-reference-chip")).toBeVisible();
    failed = false;
    await retry.click();
    await expect(retry).toBeHidden();
    await expect(
      page.getByRole("button", { name: "Submit", exact: true }),
    ).toBeEnabled();
    if (enabledAfterRetry)
      await expect(
        page.getByTestId("conversation-reference-chip"),
      ).toBeVisible();
    else
      await expect(
        page.getByTestId("conversation-reference-chip"),
      ).toBeHidden();
    const request = nextRun(page);
    await input.press("Enter");
    const body = (await request).postDataJSON();
    expect(body.context.conversation_references ?? []).toEqual(
      enabledAfterRetry ? [MOCK_THREAD_ID] : [],
    );
    expect(JSON.stringify(body.input.messages)).toContain("after retry");
  });
}

test("polish preserves reordered overlapping reference labels and their IDs", async ({
  page,
}) => {
  await page.route("**/api/input-polish", (route) =>
    route.fulfill({
      json: {
        rewritten_text: "Use @research-tools first, then @research.",
        changed: true,
      },
    }),
  );
  await page.goto("/workspace/chats/new");
  const input = composer(page);
  await input.fill(
    "Use @[research](ref:skill:research) after @[research-tools](ref:skill:research-tools)",
  );
  await expect(page.getByTestId("inline-skill-reference")).toHaveCount(2);
  await page.getByTestId("polish-input-button").click();
  await expect(input).toHaveText("Use ✦research-tools first, then ✦research.");
  await expect(
    page.getByTestId("inline-skill-reference").first(),
  ).toHaveAttribute(
    "data-reference",
    "@[research-tools](ref:skill:research-tools)",
  );
  const request = nextRun(page);
  await input.press("Enter");
  const message = (await request).postDataJSON().input.messages.at(-1);
  expect(message.additional_kwargs.skill_references).toEqual([
    "research-tools",
    "research",
  ]);
  expect(JSON.stringify(message)).toContain(
    "Use @research-tools first, then @research.",
  );
});
