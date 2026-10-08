// Drives the real LangGraph SDK useStream through the real useThreadStream,
// useActiveGoal and GoalStatus, with a fake client that sends the frames and
// history head the backend sends around a goal run.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { useState, type ReactNode } from "react";

import { GoalStatus } from "@/components/workspace/goal-status";
import { useActiveGoal } from "@/components/workspace/use-active-goal";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";
import { useThreadStream } from "@/core/threads/hooks";
import type { GoalState, ThreadGoalOutcome } from "@/core/threads/types";

type Frame = { event: string; data: unknown };

const HISTORY_HEAD_KEYS = (
  JSON.parse(
    readFileSync(
      resolve(__dirname, "../../../../../contracts/thread_goal_contract.json"),
      "utf-8",
    ),
  ) as { history_head_keys: string[] }
).history_head_keys;

/** The POST /history head: only the keys the backend projects onto it. */
function historyHead(values: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(values).filter(([key]) => HISTORY_HEAD_KEYS.includes(key)),
  );
}

const server = rs.hoisted(() => ({
  historyValues: {} as Record<string, unknown>,
  afterRunHistoryValues: null as Record<string, unknown> | null,
  frames: [] as { event: string; data: unknown }[],
  streamCalls: 0,
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    runs: {
      cancel: async () => undefined,
      joinStream: async function* () {
        // No reconnect in these tests.
      },
      list: async () => [],
      stream: async function* (
        threadId: string,
        _assistantId: string,
        payload?: {
          onRunCreated?: (meta: { run_id: string; thread_id: string }) => void;
        },
      ) {
        server.streamCalls += 1;
        payload?.onRunCreated?.({ run_id: "run-1", thread_id: threadId });
        for (const frame of server.frames) {
          // Separate macrotasks, so SDK throttling cannot merge the frames.
          await new Promise((resolve) => setTimeout(resolve, 15));
          yield frame;
        }
        if (server.afterRunHistoryValues) {
          server.historyValues = server.afterRunHistoryValues;
        }
      },
    },
    threads: {
      create: async ({ threadId }: { threadId?: string }) => ({
        thread_id: threadId ?? "thread-1",
      }),
      getHistory: async () => [
        {
          values: server.historyValues,
          next: [],
          tasks: [],
          metadata: {},
          created_at: "2026-10-07T00:00:00Z",
          checkpoint: {
            thread_id: "thread-1",
            checkpoint_ns: "",
            checkpoint_id: `ckpt-${server.streamCalls}`,
          },
          parent_checkpoint: null,
        },
      ],
      getState: async () => ({ values: server.historyValues }),
    },
  }),
}));

const GOAL: GoalState = {
  objective: "Write a three-line summary of README.md",
  status: "active",
  created_at: "2026-10-07T00:00:00Z",
  updated_at: "2026-10-07T00:00:00Z",
  continuation_count: 0,
  max_continuations: 8,
  no_progress_count: 0,
  max_no_progress_continuations: 2,
};

const HUMAN = { type: "human", id: "h-1", content: GOAL.objective } as Message;
const AI = { type: "ai", id: "ai-1", content: "Done: summary." } as Message;

const RECORD: ThreadGoalOutcome = {
  status: "achieved",
  objective: GOAL.objective,
  goal_created_at: GOAL.created_at,
  achieved_at: "2026-10-07T00:01:00Z",
  continuation_count: 0,
  max_continuations: 8,
  reason: "The summary has three lines.",
  relied_on_assumption: false,
  reply_message_id: "ai-1",
};

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        {children}
      </I18nContext.Provider>
    </QueryClientProvider>
  );
}

type Exposed = {
  sendMessage: ReturnType<typeof useThreadStream>["sendMessage"];
  setLocalGoal: ReturnType<typeof useActiveGoal>["setLocalGoal"];
  isLoading: boolean;
  hasGoal: boolean;
  hasGoalKey: boolean;
};

// Mirrors the chat pages: useThreadStream, then useActiveGoal on the thread's
// goal, record and messages, then the goal bar.
function Harness({
  startNew = false,
  expose,
}: {
  startNew?: boolean;
  expose: (value: Exposed) => void;
}) {
  const threadId = "thread-1";
  const [isNewThread, setIsNewThread] = useState(startNew);
  const { thread, sendMessage } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    displayThreadId: threadId,
    context: DEFAULT_LOCAL_SETTINGS.context,
    onStart: () => setIsNewThread(false),
  });
  const { activeGoal, hasGoal, goalOutcome, setLocalGoal } = useActiveGoal(
    threadId,
    thread.values.goal,
    thread.values.goal_outcome,
    thread.messages,
  );
  expose({
    sendMessage,
    setLocalGoal,
    isLoading: thread.isLoading,
    hasGoal,
    hasGoalKey: Object.hasOwn(thread.values, "goal"),
  });
  return (
    <GoalStatus
      goal={activeGoal}
      outcome={goalOutcome}
      isRunning={thread.isLoading}
    />
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  server.streamCalls = 0;
  server.frames = [];
  server.afterRunHistoryValues = null;
  server.historyValues = historyHead({ title: "Chat", messages: [] });
  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response(
          JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  rs.spyOn(console, "error").mockImplementation(() => undefined);
  rs.spyOn(console, "warn").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  rs.restoreAllMocks();
});

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });

function barState() {
  return screen.queryByTestId("goal-status")?.getAttribute("data-goal-state");
}

async function mountHarness(startNew = false) {
  let current!: Exposed;
  render(
    <Harness
      startNew={startNew}
      expose={(value) => {
        current = value;
      }}
    />,
    { wrapper },
  );
  await settle();
  return () => current;
}

/** `/goal <condition>`: the PUT result becomes the override, then the run starts. */
async function setGoalAndRun(current: () => Exposed) {
  act(() => current().setLocalGoal(GOAL, "set"));
  expect(barState()).toBe("set");
  await act(async () => {
    await current().sendMessage("thread-1", {
      text: GOAL.objective,
      files: [],
    });
  });
  await waitFor(() => expect(server.streamCalls).toBe(1));
  await waitFor(() => expect(current().isLoading).toBe(false));
  await settle();
}

describe.each([false, true])("a goal run (new chat: %s)", (startNew) => {
  it("met on the first run replaces the set bar with Goal met", async () => {
    // The satisfied clear: the frame drops the goal key and adds the record.
    server.frames = [
      { event: "metadata", data: { run_id: "run-1", thread_id: "thread-1" } },
      { event: "updates", data: { agent: { messages: [AI] } } },
      {
        event: "values",
        data: { title: "Chat", messages: [HUMAN, AI], goal_outcome: RECORD },
      },
    ] satisfies Frame[];
    server.afterRunHistoryValues = historyHead({
      title: "Chat",
      messages: [HUMAN, AI],
      goal_outcome: RECORD,
      todos: [],
    });

    const current = await mountHarness(startNew);
    await setGoalAndRun(current);

    expect(current().hasGoalKey).toBe(false);
    expect(current().hasGoal).toBe(false);
    expect(barState()).toBe("met");
    expect(screen.getByTestId("goal-status").textContent).toContain(
      `Goal met${GOAL.objective}`,
    );
  });

  it("keeps a stand-down and the edit lock through the post-run refetch", async () => {
    const stoodDown: GoalState = {
      ...GOAL,
      updated_at: "2026-10-07T00:01:00Z",
      last_evaluation: {
        satisfied: false,
        blocker: "missing_evidence",
        reason: "No summary was shown.",
        run_id: "run-1",
        stand_down_reason: "blocked:missing_evidence",
      },
    };
    server.frames = [
      { event: "metadata", data: { run_id: "run-1", thread_id: "thread-1" } },
      {
        event: "values",
        data: { title: "Chat", messages: [HUMAN, AI], goal: stoodDown },
      },
    ] satisfies Frame[];
    server.afterRunHistoryValues = historyHead({
      title: "Chat",
      messages: [HUMAN, AI],
      goal: stoodDown,
    });

    const current = await mountHarness(startNew);
    await setGoalAndRun(current);

    expect(current().hasGoal).toBe(true);
    expect(barState()).toBe("stopped");
    expect(screen.getByTestId("goal-status-detail").textContent).toBe(
      "Goal check: evidence missing. Ask it to show the result or explain what's missing; if the goal no longer applies, run /goal clear.",
    );
  });
});

describe("a met goal after a reload", () => {
  it("shows Goal met from the history head, and a new /goal set hides it", async () => {
    server.historyValues = historyHead({
      title: "Chat",
      messages: [HUMAN, AI],
      goal_outcome: { ...RECORD, continuation_count: 1 },
    });

    const current = await mountHarness();
    await waitFor(() => expect(barState()).toBe("met"));
    expect(screen.getByTestId("goal-status").textContent).toContain(
      "Auto-continued once",
    );
    expect(current().hasGoal).toBe(false);

    const next = {
      ...GOAL,
      objective: "Translate the summary",
      created_at: "2026-10-07T00:05:00Z",
      updated_at: "2026-10-07T00:05:00Z",
    };
    act(() => current().setLocalGoal(next, "set"));
    expect(barState()).toBe("set");
    expect(screen.getByTestId("goal-status").textContent).toBe(
      `Goal${next.objective}`,
    );
    expect(current().hasGoal).toBe(true);
  });
});
