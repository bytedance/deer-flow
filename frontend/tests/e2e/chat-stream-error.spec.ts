import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

for (const { status, body, message } of [
  {
    status: 502,
    body: '{"detail":"upstream failed"}',
    message:
      "The service is temporarily unavailable (HTTP 502). Please try again.",
  },
  {
    status: 409,
    body: '{"detail":"Another run is active"}',
    message: 'HTTP 409: {"detail":"Another run is active"}',
  },
]) {
  test(`shows the expected chat error for HTTP ${status}`, async ({ page }) => {
    const streamWarnings: string[] = [];
    page.on("console", (entry) => {
      if (
        entry.type() === "warning" &&
        entry.text().startsWith("Chat stream request failed:")
      ) {
        streamWarnings.push(entry.text());
      }
    });

    mockLangGraphAPI(page);
    await page.route(
      /\/api\/langgraph\/(?:threads\/[^/]+\/)?runs\/stream$/,
      (route) =>
        route.fulfill({ status, contentType: "application/json", body }),
    );

    await page.goto("/workspace/chats/new");
    const composer = page.getByRole("textbox", {
      name: /how can i assist you/i,
    });
    await composer.fill("Send a message");
    await composer.press("Enter");

    await expect(page.locator("[data-sonner-toast]").last()).toHaveText(
      message,
    );
    expect(streamWarnings).toEqual(
      status === 502 ? [`Chat stream request failed: HTTP 502: ${body}`] : [],
    );
  });
}

test("shows the answer of a run that ends after rejoining it failed", async ({
  page,
}) => {
  const runId = "00000000-0000-0000-0000-0000000000a1";
  const question = { type: "human", id: "human-1", content: "Sum the totals" };
  const answer = { type: "ai", id: "ai-1", content: "The totals add up." };
  let joins = 0;
  let historyReads = 0;
  let historyReadsAtLastJoin = Infinity;
  let finished = false;
  const status = () => (finished ? "success" : "running");
  const run = () => ({
    run_id: runId,
    thread_id: MOCK_THREAD_ID,
    assistant_id: "lead_agent",
    status: status(),
    metadata: {},
    kwargs: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  mockLangGraphAPI(page, {
    threads: [
      { thread_id: MOCK_THREAD_ID, title: "Totals", messages: [question] },
    ],
  });
  await page.route("**/api/features", (route) =>
    route.fulfill({ json: { run_inputs: true } }),
  );
  await page.route(`**/api/threads/${MOCK_THREAD_ID}/inputs`, (route) =>
    route.fulfill({
      json: { items: [], active_run_id: finished ? null : runId },
    }),
  );
  await page.route(
    new RegExp(`/api/langgraph/threads/${MOCK_THREAD_ID}/runs(?:\\?|$)`),
    (route) => route.fulfill({ json: [run()] }),
  );
  await page.route(
    new RegExp(
      `/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${runId}(?:\\?|$)`,
    ),
    (route) => route.fulfill({ json: run() }),
  );
  // Every rejoin loses its connection.
  await page.route(
    new RegExp(`/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${runId}/stream`),
    (route) => {
      joins += 1;
      if (joins === 3) historyReadsAtLastJoin = historyReads;
      return route.abort("connectionrefused");
    },
  );
  await page.route(
    new RegExp(`/api/threads/${MOCK_THREAD_ID}/messages/page`),
    (route) => {
      historyReads += 1;
      return route.fulfill({
        json: {
          data: (finished ? [question, answer] : [question]).map(
            (message, index) => ({
              run_id: runId,
              seq: index + 1,
              content: message,
              metadata: { caller: "lead_agent" },
              created_at: `2026-01-01T00:00:0${index}Z`,
            }),
          ),
          has_more: false,
          next_before_seq: null,
        },
      });
    },
  );

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await expect(
    page.getByRole("button", { name: "Stop current task" }),
  ).toBeVisible();
  await expect.poll(() => joins, { timeout: 15_000 }).toBe(3);
  // The last failure has reloaded history. Only then does the run end, so no
  // reload that the failure itself triggers can pick up the answer.
  await expect.poll(() => historyReads > historyReadsAtLastJoin).toBe(true);
  finished = true;

  // No stream reports this end, so the chat must notice it on its own.
  await expect(page.getByText(answer.content)).toBeVisible({ timeout: 10_000 });
  await expect(
    page.getByRole("button", { name: "Stop current task" }),
  ).toHaveCount(0);
  expect(joins).toBe(3);
});
