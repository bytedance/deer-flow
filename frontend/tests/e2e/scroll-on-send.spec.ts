import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const SENT_TEXT = "Pin this message to the top of the viewport.";
const TALL_ANSWER = Array.from(
  { length: 24 },
  (_, index) =>
    `Paragraph ${index}: the streamed reply keeps growing line after line, ` +
    "and the viewport must stay at the reader's position instead of " +
    "chasing the bottom of the conversation.",
).join("\n\n");

function fillerMessages(turns: number) {
  return Array.from({ length: turns }, (_, index) => [
    {
      type: "human",
      id: `msg-human-filler-${index}`,
      content: [
        {
          type: "text",
          text: `Filler question ${index}: describe the message list scroll behavior in detail.`,
        },
      ],
    },
    {
      type: "ai",
      id: `msg-ai-filler-${index}`,
      content: `Filler answer ${index}: the message list keeps the latest turn in view, escapes the stick lock when the user scrolls up, and exposes a jump control to return.`,
      additional_kwargs: {},
      response_metadata: {},
      invalid_tool_calls: [],
    },
  ]).flat();
}

/**
 * SSE server that answers the run handshake, then — once the send has been
 * pinned — delivers the reply and holds the connection open. The held
 * connection keeps `thread.isLoading` true so the pin and its end spacer
 * stay alive for the assertions. `progressive` delivers the reply one
 * paragraph per 200ms tick (real streaming shape); otherwise the whole tall
 * answer arrives in one `values` frame.
 */
async function startHeldRunStream(options?: { progressive?: boolean }) {
  const progressive = options?.progressive ?? false;
  const paragraphs = TALL_ANSWER.split("\n\n");
  const timers: NodeJS.Timeout[] = [];
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk: Buffer) => {
      body += chunk.toString();
    });
    request.on("end", () => {
      let inputMessages: unknown[] = [];
      try {
        inputMessages =
          (JSON.parse(body) as { input?: { messages?: unknown[] } }).input
            ?.messages ?? [];
      } catch {
        inputMessages = [];
      }
      response.writeHead(200, {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
      });
      const write = (event: string, data: unknown) => {
        response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      };
      const answerFrame = (content: string) => ({
        messages: [
          ...inputMessages,
          {
            type: "ai",
            id: "msg-ai-scroll-send",
            content,
            additional_kwargs: {},
            response_metadata: {},
            invalid_tool_calls: [],
          },
        ],
      });
      write("metadata", {
        run_id: "run-scroll-send",
        thread_id: MOCK_THREAD_ID,
      });
      if (progressive) {
        paragraphs.forEach((paragraph, index) => {
          timers.push(
            setTimeout(
              () =>
                write(
                  "values",
                  answerFrame(paragraphs.slice(0, index + 1).join("\n\n")),
                ),
              600 + index * 200,
            ),
          );
        });
      } else {
        timers.push(
          setTimeout(() => write("values", answerFrame(TALL_ANSWER)), 600),
        );
      }
      // Connection stays open: the run remains in flight.
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });

  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/runs/stream`,
    async close() {
      for (const timer of timers) clearTimeout(timer);
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

test.describe("Scroll on send", () => {
  // ChatGPT-style send behavior: the freshly sent user turn aligns with the
  // top of the viewport, and the streamed reply grows downward below the
  // reading position instead of the viewport chasing the bottom. A flexible
  // end spacer makes the last row able to reach the top at all, and the
  // scroll-to-bottom button re-locks the follow when the user wants it back.
  async function expectSendPinned(
    page: Page,
    fillerTurns: number,
    options?: { progressive?: boolean },
  ) {
    const streamServer = await startHeldRunStream(options);
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Scroll on send",
          updated_at: "2026-11-14T12:00:00Z",
          messages: fillerMessages(fillerTurns),
        },
      ],
      runStreamHandler: (route) => route.continue({ url: streamServer.url }),
    });

    try {
      await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
      const lastFiller = page
        .getByText(`Filler question ${fillerTurns - 1}`, { exact: false })
        .first();
      await expect(lastFiller).toBeVisible({ timeout: 15_000 });

      const scroller = page.getByRole("log").locator("> div");
      // The restored thread settles pinned to the bottom.
      await expect
        .poll(() =>
          scroller.evaluate(
            (el) => el.scrollHeight - el.clientHeight - el.scrollTop,
          ),
        )
        .toBeLessThanOrEqual(1);

      const textarea = page.getByPlaceholder(/how can i assist you/i);
      await expect(textarea).toBeVisible({ timeout: 15_000 });
      await textarea.fill(SENT_TEXT);
      await textarea.press("Enter");

      const sentMessage = page.getByText(SENT_TEXT, { exact: true });
      await expect(sentMessage).toBeVisible({ timeout: 15_000 });

      // The user's message now sits at the top of the viewport (the group
      // start offset is 16px), no longer hugging the bottom edge.
      const scrollerHandle = await scroller.elementHandle();
      const sentTopInViewport = () =>
        sentMessage.evaluate(
          (el, scrollerEl) =>
            el.getBoundingClientRect().top -
            scrollerEl.getBoundingClientRect().top,
          scrollerHandle,
        );
      await expect.poll(sentTopInViewport).toBeLessThanOrEqual(64);

      // The tall streamed reply lands below the pinned message. Escape means
      // the viewport does NOT chase it: the distance to the bottom grows.
      await expect
        .poll(() =>
          scroller.evaluate(
            (el) => el.scrollHeight - el.clientHeight - el.scrollTop,
          ),
        )
        .toBeGreaterThan(200);

      // A slow bottom-chasing animation (a resurrected follow lock) would
      // drag the message up past the viewport top within this window; the
      // pin must stay put after the content has settled.
      await page.waitForTimeout(1_000);
      await expect.poll(sentTopInViewport).toBeLessThanOrEqual(64);
      const settledGap = await scroller.evaluate(
        (el) => el.scrollHeight - el.clientHeight - el.scrollTop,
      );
      expect(settledGap).toBeGreaterThan(70);

      // And the follow can be re-locked on demand: the jump button appears
      // because the list escaped the stick lock.
      await expect(
        page.getByRole("button", { name: "Scroll to bottom" }),
      ).toBeVisible();
    } finally {
      await streamServer.close();
    }
  }

  test("pins the sent user message to the top (static list)", async ({
    page,
  }) => {
    await expectSendPinned(page, 12);
  });

  test("pins the sent user message to the top (virtualized list)", async ({
    page,
  }) => {
    // 32 turns = 64 groups, past the list's virtualization threshold (60).
    await expectSendPinned(page, 32);
  });

  // Regression: a progressively streamed reply (one paragraph per 200ms) must
  // not re-lock the follow. If the end spacer shrank in lockstep with each
  // chunk, the net-negative resize re-locks use-stick-to-bottom while the
  // bottom gap is inside its 70px band, and every subsequent chunk drags the
  // viewport down without user input.
  test("keeps the pin while the reply streams in progressively", async ({
    page,
  }) => {
    await expectSendPinned(page, 12, { progressive: true });
  });

  // The send-pin chain (escape + re-align ticks for ~2s after a send) must
  // hand scroll control back on the first genuine user input. A wheel over
  // the list inside the chain window cancels it; without the cancel, a later
  // tick would revert the user's position back to the pinned offset.
  test("hands scroll control back when the user wheels inside the chain window", async ({
    page,
  }) => {
    const streamServer = await startHeldRunStream();
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Scroll on send",
          updated_at: "2026-11-14T12:00:00Z",
          messages: fillerMessages(12),
        },
      ],
      runStreamHandler: (route) => route.continue({ url: streamServer.url }),
    });

    try {
      await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
      await expect(
        page.getByText("Filler question 11", { exact: false }).first(),
      ).toBeVisible({ timeout: 15_000 });

      const scroller = page.getByRole("log").locator("> div");
      await expect
        .poll(() =>
          scroller.evaluate(
            (el) => el.scrollHeight - el.clientHeight - el.scrollTop,
          ),
        )
        .toBeLessThanOrEqual(1);

      const textarea = page.getByPlaceholder(/how can i assist you/i);
      await expect(textarea).toBeVisible({ timeout: 15_000 });
      await textarea.fill(SENT_TEXT);
      await textarea.press("Enter");

      const sentMessage = page.getByText(SENT_TEXT, { exact: true });
      await expect(sentMessage).toBeVisible({ timeout: 15_000 });
      const scrollerHandle = await scroller.elementHandle();
      const sentTopInViewport = () =>
        sentMessage.evaluate(
          (el, scrollerEl) =>
            el.getBoundingClientRect().top -
            scrollerEl.getBoundingClientRect().top,
          scrollerHandle,
        );
      // The pin landed; still well inside the 2s chain window.
      await expect.poll(sentTopInViewport).toBeLessThanOrEqual(64);

      const box = await scroller.boundingBox();
      if (!box) {
        throw new Error("scroll container is not visible");
      }
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.wheel(0, -240);

      // The wheel-up moves the viewport up, pushing the pinned message down
      // by the same amount (~240px past its pinned offset). Past several
      // would-be chain ticks (350/500/700/900/1100ms) the user's position
      // must hold instead of snapping back to the pin offset.
      await page.waitForTimeout(1_500);
      await expect.poll(sentTopInViewport).toBeGreaterThan(200);
      await page.waitForTimeout(400);
      await expect.poll(sentTopInViewport).toBeGreaterThan(200);

      // The user is now free of the follow; the jump button shows.
      await expect(
        page.getByRole("button", { name: "Scroll to bottom" }),
      ).toBeVisible();
    } finally {
      await streamServer.close();
    }
  });
});
