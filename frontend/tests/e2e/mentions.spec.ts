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
  await expect(
    page.getByRole("button", { name: "Remove skill" }),
  ).toBeVisible();
  await expect(input).toHaveText("Use  carefully");
  await input.pressSequentially("it");
  await expect(input).toHaveText("Use it carefully");
  const request = nextRun(page);
  await input.press("Enter");
  expect(
    JSON.stringify((await request).postDataJSON().input.messages),
  ).toContain("/research Use it carefully");
  await expect(page.getByText("@research", { exact: true })).toBeVisible();
});
test("@ reopens after a skill, replaces it and restores the draft on reload", async ({
  page,
}) => {
  await page.goto("/workspace/chats/new");
  const input = composer(page);
  await input.fill("@res");
  await page.getByRole("option", { name: "research Research a topic" }).click();
  await input.fill("Keep this @wri");
  await page.getByRole("option", { name: "writing Write a report" }).click();
  await expect(input).toHaveText("Keep this ");
  await expect(page.getByText("@writing", { exact: true })).toBeVisible();
  await page.reload();
  await expect(input).toHaveText("Keep this ");
  await expect(page.getByText("@writing", { exact: true })).toBeVisible();
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
  await expect(input).toHaveValue("Read ");
  await expect(page).not.toHaveURL(/\/new/);
  await page.reload();
  await expect(page.getByTestId("project-attachment-chip")).toContainText(
    "report.pdf",
  );
  await expect(input).toHaveValue("Read ");
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
test("mouse upload entry and mobile picker stay usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/workspace/chats/new");
  await page.getByTestId("mention-button").click();
  const picker = page.getByTestId("mention-picker");
  await expect(picker).toBeVisible();
  const box = await picker.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "/private/tmp/mentions-mobile.png" });
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
