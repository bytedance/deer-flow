import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test.beforeEach(async ({ page }) => {
  mockLangGraphAPI(page, {
    agents: [{ name: "reviewer", description: "Review agent" }],
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Settled agent chat",
        agent_name: "reviewer",
      },
    ],
  });
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        models: [
          { name: "model-a", display_name: "Model A" },
          { name: "model-b", display_name: "Model B" },
        ],
      },
    }),
  );
  await page.route("**/api/models/resolve", (route) =>
    route.fulfill({
      json: {
        status: "resolved",
        scope: "conversation",
        query: "Model B",
        model_name: "model-b",
        candidates: [{ name: "model-b", label: "Model B" }],
        task_offset: route.request().postDataJSON().text.length,
      },
    }),
  );
});

for (const destination of ["agent-thread", "normal-chat"] as const) {
  test(`a pending Custom Agent model change cannot affect ${destination}`, async ({
    page,
  }) => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let createdId!: string;
    const intercepted = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        new URL(request.url()).pathname === "/api/threads",
    );
    const runRequests: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/runs/stream"))
        runRequests.push(request.url());
    });
    await page.route("**/api/threads", async (route) => {
      if (route.request().method() === "POST") {
        createdId = route.request().postDataJSON().thread_id;
        await held;
      }
      return route.fallback();
    });
    await page.goto("/workspace/agents/reviewer/chats/new");
    const input = page.getByRole("textbox", { name: /how can i assist you/i });
    await input.fill("From now on use Model B");
    await input.press("Enter");
    const createRequest = await intercepted;
    const previousModel = await page.evaluate(
      // No override and an explicit model-a both select the configured default.
      (id) => localStorage.getItem(`deerflow.thread-model.${id}`) ?? "model-a",
      createdId,
    );
    try {
      await page
        .getByRole("link", {
          name:
            destination === "agent-thread" ? "Settled agent chat" : "New chat",
          exact: true,
        })
        .click();
      const target =
        destination === "agent-thread"
          ? `/workspace/agents/reviewer/chats/${MOCK_THREAD_ID}`
          : "/workspace/chats/new";
      await expect(page).toHaveURL(new RegExp(`${target}$`));
      await input.fill("Keep this draft");
      release();
      const response = await createRequest.response();
      expect(response).not.toBeNull();
      expect(response!.ok()).toBe(true);
      await response!.finished();
      // The response body and its submit continuation settle before the next paint.
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      await expect(page).toHaveURL(new RegExp(`${target}$`));
      await expect(input).toHaveText("Keep this draft");
      expect(
        await page.evaluate(
          (id) =>
            localStorage.getItem(`deerflow.thread-model.${id}`) ?? "model-a",
          createdId,
        ),
      ).toBe(previousModel);
      await expect(
        page.getByText("Conversation default model saved.", { exact: true }),
      ).toBeHidden();
      expect(runRequests).toEqual([]);
    } finally {
      release();
    }
  });
}

test("a completed Custom Agent model change still saves without a run", async ({
  page,
}) => {
  const runs: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/runs/stream"))
      runs.push(request.url());
  });
  await page.goto("/workspace/agents/reviewer/chats/new");
  const input = page.getByRole("textbox", { name: /how can i assist you/i });
  await input.fill("From now on use Model B");
  await input.press("Enter");
  await expect(
    page.getByText("Conversation default model saved.", { exact: true }),
  ).toBeVisible();
  const threadId = new URL(page.url()).pathname.split("/").at(-1)!;
  expect(threadId).not.toBe("new");
  expect(
    await page.evaluate(
      (id) => localStorage.getItem(`deerflow.thread-model.${id}`),
      threadId,
    ),
  ).toBe("model-b");
  expect(runs).toEqual([]);
});
