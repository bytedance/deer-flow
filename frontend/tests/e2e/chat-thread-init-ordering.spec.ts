import { expect, test } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

/**
 * Regression for https://github.com/bytedance/deer-flow/issues/2746.
 *
 * On a brand-new chat, the LangGraph SDK's useStream eagerly fetches
 * `/threads/{id}/history` the moment it receives a thread id, and the
 * frontend's own `useThreadRuns` fires `GET /threads/{id}/runs` for the same
 * reason.  Both endpoints assume the thread already exists on the backend;
 * if the frontend forwards the (client-generated) thread id before
 * `POST /runs/stream` has actually created the thread, both calls 404 in
 * production.  This test pins the request ordering so the regression cannot
 * re-appear silently.
 */
test.describe("Chat: thread API request ordering on first send", () => {
  test("does not call /history or GET /runs before /runs/stream is initiated", async ({
    page,
  }) => {
    type EventLog = {
      phase: "sent" | "done";
      url: string;
      method: string;
      ts: number;
    };
    const events: EventLog[] = [];

    page.on("request", (req) => {
      events.push({
        phase: "sent",
        url: req.url(),
        method: req.method(),
        ts: Date.now(),
      });
    });
    page.on("requestfinished", (req) => {
      events.push({
        phase: "done",
        url: req.url(),
        method: req.method(),
        ts: Date.now(),
      });
    });

    mockLangGraphAPI(page);

    // Slow down /runs/stream so any pre-create /history or /runs request
    // would land well before the stream returns metadata, widening the
    // race window the bug used to exploit.
    await page.route(
      "**/api/langgraph/threads/*/runs/stream",
      async (route) => {
        await new Promise((r) => setTimeout(r, 250));
        return handleRunStream(route);
      },
    );
    await page.route("**/api/langgraph/runs/stream", async (route) => {
      await new Promise((r) => setTimeout(r, 250));
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Hello");
    await textarea.press("Enter");

    // Wait for streaming response so all init requests have a chance to fire.
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 15_000,
    });

    const isHistory = (url: string) =>
      /\/api\/langgraph\/threads\/[^/]+\/history/.test(url);
    const isRunsList = (url: string, method: string) =>
      method === "GET" &&
      /\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/.test(url);
    const isRunsStream = (url: string, method: string) =>
      method === "POST" && /\/runs\/stream(\?|$)/.test(url);

    const runsStreamSent = events.find(
      (e) => e.phase === "sent" && isRunsStream(e.url, e.method),
    );
    expect(
      runsStreamSent,
      "Expected POST /runs/stream to be issued during send",
    ).toBeDefined();

    const earlyHistory = events.filter(
      (e) =>
        e.phase === "sent" && isHistory(e.url) && e.ts < runsStreamSent!.ts,
    );
    const earlyRunsList = events.filter(
      (e) =>
        e.phase === "sent" &&
        isRunsList(e.url, e.method) &&
        e.ts < runsStreamSent!.ts,
    );

    expect(
      earlyHistory.map((e) => e.url),
      "GET /history must not be issued before POST /runs/stream — see issue #2746",
    ).toEqual([]);
    expect(
      earlyRunsList.map((e) => e.url),
      "GET /runs must not be issued before POST /runs/stream — see issue #2746",
    ).toEqual([]);
  });
});
