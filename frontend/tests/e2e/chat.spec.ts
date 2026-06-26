import { expect, test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

test.describe("Chat workspace", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("new chat page loads with input box", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /load more/i })).toBeHidden();
  });

  test("can type a message in the input box", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Hello, DeerFlow!");
    await expect(textarea).toHaveValue("Hello, DeerFlow!");
  });

  test("suggests matching skills after a leading slash", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/dat");
    await expect(
      page.getByRole("option", { name: /data-analysis/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("option", { name: /disabled-skill/i }),
    ).toBeHidden();

    await textarea.press("Enter");

    await expect(textarea).toHaveValue("/data-analysis ");
  });

  test("uses arrow keys to navigate skill suggestions before prompt history", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/");

    const dataAnalysis = page.getByRole("option", {
      name: /data-analysis/i,
    });
    const frontendDesign = page.getByRole("option", {
      name: /frontend-design/i,
    });
    await expect(dataAnalysis).toBeVisible();
    await expect(frontendDesign).toBeVisible();
    await expect(dataAnalysis).toHaveAttribute("aria-selected", "true");

    await textarea.press("ArrowDown");

    await expect(textarea).toHaveValue("/");
    await expect(dataAnalysis).toHaveAttribute("aria-selected", "false");
    await expect(frontendDesign).toHaveAttribute("aria-selected", "true");

    await textarea.press("ArrowUp");

    await expect(textarea).toHaveValue("/");
    await expect(dataAnalysis).toHaveAttribute("aria-selected", "true");
    await expect(frontendDesign).toHaveAttribute("aria-selected", "false");

    await textarea.press("ArrowDown");
    await textarea.press("Enter");

    await expect(textarea).toHaveValue("/frontend-design ");
  });

  test("keeps Shift+Enter as newline while skill suggestions are visible", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/dat");
    await expect(
      page.getByRole("option", { name: /data-analysis/i }),
    ).toBeVisible();

    await textarea.press("Shift+Enter");

    await expect(textarea).toHaveValue("/dat\n");
    await expect(
      page.getByRole("option", { name: /data-analysis/i }),
    ).toBeHidden();
  });

  test("does not suggest skills for slash text away from the prompt start", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("please /dat");

    await expect(
      page.getByRole("option", { name: /data-analysis/i }),
    ).toBeHidden();
  });

  test("sending a message triggers API call and shows response", async ({
    page,
  }) => {
    let streamCalled = false;
    await page.route("**/runs/stream", (route) => {
      streamCalled = true;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Hello");
    await textarea.press("Enter");

    await expect.poll(() => streamCalled, { timeout: 10_000 }).toBeTruthy();

    // The AI response should appear in the chat
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("blocks suggestion template placeholders until replaced", async ({
    page,
  }) => {
    let streamCalled = false;
    let submittedText: string | undefined;
    await page.route("**/runs/stream", (route) => {
      streamCalled = true;
      const body = route.request().postDataJSON() as {
        input?: { messages?: Array<{ content?: unknown }> };
      };
      const content = body.input?.messages?.at(-1)?.content;
      if (typeof content === "string") {
        submittedText = content;
      } else if (Array.isArray(content)) {
        submittedText = content
          .map((block) =>
            typeof block === "object" &&
            block !== null &&
            "text" in block &&
            typeof block.text === "string"
              ? block.text
              : "",
          )
          .join("");
      }
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /research/i }).click();
    await expect(textarea).toHaveValue(
      "Conduct a deep dive research on [topic], and summarize the findings.",
    );

    await textarea.press("Enter");
    await page.waitForTimeout(500);

    expect(streamCalled).toBe(false);
    await expect(textarea).toHaveValue(
      "Conduct a deep dive research on [topic], and summarize the findings.",
    );
    await expect
      .poll(
        () =>
          textarea.evaluate((element) => {
            const input = element as HTMLTextAreaElement;
            return input.value.slice(input.selectionStart, input.selectionEnd);
          }),
        { timeout: 5_000 },
      )
      .toBe("[topic]");

    await textarea.pressSequentially("AI agents");
    await expect(textarea).toHaveValue(
      "Conduct a deep dive research on AI agents, and summarize the findings.",
    );

    await textarea.press("Enter");

    await expect.poll(() => streamCalled, { timeout: 10_000 }).toBeTruthy();
    await expect
      .poll(() => submittedText, { timeout: 10_000 })
      .toBe(
        "Conduct a deep dive research on AI agents, and summarize the findings.",
      );
  });

  test("slash skill command is submitted as normal chat text", async ({
    page,
  }) => {
    const slashCommand = "/data-analysis analyze uploads/foo.csv";
    let submittedText: string | undefined;
    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        input?: { messages?: Array<{ content?: unknown }> };
      };
      const content = body.input?.messages?.at(-1)?.content;
      if (typeof content === "string") {
        submittedText = content;
      } else if (Array.isArray(content)) {
        submittedText = content
          .map((block) =>
            typeof block === "object" &&
            block !== null &&
            "text" in block &&
            typeof block.text === "string"
              ? block.text
              : "",
          )
          .join("");
      }
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill(slashCommand);
    await textarea.press("Enter");

    await expect
      .poll(() => submittedText, { timeout: 10_000 })
      .toBe(slashCommand);
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("slash skill command with attachment preserves command text and file metadata", async ({
    page,
  }) => {
    const slashCommand = "/data-analysis analyze report.docx";
    let uploadCalled = false;
    let submittedText: string | undefined;
    let submittedFiles:
      | Array<{ filename?: string; path?: string; status?: string }>
      | undefined;

    await page.route("**/api/threads/*/uploads", async (route) => {
      uploadCalled = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Uploaded",
          files: [
            {
              filename: "report.docx",
              size: 12,
              path: "report.docx",
              virtual_path: "/mnt/user-data/uploads/report.docx",
              artifact_url: "/api/threads/test/uploads/report.docx",
              extension: ".docx",
            },
          ],
        }),
      });
    });

    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        input?: {
          messages?: Array<{
            content?: unknown;
            additional_kwargs?: {
              files?: Array<{
                filename?: string;
                path?: string;
                status?: string;
              }>;
            };
          }>;
        };
      };
      const message = body.input?.messages?.at(-1);
      const content = message?.content;
      if (typeof content === "string") {
        submittedText = content;
      } else if (Array.isArray(content)) {
        submittedText = content
          .map((block) =>
            typeof block === "object" &&
            block !== null &&
            "text" in block &&
            typeof block.text === "string"
              ? block.text
              : "",
          )
          .join("");
      }
      submittedFiles = message?.additional_kwargs?.files;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await page.getByLabel("Upload files").setInputFiles({
      name: "report.docx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: Buffer.from("fake docx"),
    });

    await textarea.fill(slashCommand);
    await textarea.press("Enter");

    await expect.poll(() => uploadCalled, { timeout: 10_000 }).toBeTruthy();
    await expect
      .poll(() => submittedText, { timeout: 10_000 })
      .toBe(slashCommand);
    await expect
      .poll(() => submittedFiles, { timeout: 10_000 })
      .toEqual([
        {
          filename: "report.docx",
          size: 12,
          path: "/mnt/user-data/uploads/report.docx",
          status: "uploaded",
        },
      ]);
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("keeps attachments visible while upload submit is pending", async ({
    page,
  }) => {
    let releaseUpload!: () => void;
    const uploadCanFinish = new Promise<void>((resolve) => {
      releaseUpload = resolve;
    });
    let uploadStarted!: () => void;
    const uploadStartedPromise = new Promise<void>((resolve) => {
      uploadStarted = resolve;
    });

    await page.route("**/api/threads/*/uploads", async (route) => {
      uploadStarted();
      await uploadCanFinish;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Uploaded",
          files: [
            {
              filename: "report.docx",
              size: 12,
              path: "report.docx",
              virtual_path: "/mnt/user-data/uploads/report.docx",
              artifact_url: "/api/threads/test/uploads/report.docx",
              extension: ".docx",
            },
          ],
        }),
      });
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    const promptForm = page.locator("form").filter({ has: textarea });

    await page.getByLabel("Upload files").setInputFiles({
      name: "report.docx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: Buffer.from("fake docx"),
    });
    await expect(promptForm.getByText("report.docx")).toBeVisible();

    await textarea.fill("Summarize this document");
    await textarea.press("Enter");

    await uploadStartedPromise;
    await expect(promptForm.getByText("report.docx")).toBeVisible();

    releaseUpload();
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
    await expect(promptForm.getByText("report.docx")).toBeHidden();
  });

  test("does not fetch follow-up suggestions when disabled in config", async ({
    page,
  }) => {
    await page.route("**/api/suggestions/config", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false }),
      });
    });

    let suggestionsFetched = false;
    await page.route("**/api/threads/*/suggestions", (route) => {
      suggestionsFetched = true;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ suggestions: [] }),
      });
    });

    let streamCalled = false;
    await page.route("**/runs/stream", (route) => {
      streamCalled = true;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Hello");
    await textarea.press("Enter");

    await expect.poll(() => streamCalled, { timeout: 10_000 }).toBeTruthy();
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
    await page.waitForTimeout(1000);
    expect(suggestionsFetched).toBe(false);
  });
});
