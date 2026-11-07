import { expect, test, type Route } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_RUN_ID,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

test("discovers a batch follow-up while its Run input channel is still closed", async ({
  page,
}, testInfo) => {
  let admitted = false,
    finished = false,
    inputsRead = 0,
    runsRead = 0,
    batchesRead = 0;
  let joined: Route | undefined;
  const messages = [
    {
      type: "human",
      id: "request",
      content: "Process the records and send me the summary.",
    },
    {
      type: "ai",
      id: "submitted",
      content: "The background batch is processing the records.",
    },
  ];
  const answer = {
    type: "ai",
    id: "follow-up-answer",
    content: "The background summary is now complete.",
  };
  const api = mockLangGraphAPI(page, {
    threads: [
      { thread_id: MOCK_THREAD_ID, title: "Batch follow-up", messages },
    ],
  });
  await page.route("**/api/features", (route) =>
    route.fulfill({
      json: {
        agents_api: { enabled: true },
        browser_control: { enabled: false },
        run_inputs: true,
        subagent_batches: {
          repository_available: true,
          worker_running: true,
          max_running: 8,
        },
      },
    }),
  );
  await page.route(`**/api/threads/${MOCK_THREAD_ID}/inputs`, (route) => {
    inputsRead++;
    // Admission is visible through /runs before the worker opens Run inputs.
    return route.fulfill({ json: { items: [], active_run_id: null } });
  });
  const run = () => ({
    run_id: MOCK_RUN_ID,
    thread_id: MOCK_THREAD_ID,
    assistant_id: "lead_agent",
    status: finished ? "success" : "pending",
    metadata: {},
    kwargs: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:01Z",
  });
  await page.route(
    new RegExp(`/api/langgraph/threads/${MOCK_THREAD_ID}/runs(?:\\?|$)`),
    (route) => {
      runsRead++;
      return route.fulfill({ json: admitted ? [run()] : [] });
    },
  );
  await page.route(
    new RegExp(
      `/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${MOCK_RUN_ID}(?:\\?|$)`,
    ),
    (route) => route.fulfill({ json: run() }),
  );
  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/subagent-batches?*`,
    (route) => {
      batchesRead++;
      return route.fulfill({
        json: [
          {
            id: "batch",
            thread_id: MOCK_THREAD_ID,
            title: "Meeting records",
            subagent_type: "general-purpose",
            status: admitted ? "completed" : "running",
            total_items: 1,
            max_live_items: 1,
            max_running_items: 1,
            max_attempts: 1,
            counts: {
              pending: 0,
              queued: 0,
              leased: 0,
              running: admitted ? 0 : 1,
              succeeded: admitted ? 1 : 0,
              failed: 0,
              cancelled: 0,
            },
            continuation_status: admitted ? "dispatched" : "pending",
            continuation_run_id: admitted ? MOCK_RUN_ID : null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:01Z",
            completed_at: admitted ? "2026-01-01T00:00:01Z" : null,
          },
        ],
      });
    },
  );
  await page.route(
    `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${MOCK_RUN_ID}/stream*`,
    (route) => {
      joined = route;
    },
  );

  try {
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(
      page.getByText(messages[1]!.content, { exact: true }),
    ).toBeVisible();
    await expect
      .poll(() => inputsRead > 0 && runsRead > 0 && batchesRead > 0)
      .toBe(true);
    admitted = true;
    await expect.poll(() => !!joined, { timeout: 10000 }).toBe(true);
    expect(runsRead).toBeGreaterThan(1);
    finished = true;
    api.upsertThread({
      thread_id: MOCK_THREAD_ID,
      title: "Batch follow-up",
      messages: [...messages, answer],
    });
    const stream = joined!;
    joined = undefined;
    await handleRunStream(stream, {}, messages, { responseMessage: answer });
    await expect(page.getByText(answer.content, { exact: true })).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath("followup-before-inputs-open.png"),
      fullPage: true,
    });
  } finally {
    if (joined) await joined.abort();
  }
});
