import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Page, type Route } from "@playwright/test";

import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

import {
  MOCK_RUN_ID,
  mockGoal,
  mockGoalOutcome,
  mockLangGraphAPI,
  runStreamThreadId,
  visibleRunInputMessages,
  type MockAPIOptions,
  type MockThread,
} from "./utils/mock-api";
import { expectNoRawIdentifiers } from "./utils/readable";

/**
 * A Gateway-like run stream. The response names the created run
 * (`Content-Location`, which moves a new chat to its own URL), and each
 * `values` frame is written `gapMs` after the previous one, so the goal bar
 * renders every state a live goal run passes through. As elsewhere in these
 * mocks, messages ride the `values` frames. The Gateway streams a chat run's
 * messages as message events and sends `values` only for goal writes, so a
 * frame that adds messages and leaves the goal as it was stands in for those
 * events. `saved` runs before the last frame: by then the backend has stored
 * the run's final state for the post-run history refetch.
 */
async function startRunStream(gapMs: number) {
  let run: {
    threadId: string;
    steps: Record<string, unknown>[];
    saved: () => void;
  } = { threadId: "", steps: [], saved: () => undefined };
  const server = createServer((_request, response) => {
    const { threadId, steps, saved } = run;
    response.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Expose-Headers": "Content-Location",
      "Cache-Control": "no-cache",
      "Content-Location": `/threads/${threadId}/runs/${MOCK_RUN_ID}`,
      "Content-Type": "text/event-stream",
    });
    const frame = (event: string, data: unknown) =>
      `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    response.write(
      frame("metadata", { run_id: MOCK_RUN_ID, thread_id: threadId }),
    );
    const timers = steps.map((values, index) =>
      setTimeout(() => {
        if (index < steps.length - 1) {
          response.write(frame("values", values));
          return;
        }
        saved();
        response.end(frame("values", values) + frame("end", {}));
      }, index * gapMs),
    );
    response.once("close", () => timers.forEach(clearTimeout));
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
    /** Answer the run `route` starts with these `values` frames. */
    serve(route: Route, steps: Record<string, unknown>[], saved: () => void) {
      run = { threadId: runStreamThreadId(route), steps, saved };
      return route.continue({ url: `http://127.0.0.1:${port}/runs/stream` });
    },
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

// Both chat pages wire the goal bar and the edit lock themselves, so every
// case runs on each of them.
const CHAT_PAGES: {
  name: string;
  path: string;
  options: MockAPIOptions;
  agentName?: string;
}[] = [
  { name: "chat", path: "/workspace/chats", options: {} },
  {
    name: "agent chat",
    path: "/workspace/agents/test-agent/chats",
    options: {
      agents: [
        {
          name: "test-agent",
          description: "A test agent for E2E tests",
          system_prompt: "You are a test agent.",
        },
      ],
    },
    agentName: "test-agent",
  },
];

const THREAD_ID = "00000000-0000-0000-0000-000000000601";
const BUSY = "A run is still going in this chat. Try again when it finishes.";

function goalBar(page: Page) {
  return page.getByRole("region", { name: "Goal status" });
}

function composer(page: Page) {
  return page.getByPlaceholder(/how can i assist you/i);
}

/** A question card the agent left open (`ask_clarification`). */
const OPEN_QUESTION = [
  {
    type: "ai",
    id: "goal-ask",
    content: "",
    tool_calls: [
      {
        id: "call-room",
        name: "ask_clarification",
        args: {
          question: "Which time works for you?",
          clarification_type: "missing_info",
          options: ["10:00", "14:00"],
        },
      },
    ],
  },
  {
    type: "tool",
    id: "goal-question",
    name: "ask_clarification",
    tool_call_id: "call-room",
    content: "Which time works for you?",
    artifact: {
      human_input: {
        version: 1,
        kind: "human_input_request",
        source: "ask_clarification",
        request_id: "clarification:call-room",
        tool_call_id: "call-room",
        clarification_type: "missing_info",
        question: "Which time works for you?",
        input_mode: "choice_with_other",
        options: [
          { id: "option-1", label: "10:00", value: "10:00" },
          { id: "option-2", label: "14:00", value: "14:00" },
        ],
      },
    },
  },
];

const STOOD_DOWN = [
  {
    name: "a goal that used every automatic follow-up",
    objective: "Make every test in the suite pass",
    goal: {
      continuation_count: 8,
      last_evaluation: {
        satisfied: false,
        blocker: "goal_not_met_yet",
        reason: "Two tests still fail.",
        stand_down_reason: "max_continuations_reached",
      },
    },
    reply: [
      {
        type: "ai",
        id: "goal-ai",
        content: "Six of the eight tests pass now.",
      },
    ],
    chip: "Stopped",
    detail:
      "Continuation limit reached · 8/8. It won't auto-continue again. Reply to keep going, or set the goal again with /goal <condition> to start a fresh count (this also starts a new run).",
    note: "Two tests still fail.",
  },
  {
    name: "a goal that needs details before any follow-up",
    objective: "Book a meeting room for Friday",
    goal: {
      last_evaluation: {
        satisfied: false,
        blocker: "needs_user_input",
        reason: "The user has to pick a time first.",
        stand_down_reason: "blocked:needs_user_input",
      },
    },
    reply: [
      { type: "ai", id: "goal-ai", content: "Which time works for you?" },
    ],
    chip: "Waiting for you",
    detail: "Reply with the missing details to continue.",
    note: "The user has to pick a time first.",
  },
  {
    name: "a goal waiting on an open question",
    objective: "Book a meeting room for Friday",
    goal: {
      // The host writes this reason itself; it is not the checker's note.
      last_evaluation: {
        satisfied: false,
        blocker: "needs_user_input",
        reason:
          "The turn ended on a question to the user that has not been answered.",
        stand_down_reason: "blocked:needs_user_input",
      },
    },
    reply: OPEN_QUESTION,
    chip: "Waiting for you",
    detail: "Answer the question above to continue.",
    note: null,
  },
] satisfies {
  name: string;
  objective: string;
  goal: Partial<GoalState>;
  reply: unknown[];
  chip: string;
  detail: string;
  note: string | null;
}[];

for (const chatPage of CHAT_PAGES) {
  const threadUrl = `${chatPage.path}/${THREAD_ID}`;

  /** A chat with one finished turn, optionally under a stood-down goal. */
  function chatThread({
    objective = "Summarize the README",
    goal,
    reply = [
      { type: "ai", id: "goal-ai", content: "The README covers setup." },
    ],
  }: {
    objective?: string;
    goal?: Partial<GoalState>;
    reply?: unknown[];
  } = {}): MockThread {
    return {
      thread_id: THREAD_ID,
      title: "Goal chat",
      agent_name: chatPage.agentName,
      messages: [
        {
          type: "human",
          id: "goal-human",
          content: [{ type: "text", text: objective }],
        },
        ...reply,
      ],
      ...(goal ? { goal: mockGoal(objective, goal) } : {}),
    };
  }

  test.describe(`Goal bar on the ${chatPage.name} page`, () => {
    for (const scenario of STOOD_DOWN) {
      test(`explains ${scenario.name}, also after a reload`, async ({
        page,
      }) => {
        mockLangGraphAPI(page, {
          ...chatPage.options,
          threads: [chatThread(scenario)],
        });
        await page.goto(threadUrl);

        const bar = goalBar(page);
        for (const reload of [false, true]) {
          if (reload) {
            await page.reload();
          }
          await expect(bar.getByTestId("goal-status-chip")).toHaveText(
            scenario.chip,
            { timeout: 15_000 },
          );
          await expect(bar.getByTestId("goal-status-detail")).toHaveText(
            scenario.detail,
          );
          await expect(bar).not.toContainText("Continuing");
          await expectNoRawIdentifiers(bar);
        }

        await bar.getByRole("button", { name: "Details" }).click();
        const details = bar.getByTestId("goal-status-details");
        await expect(details).toContainText(scenario.objective);
        if (scenario.note) {
          await expect(bar.getByTestId("goal-status-note")).toHaveText(
            scenario.note,
          );
        } else {
          await expect(details).not.toContainText("Goal check note");
        }
      });
    }

    test("keeps the locked edit pencil visible to the keyboard, and hides it during an upload", async ({
      page,
    }) => {
      mockLangGraphAPI(page, {
        ...chatPage.options,
        threads: [chatThread(STOOD_DOWN[0])],
      });
      await page.goto(threadUrl);
      await expect(goalBar(page).getByTestId("goal-status-chip")).toHaveText(
        "Stopped",
        { timeout: 15_000 },
      );

      // No pointer over the message: only keyboard focus can show its toolbar.
      await page.mouse.move(0, 0);
      const toolbar = page
        .getByTestId("message-toolbar")
        .filter({ has: page.getByTestId("message-edit-locked") });
      const pencil = toolbar.getByRole("button", { name: "Edit and rerun" });
      await toolbar.getByRole("button", { name: "Copy to clipboard" }).focus();
      await page.keyboard.press("Tab");

      await expect(pencil).toBeFocused();
      await expect(pencil).toBeDisabled();
      await expect(toolbar).toHaveCSS("opacity", "1");
      await expect(
        page.getByRole("tooltip").filter({
          hasText:
            "Editing is off while a goal is set. Run /goal clear to edit.",
        }),
      ).toBeVisible();

      await page.keyboard.press("Enter");
      await expect(
        page.getByRole("button", { name: "Update and rerun" }),
      ).toBeHidden();

      // No turn can be edited while a file uploads, so no pencil shows, not
      // even the goal's locked one.
      let releaseUpload!: () => void;
      const uploadHeld = new Promise<void>((resolve) => {
        releaseUpload = resolve;
      });
      await page.route("**/api/threads/*/uploads", async (route) => {
        await uploadHeld;
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Upload failed." }),
        });
      });
      await page.getByLabel("Upload files").setInputFiles({
        name: "notes.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("notes"),
      });
      await composer(page).fill("Summarize these notes");
      await composer(page).press("Enter");
      await expect(page.getByTestId("message-edit-locked")).toHaveCount(0);
      releaseUpload();
      await expect(page.getByTestId("message-edit-locked")).toHaveCount(1);
    });

    test("shows Goal met after one automatic follow-up until the chat moves on", async ({
      page,
    }) => {
      const objective = "Write a three-line summary of the README";
      const stream = await startRunStream(600);
      let runs = 0;
      const api = mockLangGraphAPI(page, {
        ...chatPage.options,
        threads: [chatThread()],
        runStreamHandler: async (route) => {
          runs += 1;
          const thread = api.getThread(runStreamThreadId(route))!;
          const turn = [
            ...(thread.messages ?? []),
            ...visibleRunInputMessages(route),
          ];

          if (runs > 1) {
            // A later turn: the backend keeps the record and adds the turn.
            const messages = [
              ...turn,
              { type: "ai", id: "goal-ai-3", content: "Glad it helps." },
            ];
            return stream.serve(
              route,
              [{ messages, goal_outcome: thread.goal_outcome }],
              () => api.upsertThread({ ...thread, messages }),
            );
          }

          const goal = thread.goal as GoalState;
          const draft = {
            type: "ai",
            id: "goal-ai-1",
            content: "Draft: the summary has two lines so far.",
          };
          const continuation = {
            type: "human",
            id: "goal-continuation-1",
            content: `<goal_continuation>\nActive goal: ${objective}\n</goal_continuation>`,
            additional_kwargs: {
              hide_from_ui: true,
              deerflow_goal_continuation: true,
            },
          };
          const reply = {
            type: "ai",
            id: "goal-ai-2",
            content: "Done: the summary now has three lines.",
          };
          const continuing: GoalState = {
            ...goal,
            continuation_count: 1,
            last_evaluation: {
              satisfied: false,
              blocker: "goal_not_met_yet",
              reason: "The summary has two lines, not three.",
              run_id: MOCK_RUN_ID,
            },
          };
          const record = mockGoalOutcome(continuing, reply.id, {
            reason: "The summary has three lines.",
          });
          const messages = [...turn, draft, continuation, reply];
          // The checkpoint has the submitted turn while the run goes on.
          api.upsertThread({ ...thread, messages: turn });
          return stream.serve(
            route,
            [
              { messages: [...turn, draft], goal },
              { messages: [...turn, draft, continuation], goal: continuing },
              { messages, goal: continuing },
              // The clear of the met goal: the record, and no `goal` key.
              { messages, goal_outcome: record },
            ],
            () =>
              api.upsertThread({
                ...thread,
                goal: null,
                goal_outcome: record,
                messages,
              }),
          );
        },
      });

      try {
        await page.goto(threadUrl);
        const textarea = composer(page);
        await expect(page.getByText("The README covers setup.")).toBeVisible({
          timeout: 15_000,
        });
        await textarea.fill(`/goal ${objective}`);
        await textarea.press("Enter");

        const bar = goalBar(page);
        await expect(bar).toContainText("In progress");
        await expect(bar).toContainText("Continuing 1/8");
        await expect(bar).toHaveAttribute("data-goal-state", "met");
        await expect(bar).toContainText(`Goal met${objective}`);
        await expect(bar).toContainText("Auto-continued once");
        await expect(bar).not.toContainText("Continuing");
        await expect(
          page.getByText("Done: the summary now has three lines."),
        ).toBeVisible();
        // The goal is no longer active, so edit-and-rerun is back.
        await expect(
          page.getByRole("button", { name: "Edit and rerun" }),
        ).toBeEnabled();
        await expect(page.getByTestId("message-edit-locked")).toHaveCount(0);
        await expectNoRawIdentifiers(bar);

        await page.reload();
        await expect(bar).toContainText("Goal met", { timeout: 15_000 });
        await expect(bar).toContainText("Auto-continued once");

        await textarea.fill("Thanks, that works.");
        await textarea.press("Enter");
        await expect(page.getByText("Glad it helps.")).toBeVisible();
        await expect(bar).toBeHidden();
        await page.reload();
        await expect(page.getByText("Glad it helps.")).toBeVisible({
          timeout: 15_000,
        });
        await expect(bar).toBeHidden();
        expect(runs).toBe(2);
      } finally {
        await stream.close();
      }
    });

    test("replaces the set goal with Goal met when the first run meets it, and Goal met with a new goal", async ({
      page,
    }) => {
      const objective = "Summarize the README in three lines";
      const next = "List the README's sections";
      const nextReply = "Sections: Setup, Usage, License.";
      const stream = await startRunStream(600);
      let runs = 0;
      let lastRecord: ThreadGoalOutcome | undefined;
      const api = mockLangGraphAPI(page, {
        ...chatPage.options,
        // The goal PUT and the run share the chat's own id, as on the Gateway.
        honorRequestedThreadId: true,
        createdThreadMessages: [],
        // Each goal is met on its own first run.
        runStreamHandler: async (route) => {
          runs += 1;
          const thread = api.getThread(runStreamThreadId(route))!;
          const turn = [
            ...(thread.messages ?? []),
            ...visibleRunInputMessages(route),
          ];
          const reply = {
            type: "ai",
            id: `goal-ai-${runs}`,
            content:
              runs === 1 ? "README: setup, usage and license." : nextReply,
          };
          const messages = [...turn, reply];
          const record = mockGoalOutcome(thread.goal as GoalState, reply.id);
          const earlier = lastRecord;
          lastRecord = record;
          return stream.serve(
            route,
            [
              // The turn's message events: the tab keeps the values it had,
              // an earlier goal's record included.
              { messages: turn, ...(earlier ? { goal_outcome: earlier } : {}) },
              // The clear of the met goal: the record, and no `goal` key at all.
              { messages, goal_outcome: record },
            ],
            () =>
              api.upsertThread({
                ...thread,
                goal: null,
                goal_outcome: record,
                messages,
              }),
          );
        },
      });

      try {
        await page.goto(`${chatPage.path}/new`);
        const textarea = composer(page);
        await expect(textarea).toBeVisible({ timeout: 15_000 });
        await textarea.fill(`/goal ${objective}`);
        await textarea.press("Enter");

        const bar = goalBar(page);
        await expect(bar).toHaveAttribute("data-goal-state", "met");
        await expect(bar).toContainText(`Goal met${objective}`);
        await expect(bar).not.toContainText("Auto-continued");
        await expect(
          page.getByText("README: setup, usage and license."),
        ).toBeVisible();
        await expect(page).not.toHaveURL(/\/new$/);
        await expect(
          page.getByRole("button", { name: "Edit and rerun" }),
        ).toBeEnabled();

        await page.reload();
        await expect(bar).toHaveAttribute("data-goal-state", "met", {
          timeout: 15_000,
        });
        await expect(bar).toContainText(`Goal met${objective}`);

        // A new goal replaces Goal met at once, and its own run meets it.
        await textarea.fill(`/goal ${next}`);
        await textarea.press("Enter");
        await expect(bar).toHaveAttribute("data-goal-state", "inProgress");
        await expect(bar).toContainText(next);
        await expect(bar).toHaveAttribute("data-goal-state", "met");
        await expect(bar).toContainText(`Goal met${next}`);
        await expect(bar).not.toContainText(objective);

        await textarea.fill("/goal clear");
        await textarea.press("Enter");
        await expect(page.getByText("Goal cleared.")).toBeVisible();
        await expect(bar).toBeHidden();
        await page.reload();
        await expect(page.getByText(nextReply)).toBeVisible({
          timeout: 15_000,
        });
        await expect(bar).toBeHidden();
        expect(runs).toBe(2);
      } finally {
        await stream.close();
      }
    });

    test("keeps the /goal draft when a run is still going", async ({
      page,
    }) => {
      const objective = "Finish the quarterly report";
      const api = mockLangGraphAPI(page, {
        ...chatPage.options,
        threads: [chatThread()],
      });
      let runStreams = 0;
      page.on("request", (request) => {
        if (
          request.method() === "POST" &&
          request.url().includes("/runs/stream")
        ) {
          runStreams += 1;
        }
      });
      await page.goto(threadUrl);
      const textarea = composer(page);
      const bar = goalBar(page);
      await expect(page.getByText("The README covers setup.")).toBeVisible({
        timeout: 15_000,
      });

      // Setting the goal: the Gateway's 409 keeps the draft for a retry.
      api.setGoalWritesBusy(true);
      await textarea.fill(`/goal ${objective}`);
      await textarea.press("Enter");
      await expect(page.getByText(BUSY)).toBeVisible();
      await expect(textarea).toHaveValue(`/goal ${objective}`);
      await expect(bar).toBeHidden();
      expect(runStreams).toBe(0);

      api.setGoalWritesBusy(false);
      await textarea.press("Enter");
      await expect(bar).toContainText(objective);
      await expect(textarea).toHaveValue("");
      await expect(page.getByText("Hello from DeerFlow!")).toBeVisible();
      expect(runStreams).toBe(1);

      // Clearing it: the same. The set half's toast closes first, so the busy
      // toast below can only be the clear's own.
      await expect(page.getByText(BUSY)).toHaveCount(0, { timeout: 10_000 });
      api.setGoalWritesBusy(true);
      await textarea.fill("/goal clear");
      const refused = page.waitForResponse(
        (response) =>
          response.request().method() === "DELETE" &&
          response.url().endsWith("/goal"),
      );
      await textarea.press("Enter");
      expect((await refused).status()).toBe(409);
      await expect(page.getByText(BUSY)).toBeVisible();
      await expect(textarea).toHaveValue("/goal clear");
      await expect(bar).toContainText(objective);

      api.setGoalWritesBusy(false);
      await textarea.press("Enter");
      await expect(page.getByText("Goal cleared.")).toBeVisible();
      await expect(bar).toBeHidden();
      await expect(textarea).toHaveValue("");
      expect(runStreams).toBe(1);
    });
  });
}
