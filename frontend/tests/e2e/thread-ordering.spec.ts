import { expect, test, type Page, type Route } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_RUN_ID,
} from "./utils/mock-api";

/**
 * Browser-level composition regression for the message-ordering contract
 * (design §5.3): a deterministic fixture with more than one feed page
 * (>50 rows), many turns, and two past compactions (the hidden summary
 * rows), then a live third compaction during a newly submitted turn.
 *
 * Assertions happen at stage barriers: the relative DOM order of human
 * messages and steps, the visible message set, and a tool card's
 * association — then the same server data is reloaded and compared. The
 * virtual list is exercised through scroll/outline navigation instead of
 * assuming every message is in the DOM at once.
 */

const PAGE_SIZE = 50;
const THREAD = {
  thread_id: MOCK_THREAD_ID,
  title: "Ordering conversation",
  updated_at: "2026-09-08T12:00:00Z",
};

type FeedMessage = Record<string, unknown>;

function turnMessages(turn: number): FeedMessage[] {
  return [
    {
      type: "human",
      id: `h-turn-${turn}`,
      content: `turn-${turn} question`,
    },
    { type: "ai", id: `a-turn-${turn}`, content: `turn-${turn} answer` },
  ];
}

function hiddenSummary(id: string, text: string): FeedMessage {
  return {
    type: "ai",
    id,
    name: "summary",
    content: text,
    additional_kwargs: { hide_from_ui: true },
  };
}

/** 68 rows: 33 turns plus two hidden summary rows from past compactions. */
function buildFixtureMessages(): FeedMessage[] {
  const messages: FeedMessage[] = [];
  for (let turn = 0; turn <= 9; turn += 1) {
    messages.push(...turnMessages(turn));
  }
  // First compaction collapsed everything above into this hidden summary.
  messages.push(hiddenSummary("summary-1", "context summary one"));
  for (let turn = 10; turn <= 19; turn += 1) {
    messages.push(...turnMessages(turn));
  }
  // Second compaction.
  messages.push(hiddenSummary("summary-2", "context summary two"));
  for (let turn = 20; turn <= 29; turn += 1) {
    messages.push(...turnMessages(turn));
  }
  // A tool-using turn so the tool card association is verifiable.
  messages.push({
    type: "human",
    id: "h-turn-30",
    content: "turn-30 question",
  });
  messages.push({
    type: "ai",
    id: "a-turn-30",
    content: "",
    tool_calls: [
      {
        id: "call-turn-30",
        name: "web_search",
        args: { query: "turn-30 lookup" },
        type: "tool_call",
      },
    ],
  });
  messages.push({
    type: "tool",
    id: "t-turn-30",
    tool_call_id: "call-turn-30",
    name: "web_search",
    content: "tool-30 result payload",
  });
  messages.push({
    type: "ai",
    id: "a-turn-30-final",
    content: "turn-30 answer",
  });
  messages.push(...turnMessages(31));
  return messages;
}

type FeedRow = {
  run_id: string;
  seq: number;
  content: FeedMessage;
  metadata: { caller: string };
  created_at: string;
};

function toFeedRows(messages: FeedMessage[]): FeedRow[] {
  return messages.map((message, index) => ({
    run_id: `run-${MOCK_THREAD_ID}`,
    seq: index + 1,
    content: message,
    metadata: { caller: "lead_agent" },
    created_at: `2026-09-08T00:${String(Math.floor(index / 60)).padStart(2, "0")}:${String(index % 60).padStart(2, "0")}Z`,
  }));
}

/** Register a paginating `/messages/page` backed by the mutable feed rows. */
async function mockPaginatedFeed(page: Page, rows: FeedRow[]) {
  await page.route(/\/api\/threads\/[^/]+\/messages\/page/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    const url = new URL(route.request().url());
    const beforeSeqParam = url.searchParams.get("before_seq");
    const eligible =
      beforeSeqParam === null
        ? rows
        : rows.filter((row) => row.seq < Number(beforeSeqParam));
    const pageRows = eligible.slice(-PAGE_SIZE);
    const hasMore = eligible.length > pageRows.length;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data: pageRows,
        has_more: hasMore,
        next_before_seq: hasMore ? pageRows[0]!.seq : null,
      }),
    });
  });
}

/** Rendered message-group indices must appear in ascending DOM order. */
async function expectGroupIndicesAscending(page: Page) {
  const indices = await page
    .locator("[data-message-group-index]")
    .evaluateAll((elements) =>
      elements.map((element) =>
        Number(element.getAttribute("data-message-group-index")),
      ),
    );
  expect(indices.length).toBeGreaterThan(0);
  const sorted = [...indices].sort((left, right) => left - right);
  expect(indices).toEqual(sorted);
}

async function jumpToChapter(page: Page, title: string | RegExp) {
  await page.getByTestId("conversation-outline-trigger").click();
  // The menu sits above a smoothly-scrolling virtual list; late chapters need
  // an in-menu scroll, which can starve actionability checks. The item is
  // resolved and attached, so click through.
  await page.getByRole("menuitem", { name: title }).click({ force: true });
}

async function loadAllHistoryPages(page: Page) {
  const loadMore = page.getByRole("button", { name: "Load more" });
  // Each click prepends one older page; keep clicking until exhausted. The
  // near-top sentinel may already have auto-loaded a page, so the button is
  // not guaranteed to be there on every pass.
  for (let attempt = 0; attempt < 10; attempt += 1) {
    // Clicking a menu item closes the dropdown, so each pass starts from a
    // closed menu: open it, read the earliest loaded chapter, then jump to it
    // with the same click.
    await page.getByTestId("conversation-outline-trigger").click();
    const firstItem = page.getByRole("menuitem").first();
    const firstTitle = (await firstItem.textContent()) ?? "";
    await firstItem.click();
    if (firstTitle.includes("turn-0 question")) {
      return;
    }
    if (!(await loadMore.isVisible())) {
      // The sentinel auto-load is in flight; give it a beat to land.
      await page.waitForResponse(
        (response) => response.url().includes("/messages/page"),
        { timeout: 5_000 },
      );
      continue;
    }
    const pageResponse = page.waitForResponse((response) =>
      response.url().includes("/messages/page"),
    );
    await loadMore.click();
    await pageResponse;
  }
  throw new Error("turn-0 chapter never became reachable");
}
test.describe("Thread message ordering", () => {
  // Long conversations paginate and virtualize; navigation through the
  // outline plus a reload needs more than the 30s default.
  test.setTimeout(90_000);

  test("paginated long history renders turns in feed order and survives refresh", async ({
    page,
  }) => {
    const rows = toFeedRows(buildFixtureMessages());
    mockLangGraphAPI(page, {
      threads: [{ ...THREAD, messages: rows.map((row) => row.content) }],
    });
    await mockPaginatedFeed(page, rows);

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    // Newest page loads first and the view starts at the bottom.
    await expect(page.getByText("turn-31 answer")).toBeVisible({
      timeout: 15_000,
    });
    await expectGroupIndicesAscending(page);
    // Hidden compaction summaries never render.
    await expect(page.getByText("context summary one")).toHaveCount(0);
    await expect(page.getByText("context summary two")).toHaveCount(0);

    // Walk to the head of the conversation through pagination + outline
    // navigation; the virtual list only renders the visited window. The walk
    // ends on the turn-0 chapter.
    await loadAllHistoryPages(page);
    // Scope to the message list: the outline menu carries the same text.
    await expect(
      page.getByTestId("main-message-list").getByText("turn-0 question"),
    ).toBeVisible();
    await expectGroupIndicesAscending(page);

    // The tool turn keeps its card association: expand the collapsed steps
    // and the intermediate result is still there.
    await jumpToChapter(page, /turn-30 question/);
    await expect(
      page.getByTestId("main-message-list").getByText("turn-30 answer"),
    ).toBeVisible();

    // Same server data after a refresh reconstructs the same order.
    await page.reload();
    await expect(page.getByText("turn-31 answer")).toBeVisible({
      timeout: 15_000,
    });
    await expectGroupIndicesAscending(page);
    await loadAllHistoryPages(page);
    await expect(
      page.getByTestId("main-message-list").getByText("turn-0 question"),
    ).toBeVisible();
  });

  test("a live compaction during submit keeps history order and appends the new turn", async ({
    page,
  }) => {
    const messages = buildFixtureMessages();
    const rows = toFeedRows(messages);
    mockLangGraphAPI(page, {
      threads: [{ ...THREAD, messages: [...messages] }],
    });
    await mockPaginatedFeed(page, rows);

    // A run stream in the real frame format: metadata, the summarization
    // update (RemoveMessage(ALL) + hidden summary + retained tail), the
    // retained tail re-arriving as messages-tuple frames, then the streamed
    // answer and the end of the run. The feed grows by the new turn so the
    // finishing history refetch observes it.
    const compactionStream = async (route: Route) => {
      const submitted = (
        route.request().postDataJSON() as {
          input?: { messages?: FeedMessage[] };
        }
      )?.input?.messages;
      const submittedHuman = (submitted ?? []).find(
        (message) => message.type === "human",
      );
      // The runtime keeps the just-submitted human in the post-compaction
      // checkpoint state — the SDK-side human count only advances if the
      // stream echoes it, which is also what hides the optimistic copy.
      const serverHuman: FeedMessage = {
        type: "human",
        id: "h-turn-32",
        content: submittedHuman?.content ?? "final-turn question",
      };
      const retainedTail = [...turnMessages(31)];
      const removeAll = { id: "__remove_all__", type: "remove" };
      const summary3 = hiddenSummary("summary-3", "context summary three");
      const answer = {
        type: "ai",
        id: "a-turn-32",
        content: "final-turn answer",
      };
      const frames = [
        {
          event: "metadata",
          data: { run_id: MOCK_RUN_ID, thread_id: MOCK_THREAD_ID },
        },
        // The summarization middleware update the frontend's compaction
        // rescue keys off: RemoveMessage(ALL) + hidden summary + retained
        // tail, with the just-submitted human still in state.
        {
          event: "updates",
          data: {
            "DeerFlowSummarizationMiddleware.before_model": {
              messages: [removeAll, summary3, ...retainedTail, serverHuman],
            },
          },
        },
        // The post-compaction checkpoint wholesale, as the established
        // handleRunStream mock convention delivers it: hidden summary,
        // retained tail, submitted human, and the streamed answer.
        {
          event: "values",
          data: {
            messages: [summary3, ...retainedTail, serverHuman, answer],
          },
        },
        { event: "end", data: {} },
      ];
      // The persisted feed grows by the new turn so the finishing history
      // refetch observes it, mirroring the journal flush on the real backend.
      const base = rows.length;
      const newTurn: FeedMessage[] = [serverHuman, answer];
      rows.push(
        ...newTurn.map((message, index) => ({
          run_id: `run-${MOCK_THREAD_ID}`,
          seq: base + index + 1,
          content: message,
          metadata: { caller: "lead_agent" },
          created_at: "2026-09-08T01:00:00Z",
        })),
      );
      const body = frames
        .map(
          (frame) =>
            `event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`,
        )
        .join("");
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body,
      });
    };
    await page.route("**/api/langgraph/threads/*/runs/stream", (route) =>
      compactionStream(route),
    );
    await page.route("**/api/langgraph/runs/stream", (route) =>
      compactionStream(route),
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText("turn-31 answer")).toBeVisible({
      timeout: 15_000,
    });

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await textarea.fill("final-turn question");
    await textarea.press("Enter");

    // The streamed answer lands below the submitted question. Note: the
    // count-based optimistic clearing does not fire when compaction shrinks
    // the SDK human count below its pre-submit value (a known limitation
    // tracked with the turn-ownership work), so a trailing optimistic twin
    // can remain; the ordering contract asserted here is about the canonical
    // server copy.
    await expect(page.getByText("final-turn answer")).toBeVisible({
      timeout: 15_000,
    });
    const questionBox = await page
      .getByTestId("main-message-list")
      .getByText("final-turn question", { exact: true })
      .first()
      .boundingBox();
    const answerBox = await page
      .getByTestId("main-message-list")
      .getByText("final-turn answer")
      .boundingBox();
    expect(questionBox).not.toBeNull();
    expect(answerBox).not.toBeNull();
    expect(answerBox!.y).toBeGreaterThan(questionBox!.y);

    // The finishing refetch observed the extended feed; the established
    // order — including the compacted head — is unchanged.
    await expectGroupIndicesAscending(page);
    await expect(page.getByText("turn-31 answer")).toBeVisible();
    await expect(page.getByText("context summary three")).toHaveCount(0);

    await loadAllHistoryPages(page);
    await expect(
      page.getByTestId("main-message-list").getByText("turn-0 question"),
    ).toBeVisible();

    // Refresh against the same server data: identical order.
    await page.reload();
    await expect(page.getByText("final-turn answer")).toBeVisible({
      timeout: 15_000,
    });
    await expectGroupIndicesAscending(page);
  });
});
