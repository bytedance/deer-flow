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

  test("polishes draft input before sending", async ({ page }) => {
    let polishRequest: { text?: string; model_name?: string } | undefined;
    let submittedText: string | undefined;
    let finishPolish!: () => void;
    const polishCanFinish = new Promise<void>((resolve) => {
      finishPolish = resolve;
    });

    await page.route("**/api/input-polish", async (route) => {
      polishRequest = route.request().postDataJSON() as {
        text?: string;
        model_name?: string;
      };
      await polishCanFinish;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          rewritten_text: "Please summarize the uploaded report clearly.",
          changed: true,
        }),
      });
    });
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

    await textarea.fill("summarize report");
    await page.getByTestId("polish-input-button").click();

    await expect
      .poll(() => polishRequest?.text, { timeout: 10_000 })
      .toBe("summarize report");
    expect(polishRequest?.model_name).toBeUndefined();
    await expect(textarea).toBeDisabled();
    await expect(page.getByText("Polishing input...")).toBeVisible();

    finishPolish();

    await expect(textarea).toHaveValue(
      "Please summarize the uploaded report clearly.",
    );
    await expect(textarea).toBeEnabled();
    await expect(page.getByTestId("polish-input-button")).toHaveAccessibleName(
      "Undo polish",
    );

    await textarea.press("Enter");

    await expect
      .poll(() => submittedText, { timeout: 10_000 })
      .toBe("Please summarize the uploaded report clearly.");
  });

  test("undoes polished draft from the polish button", async ({ page }) => {
    await page.route("**/api/input-polish", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          rewritten_text: "Please summarize the uploaded report clearly.",
          changed: true,
        }),
      }),
    );

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("summarize report");
    await page.getByTestId("polish-input-button").click();

    await expect(textarea).toHaveValue(
      "Please summarize the uploaded report clearly.",
    );

    const polishButton = page.getByTestId("polish-input-button");
    await expect(polishButton).toHaveAccessibleName("Undo polish");
    await polishButton.click();

    await expect(textarea).toHaveValue("summarize report");
    await expect(polishButton).toHaveAccessibleName("Polish input");
  });

  test("cancels an in-flight polish request", async ({ page }) => {
    // Hold the polish response open so the request stays in flight while we
    // exercise the cancel affordance.
    let releasePolish!: () => void;
    const polishHeld = new Promise<void>((resolve) => {
      releasePolish = resolve;
    });
    await page.route("**/api/input-polish", async (route) => {
      await polishHeld;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          rewritten_text: "Please summarize the uploaded report clearly.",
          changed: true,
        }),
      });
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("summarize report");
    await page.getByTestId("polish-input-button").click();

    await expect(page.getByText("Polishing input...")).toBeVisible();
    await expect(textarea).toBeDisabled();

    await page.getByTestId("cancel-polish-input-button").click();

    // Cancelling aborts the request, re-enables the composer, and leaves the
    // original draft untouched (no rewrite applied).
    await expect(page.getByText("Polishing input...")).toBeHidden();
    await expect(textarea).toBeEnabled();
    await expect(textarea).toHaveValue("summarize report");
    await expect(page.getByTestId("polish-input-button")).toHaveAccessibleName(
      "Polish input",
    );

    releasePolish();
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

  test("goal command sets a goal and starts an agent run", async ({ page }) => {
    let streamCalls = 0;
    await page.goto("/workspace/chats/new");
    await page.route("**/runs/stream", (route) => {
      streamCalls += 1;
      return route.fallback();
    });

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/go");
    await expect(page.getByRole("option", { name: /goal/i })).toBeVisible();

    await textarea.fill("/goal finish all tests");
    await textarea.press("Enter");

    await expect(
      page.locator("span.font-medium", { hasText: "finish all tests" }),
    ).toBeVisible();
    await expect.poll(() => streamCalls).toBe(1);
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible();
  });

  test("goal command keeps the welcome header clear of the goal status", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill(
      "/goal finish a small repo check and report the result",
    );
    await textarea.press("Enter");

    const goal = page.locator("span.font-medium", {
      hasText: "finish a small repo check",
    });
    await expect(goal).toBeVisible();
    await expect(page.getByText(/welcome to/i)).toBeHidden();

    const overlaps = await page.evaluate(() => {
      const welcome = [...document.querySelectorAll("p")].find((el) =>
        el.textContent?.toLowerCase().includes("welcome to"),
      );
      const goal = [...document.querySelectorAll("span")].find((el) =>
        el.textContent?.includes(
          "finish a small repo check and report the result",
        ),
      );
      if (!welcome || !goal) {
        return false;
      }
      const welcomeRect = welcome.getBoundingClientRect();
      const goalRect = goal.getBoundingClientRect();
      return !(
        welcomeRect.right < goalRect.left ||
        goalRect.right < welcomeRect.left ||
        welcomeRect.bottom < goalRect.top ||
        goalRect.bottom < welcomeRect.top
      );
    });
    expect(overlaps).toBe(false);
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

  test("shows gateway upload limits on the attachment entry point", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const addAttachments = page.getByTestId("add-attachments-button");
    await expect(addAttachments).toBeVisible({ timeout: 15_000 });
    await addAttachments.hover();

    await expect(page.getByRole("tooltip")).toContainText("50 MiB");
    await expect(page.getByRole("tooltip")).toContainText("100 MiB");
  });

  test("rejects an oversized attachment before upload", async ({ page }) => {
    let uploadCalled = false;
    await page.route("**/api/threads/*/uploads", (route) => {
      if (route.request().method() === "POST") {
        uploadCalled = true;
      }
      return route.fallback();
    });
    await page.route("**/api/threads/*/uploads/limits", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          max_files: 10,
          max_file_size: 5,
          max_total_size: 20,
        }),
      }),
    );

    await page.goto("/workspace/chats/new");
    const addAttachments = page.getByTestId("add-attachments-button");
    await addAttachments.hover();
    await expect(page.getByRole("tooltip")).toContainText("5 B");

    await page.getByLabel("Upload files").setInputFiles({
      name: "too-large.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("123456"),
    });

    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "too-large.txt" }),
    ).toBeVisible();
    await expect(page.locator("form").getByText("too-large.txt")).toBeHidden();

    const textarea = page.locator('textarea[name="message"]');
    await textarea.fill("Continue without the rejected attachment");
    await textarea.press("Enter");
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
    expect(uploadCalled).toBe(false);
  });

  test("keeps valid attachments in order when the total limit is exceeded", async ({
    page,
  }) => {
    await page.route("**/api/threads/*/uploads/limits", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          max_files: 3,
          max_file_size: 10,
          max_total_size: 5,
        }),
      }),
    );

    await page.goto("/workspace/chats/new");
    const addAttachments = page.getByTestId("add-attachments-button");
    await addAttachments.hover();
    await expect(page.getByRole("tooltip")).toContainText("5 B");

    await page.getByLabel("Upload files").setInputFiles([
      {
        name: "first.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("1234"),
      },
      {
        name: "over-total.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("12"),
      },
      {
        name: "second.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("1"),
      },
    ]);

    const promptForm = page.locator("form").filter({
      has: page.locator('textarea[name="message"]'),
    });
    await expect(promptForm.getByText("first.txt")).toBeVisible();
    await expect(promptForm.getByText("second.txt")).toBeVisible();
    await expect(promptForm.getByText("over-total.txt")).toBeHidden();
    await expect(
      page.locator("[data-sonner-toast]").filter({ hasText: "5 B" }),
    ).toBeVisible();
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
