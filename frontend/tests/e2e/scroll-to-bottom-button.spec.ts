import { expect, test, type Locator } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

const FIRST_TASK_PROMPT =
  "Summarize the repository layout and report the result back to the parent agent.";
const LAST_TASK_PROMPT =
  "Verify the subtask card markup and report accessibility gaps to the parent agent.";
const TASK_PROMPTS = [
  FIRST_TASK_PROMPT,
  "Audit the thread sync hooks and report streaming regressions to the parent agent.",
  LAST_TASK_PROMPT,
];
// use-stick-to-bottom treats the list as "at the bottom" within 70px
// (STICK_TO_BOTTOM_OFFSET_PX), so the escape scroll must exceed that to
// reveal the button. It must also land the last card box across the button's
// center slot (~36px above the container's bottom edge): measured on this
// layout the card sits 90px above the content end, so the covering window is
// roughly 140-180px of scroll-up; the midpoint leaves margin on both sides.
const SCROLL_UP_PX = 160;
const FILLER_MESSAGES = Array.from({ length: 12 }, (_, index) => [
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

const subtaskThread = {
  thread_id: MOCK_THREAD_ID,
  title: "Scroll to bottom with a subtask card",
  updated_at: "2026-11-13T12:00:00Z",
  messages: [
    ...FILLER_MESSAGES,
    {
      type: "human",
      id: "msg-human-subtask",
      content: [
        { type: "text", text: "Kick off a subtask for the scroll test." },
      ],
    },
    {
      type: "ai",
      id: "msg-ai-subtask",
      content: "",
      additional_kwargs: {},
      response_metadata: {},
      tool_calls: TASK_PROMPTS.map((prompt, index) => ({
        id: `call-scroll-subtask-${index}`,
        name: "task",
        args: {
          subagent_type: "general-purpose",
          prompt,
        },
        type: "tool_call",
      })),
      invalid_tool_calls: [],
    },
  ],
};

/** The subtask card container (matches the idiom in subtask-card.spec.ts). */
function subtaskCard(title: Locator): Locator {
  return title.locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
}

test.describe("Scroll-to-bottom button", () => {
  // The card wrapper renders `relative z-1` (message-list.tsx); the button is
  // absolutely positioned without a stacking level, so a card scrolled under
  // the control paints over it and swallows the click. The Playwright click
  // below is the hit-test: an intercepted pointer fails the actionability wait.
  test("stays clickable above a subtask card scrolled under it", async ({
    page,
  }) => {
    test.setTimeout(60_000);
    mockLangGraphAPI(page, { threads: [subtaskThread] });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.reload();

    const lastCard = subtaskCard(page.getByTitle(LAST_TASK_PROMPT));
    await expect(lastCard).toBeVisible({ timeout: 15_000 });

    // `role="log"` lands on the StickToBottom wrapper; its only child is the
    // actual scroll container (Content's scrollRef, put on computed
    // `overflow: auto` by the library). Escape the stick lock the way a real
    // user does — a wheel-up over the list, which the library handles in
    // `handleWheel` directly. The restored thread's animation can still snap
    // an escape back to the bottom and unmount the button, so the whole
    // cycle — pin, wheel, geometry precondition, hit-test, click — retries
    // until one round completes end to end. 160px clears the 70px near-bottom band and lands a card box
    // across the button's slot.
    const scroller = page.getByRole("log").locator("> div");
    const button = page.getByRole("button", { name: "Scroll to bottom" });
    await expect(async () => {
      await scroller.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
      });
      await expect
        .poll(() =>
          scroller.evaluate(
            (el) => el.scrollHeight - el.clientHeight - el.scrollTop,
          ),
        )
        .toBeLessThanOrEqual(1);
      const box = await scroller.boundingBox();
      if (!box) {
        throw new Error("scroll container is not visible");
      }
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.wheel(0, -SCROLL_UP_PX);
      await expect(button).toBeVisible({ timeout: 2_000 });

      // Stacking check, in a single frame: one of the opaque card boxes must
      // cover the button's center point (otherwise the click would pass
      // vacuously), and the topmost element at that point must be the button
      // itself — without the z-index the card wins the hit-test. One
      // predicate, because separate polls leave a window where the restore
      // animation snaps the list back down and unmounts the button.
      const cardHandle = await subtaskCard(
        page.getByTitle(FIRST_TASK_PROMPT),
      ).elementHandle();
      await expect
        .poll(() =>
          button.evaluate((el, cardEl) => {
            if (!cardEl?.parentElement) {
              return false;
            }
            const b = el.getBoundingClientRect();
            const cx = b.left + b.width / 2;
            const cy = b.top + b.height / 2;
            const covered = Array.from(cardEl.parentElement.children).some(
              (child) => {
                const r = child.getBoundingClientRect();
                return (
                  cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom
                );
              },
            );
            if (!covered) {
              return false;
            }
            const hit = document.elementFromPoint(cx, cy);
            return hit === el || el.contains(hit);
          }, cardHandle),
        )
        .toBe(true);

      await button.click({ timeout: 2_000 });
    }).toPass({ timeout: 45_000 });

    await expect
      .poll(() =>
        scroller.evaluate(
          (el) => el.scrollTop + el.clientHeight >= el.scrollHeight - 4,
        ),
      )
      .toBe(true);
    await expect(button).toHaveCount(0);
  });
});
