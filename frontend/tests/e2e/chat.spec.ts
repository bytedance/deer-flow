import { expect, test, type Page, type Route } from "@playwright/test";

import {
  handleRunStream,
  MOCK_THREAD_ID,
  mockLangGraphAPI,
} from "./utils/mock-api";

test.describe("Project-scoped submit staleness", () => {
  test.beforeEach(async ({ page }) => {
    // A settled conversation to switch to mid-submit. Seeded at setup (not
    // created during the test): opening a session-created thread page in the
    // mock races the empty-thread redirect, while a setup-seeded thread is
    // the stable pattern other specs rely on.
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Settled chat",
          updated_at: "2025-06-01T12:00:00Z",
        },
      ],
    });
  });

  function holdThreadCreate(page: Page) {
    let releaseCreate!: () => void;
    let markIntercepted!: () => void;
    const intercepted = new Promise<void>((resolve) => {
      markIntercepted = resolve;
    });
    const createHeld = new Promise<void>((resolve) => {
      releaseCreate = resolve;
    });
    void page.route("**/api/threads", async (route) => {
      if (route.request().method() === "POST") {
        markIntercepted();
        await createHeld;
      }
      return route.fallback();
    });
    return { intercepted, releaseCreate };
  }

  test("switching conversations during goal preparation drops the stale continuation", async ({
    page,
  }) => {
    // Regression: the goal PUT registers its AbortController only after the
    // project pre-create resolves, so the thread-change cleanup cannot abort
    // an in-flight prepare. Navigating away while preparation is pending
    // must drop the continuation — no goal save, composer clear, or
    // abandoned run may touch the newly opened conversation.
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    const settledChat = page.getByRole("link", {
      name: "Settled chat",
      exact: true,
    });

    const goalPuts: string[] = [];
    const runStreams: string[] = [];
    page.on("request", (request) => {
      const url = request.url();
      if (
        request.method() === "PUT" &&
        /\/api\/threads\/[^/]+\/goal$/.test(url)
      ) {
        goalPuts.push(url);
      }
      if (request.method() === "POST" && url.includes("/runs/stream")) {
        runStreams.push(url);
      }
    });
    const { intercepted, releaseCreate } = holdThreadCreate(page);

    await page.goto("/workspace/chats/new?project=proj-1");
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("/goal finish all tests");
    await textarea.press("Enter");
    // The project pre-create must actually be in flight before we navigate:
    // releasing a request that was never intercepted would make the
    // assertions pass without exercising the stale continuation at all.
    await intercepted;

    // Switch conversations while the project pre-create is held.
    await settledChat.click();
    await expect(page).toHaveURL(new RegExp(`/chats/${MOCK_THREAD_ID}$`));
    releaseCreate();
    // Let any stale continuation run to completion before asserting: a goal
    // PUT that fires late must still be caught.
    await page.waitForTimeout(1500);
    await expect(page.getByText("finish all tests")).toBeHidden();
    await expect.poll(() => goalPuts.length).toBe(0);
    await expect.poll(() => runStreams.length).toBe(0);
    await expect(page).toHaveURL(new RegExp(`/chats/${MOCK_THREAD_ID}$`));
  });

  test("dropping the project scope mid-submission resets the thread identity", async ({
    page,
  }) => {
    // Regression: the sidebar "New chat" link leaves /new?project=… for
    // plain /new without a pathname change, so the thread identity and the
    // submission fences keyed on `threadId` survive the navigation. The
    // abandoned submission must not start a run against the previous
    // scope's pre-created thread or rewrite the URL to it.
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    const runStreams: string[] = [];
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        request.url().includes("/runs/stream")
      ) {
        runStreams.push(request.url());
      }
    });
    const { intercepted, releaseCreate } = holdThreadCreate(page);

    await page.goto("/workspace/chats/new?project=proj-1");
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("run inside the project");
    await textarea.press("Enter");
    // The project pre-create must be in flight before navigating away.
    await intercepted;

    await page.getByRole("link", { name: "New chat", exact: true }).click();
    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
    releaseCreate();

    // The stale submission must not start a run for the previous scope's
    // identity, nor rewrite the URL to it.
    await page.waitForTimeout(1500);
    await expect.poll(() => runStreams.length).toBe(0);
    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
  });
});

function textFromMessageContent(content: unknown) {
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return undefined;
  }
  return content
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

test.describe("Streaming message actions", () => {
  test("keeps a completed answer copyable while the next turn starts", async ({
    page,
  }) => {
    let streamCalls = 0;
    let releaseSecondStream!: () => void;
    const secondStreamHeld = new Promise<void>((resolve) => {
      releaseSecondStream = resolve;
    });

    const handleCopyRegressionStream = async (route: Route) => {
      streamCalls += 1;
      if (streamCalls === 2) {
        await secondStreamHeld;
      }
      return handleRunStream(route, {}, undefined, {
        responseMessage: {
          type: "ai",
          id: `copy-regression-ai-${streamCalls}`,
          content:
            streamCalls === 1 ? "First completed answer" : "Second answer",
        },
        messageMetadata: {
          langgraph_node: "agent",
          langgraph_step: streamCalls,
        },
      });
    };
    mockLangGraphAPI(page, {
      createdThreadMessages: [
        {
          type: "human",
          id: "copy-regression-human-1",
          content: "First question",
        },
        {
          type: "ai",
          id: "copy-regression-ai-1",
          content: "First completed answer",
        },
      ],
      runStreamHandler: handleCopyRegressionStream,
    });

    try {
      await page.goto("/workspace/chats/new");
      const textarea = page.getByPlaceholder(/how can i assist you/i);
      await expect(textarea).toBeVisible({ timeout: 15_000 });

      await textarea.fill("First question");
      await textarea.press("Enter");
      await expect.poll(() => streamCalls).toBe(1);
      await expect(page.getByText("First completed answer")).toBeVisible({
        timeout: 10_000,
      });

      await textarea.fill("Second question");
      await textarea.press("Enter");
      await expect.poll(() => streamCalls).toBe(2);

      const completedTurn = page
        .locator('[data-assistant-turn=""]')
        .filter({ hasText: "First completed answer" });
      await completedTurn.hover();
      await expect(
        completedTurn.getByRole("button", { name: "Copy to clipboard" }),
      ).toBeVisible();
    } finally {
      releaseSecondStream();
    }
  });
});

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

  test("shows the localized AI disclaimer", async ({ page }) => {
    await page.goto("/workspace/chats/new");
    await page.evaluate(() => {
      document.cookie = "locale=zh-CN; path=/; SameSite=Lax";
    });
    await page.reload();

    await expect(
      page.getByText("内容由AI生成，重要信息请务必核查", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("can type a message in the input box", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("Hello, DeerFlow!");
    await expect(textarea).toHaveValue("Hello, DeerFlow!");
  });

  test("restores a draft after reload and clears it after sending", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Keep this unfinished draft");

    await page.reload();

    const restoredTextarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(restoredTextarea).toHaveValue("Keep this unfinished draft");
    await restoredTextarea.press("Enter");
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });

    await page.reload();
    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      "",
    );
  });

  test("restores a repeated draft that matches the last sent prompt", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Repeat this request");
    await textarea.press("Enter");
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
    await expect(textarea).toHaveValue("");

    await textarea.fill("Repeat this request");
    await expect
      .poll(() =>
        page.evaluate(() => Object.values(window.sessionStorage).join("\n")),
      )
      .toContain("Repeat this request");

    await page.reload();
    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      "Repeat this request",
    );
  });

  test("restores an inline skill draft after reload", async ({ page }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("@dat");
    await textarea.press("Enter");

    await expect(page.getByTestId("inline-skill-reference")).toBeVisible();
    const skillInput = page.getByRole("textbox", {
      name: /how can i assist you/i,
    });
    await skillInput.pressSequentially("Analyze the latest results");
    await expect
      .poll(() =>
        page.evaluate(() => Object.values(window.sessionStorage).join("\n")),
      )
      .toContain("Analyze the latest results");

    await page.reload();

    await expect(page.getByTestId("inline-skill-reference")).toBeVisible();
    await expect(
      page.getByRole("textbox", {
        name: /how can i assist you/i,
      }),
    ).toHaveText("✦data-analysis Analyze the latest results");
  });

  test("continues without draft persistence when sessionStorage is blocked", async ({
    page,
  }) => {
    let submittedText: string | undefined;
    await page.addInitScript(() => {
      const realSessionStorage = window.sessionStorage;
      Reflect.set(window, "__blockComposerDraftStorage", false);
      Object.defineProperty(window, "sessionStorage", {
        configurable: true,
        get() {
          if (Reflect.get(window, "__blockComposerDraftStorage") === true) {
            throw new DOMException("Blocked", "SecurityError");
          }
          return realSessionStorage;
        },
      });
    });
    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        input?: { messages?: Array<{ content?: unknown }> };
      };
      const content = body.input?.messages?.at(-1)?.content;
      submittedText = textFromMessageContent(content);
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await page.evaluate(() => {
      Reflect.set(window, "__blockComposerDraftStorage", true);
    });
    await textarea.fill("Send while storage is blocked");
    await textarea.press("Enter");

    await expect
      .poll(() => submittedText, { timeout: 10_000 })
      .toBe("Send while storage is blocked");
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("does not rewrite an accepted attachment draft from a stale debounce", async ({
    page,
  }) => {
    let releaseUpload!: () => void;
    const uploadHeld = new Promise<void>((resolve) => {
      releaseUpload = resolve;
    });
    let submittedText: string | undefined;

    await page.route("**/api/threads/*/uploads", async (route) => {
      await uploadHeld;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          message: "Uploaded",
          files: [
            {
              filename: "notes.txt",
              size: 12,
              path: "notes.txt",
              virtual_path: "/mnt/user-data/uploads/notes.txt",
              artifact_url: "/api/threads/test/uploads/notes.txt",
              extension: ".txt",
            },
          ],
        }),
      });
    });
    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        input?: { messages?: Array<{ content?: unknown }> };
      };
      const content = body.input?.messages?.at(-1)?.content;
      submittedText = textFromMessageContent(content);
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await page.getByLabel("Upload files").setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("fake notes"),
    });
    await textarea.fill("Send this immediately");
    await textarea.press("Enter");

    // The attachment is still uploading, so the send is not dispatched yet:
    // the draft stays stored, and a reload or a failed upload cannot lose it.
    await page.waitForTimeout(500);
    expect(
      await page.evaluate(() =>
        Object.values(window.sessionStorage).join("\n"),
      ),
    ).toContain("Send this immediately");

    releaseUpload();
    await expect
      .poll(() => submittedText, { timeout: 10_000 })
      .toBe("Send this immediately");
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });

    // Dispatch retired the draft, and nothing scheduled before it may write
    // the accepted text back.
    await page.waitForTimeout(500);
    expect(
      await page.evaluate(() =>
        Object.values(window.sessionStorage).join("\n"),
      ),
    ).not.toContain("Send this immediately");

    // A new user edit must still save, even when it repeats the accepted text.
    await page
      .getByPlaceholder(/how can i assist you/i)
      .fill("Send this immediately");
    await expect
      .poll(() =>
        page.evaluate(() => Object.values(window.sessionStorage).join("\n")),
      )
      .toContain("Send this immediately");
    await page.getByPlaceholder(/how can i assist you/i).fill("");
    await expect
      .poll(() =>
        page.evaluate(() => Object.values(window.sessionStorage).join("\n")),
      )
      .not.toContain("Send this immediately");

    await page.reload();
    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      "",
    );
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

  test("suggests only builtin commands after a leading slash", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");
    const input = page.getByPlaceholder(/how can i assist you/i);
    await input.fill("/");
    const list = page.getByRole("listbox", { name: "Command suggestions" });
    await expect(list.getByRole("option")).toHaveCount(2);
    await expect(list.getByRole("option", { name: /^\/goal / })).toBeVisible();
    await expect(
      list.getByRole("option", { name: /^\/compact / }),
    ).toBeVisible();
    await input.fill("/dat");
    await expect(list).toBeHidden();
    await expect(page.getByTestId("inline-skill-reference")).toBeHidden();
  });

  test("submits a legacy skill query literally without choosing a skill", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");
    const input = page.getByPlaceholder(/how can i assist you/i);
    await input.fill("/dat");
    const request = page.waitForRequest((request) =>
      request.url().includes("/runs/stream"),
    );
    await input.press("Enter");
    const body = (await request).postDataJSON();
    const message = body.input.messages.at(-1);
    expect(textFromMessageContent(message.content)).toBe("/dat");
    expect(message.additional_kwargs?.skill_references).toBeUndefined();
  });

  test("selects a skill named after a builtin through the mention picker", async ({
    page,
  }) => {
    await page.route("**/api/skills", (route) =>
      route.fulfill({
        json: {
          skills: [
            {
              name: "compact",
              description: "A compact skill",
              category: "custom",
              enabled: true,
            },
            {
              name: "status",
              description: "A status skill",
              category: "custom",
              enabled: true,
            },
            {
              name: "a--b",
              description: "An invalid skill name",
              category: "custom",
              enabled: true,
            },
          ],
        },
      }),
    );
    let compactCalls = 0;
    await page.route("**/api/threads/*/compact", (route) => {
      compactCalls += 1;
      return route.fulfill({ json: {} });
    });
    await page.goto("/workspace/chats/new");
    const input = page.getByRole("textbox", { name: /how can i assist you/i });
    await input.fill("@");
    await expect(
      page.getByRole("option", { name: "compact A compact skill" }),
    ).toBeVisible();
    await expect(
      page.getByRole("option", { name: "status A status skill" }),
    ).toBeHidden();
    await expect(
      page.getByRole("option", { name: "a--b An invalid skill name" }),
    ).toBeHidden();
    await input.fill("@comp");
    await page.getByRole("option", { name: "compact A compact skill" }).click();
    await expect(page.getByTestId("inline-skill-reference")).toHaveText(
      "✦compact",
    );
    await input.pressSequentially("Analyze this");
    const request = page.waitForRequest((request) =>
      request.url().includes("/runs/stream"),
    );
    await input.press("Enter");
    const message = (await request).postDataJSON().input.messages.at(-1);
    expect(textFromMessageContent(message.content)).toBe(
      "@compact Analyze this",
    );
    expect(message.additional_kwargs.skill_references).toEqual(["compact"]);
    expect(compactCalls).toBe(0);
  });

  test("selects a goal command after removing an inline skill", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");
    const input = page.getByRole("textbox", { name: /how can i assist you/i });
    await input.fill("@dat");
    await page.getByRole("option", { name: /data-analysis/i }).click();
    await input.press("ControlOrMeta+A");
    await input.press("Backspace");
    await expect(page.getByTestId("inline-skill-reference")).toBeHidden();
    await input.pressSequentially("/go");
    await input.press("Enter");
    await input.pressSequentially("finish the tests");
    await expect(input).toHaveText("/goal finish the tests");
    const goalRequest = page.waitForRequest(
      (request) =>
        request.method() === "PUT" && request.url().endsWith("/goal"),
    );
    await input.press("Enter");
    expect((await goalRequest).postDataJSON()).toEqual({
      objective: "finish the tests",
    });
  });

  test("compact commands call the context endpoint without starting a run", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Existing chat",
          messages: [
            { id: "existing-task", type: "human", content: "A first task" },
          ],
        },
      ],
    });
    let compactCalls = 0;
    let streamCalls = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/runs/stream"))
        streamCalls += 1;
    });
    await page.route("**/api/threads/*/compact", (route) => {
      compactCalls += 1;
      return route.fulfill({ json: { compacted: true } });
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const input = page.getByRole("textbox", { name: /how can i assist you/i });
    await expect(input).toBeVisible();
    for (const [index, command] of ["/compact", "/context compact"].entries()) {
      await input.fill(command);
      if (command === "/compact") {
        await input.press("Enter");
        await expect(input).toHaveValue("/compact ");
      }
      await input.press("Enter");
      await expect.poll(() => compactCalls).toBe(index + 1);
      await expect(input).toHaveValue("");
    }
    expect(streamCalls).toBe(0);
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
  test("goal command assigns the project before saving the goal", async ({
    page,
  }) => {
    // Regression: the goal PUT endpoint materializes a missing thread row
    // itself, so the project-scoped thread create must land first — an
    // unassigned row would make the later idempotent createThread return it
    // without assigning the requested project.
    const events: string[] = [];
    let createProjectId: string | null = null;
    page.on("request", (request) => {
      const url = request.url();
      if (request.method() === "POST" && url.endsWith("/api/threads")) {
        events.push("create-thread");
        createProjectId =
          (request.postDataJSON() as { project_id?: string } | null)
            ?.project_id ?? null;
      }
      if (
        request.method() === "PUT" &&
        /\/api\/threads\/[^/]+\/goal$/.test(url)
      ) {
        events.push("save-goal");
      }
    });

    await page.goto("/workspace/chats/new?project=proj-1");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/goal finish all tests");
    await textarea.press("Enter");

    await expect(
      page.locator("span.font-medium", { hasText: "finish all tests" }),
    ).toBeVisible();
    expect(createProjectId).toBe("proj-1");
    expect(events.slice(0, 2)).toEqual(["create-thread", "save-goal"]);
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

  test("uses arrow keys to navigate command suggestions before prompt history", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/");

    const goal = page.getByRole("option", {
      name: /^\/goal /,
    });
    const compact = page.getByRole("option", {
      name: /^\/compact /,
    });
    await expect(goal).toBeVisible();
    await expect(compact).toBeVisible();
    await expect(goal).toHaveAttribute("aria-selected", "true");

    await textarea.press("ArrowDown");

    await expect(textarea).toHaveValue("/");
    await expect(goal).toHaveAttribute("aria-selected", "false");
    await expect(compact).toHaveAttribute("aria-selected", "true");

    await textarea.press("ArrowUp");

    await expect(textarea).toHaveValue("/");
    await expect(goal).toHaveAttribute("aria-selected", "true");
    await expect(compact).toHaveAttribute("aria-selected", "false");

    await textarea.press("ArrowDown");
    await textarea.press("Enter");

    await expect(textarea).toHaveValue("/compact ");
  });

  test("keeps Shift+Enter as newline while command suggestions are visible", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("/go");
    await expect(page.getByRole("option", { name: /^\/goal / })).toBeVisible();

    await textarea.press("Shift+Enter");

    await expect(textarea).toHaveValue("/go\n");
    await expect(page.getByRole("option", { name: /^\/goal / })).toBeHidden();
  });

  test("does not suggest commands for slash text away from the prompt start", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await textarea.fill("please /goal");

    await expect(page.getByRole("option", { name: /^\/goal / })).toBeHidden();
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

  test("shows structured upload errors as readable messages", async ({
    page,
  }) => {
    await page.route("**/api/threads/*/uploads", (route) =>
      route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          detail: [
            {
              type: "missing",
              loc: ["body", "files"],
              msg: "Field required",
              input: null,
            },
          ],
        }),
      }),
    );

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });

    await page.getByLabel("Upload files").setInputFiles({
      name: "report.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("report"),
    });
    await textarea.fill("Summarize this report");
    await textarea.press("Enter");

    const errorToast = page
      .locator("[data-sonner-toast]")
      .filter({ hasText: "body.files: Field required" });
    await expect(errorToast).toBeVisible();
    await expect(errorToast).not.toContainText("[object Object]");
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
