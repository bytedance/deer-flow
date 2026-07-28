import type { Message } from "@langchain/langgraph-sdk";
import { expect, rs, test } from "@rstest/core";
import { InfiniteQueryObserver, QueryClient } from "@tanstack/react-query";

import {
  buildThreadMessagesPageUrl,
  buildVisibleHistoryMessages,
  areOptimisticMessagesConfirmed,
  computeSummarizationTransientMessages,
  flattenThreadHistoryPages,
  getSummarizationMiddlewareMessages,
  getThreadHistoryNextPageParam,
  getVisibleOptimisticMessages,
  mergeRenderedMessageLedger,
  mergeTransientHistoryBridge,
  mergeTransientHistoryBridgeOrder,
  mergeMessages,
  parseThreadMessagesPageResponse,
  pruneConfirmedTransientMessages,
  reconcileThreadHistoryRows,
  removeSetItems,
  resolveThreadTransientHistoryBridge,
  resolveTransientHistoryBridge,
  type ThreadMessagesPageResponse,
} from "@/core/threads/hooks";
import type { RunMessage } from "@/core/threads/types";

function runMessage(seq: number): RunMessage {
  return {
    run_id: "run-1",
    seq,
    content: {} as Message,
    metadata: { caller: "" },
    created_at: "2026-05-22T00:00:00Z",
  };
}

test("mergeMessages removes duplicate messages already present in history", () => {
  const human = {
    id: "human-1",
    type: "human",
    content: "Design an agent",
  } as Message;
  const ai = {
    id: "ai-1",
    type: "ai",
    content: "Let's design it.",
  } as Message;

  expect(mergeMessages([human, ai, human, ai], [], [])).toEqual([human, ai]);
});

test("mergeMessages does not collapse an unloaded gap before the first shared anchor", () => {
  const protectedEarly = {
    id: "protected-early",
    type: "human",
    content: "写一个算法PDF",
  } as Message;
  const latestHuman = {
    id: "latest-human",
    type: "human",
    content: "写一本超级小说",
  } as Message;
  const latestAi = {
    id: "latest-ai",
    type: "ai",
    content: "latest answer",
  } as Message;

  expect(
    mergeMessages([latestHuman, latestAi], [protectedEarly, latestHuman], []),
  ).toEqual([latestHuman, latestAi]);
});

test("mergeMessages lets live thread messages replace overlapping history", () => {
  const oldHuman = {
    id: "human-1",
    type: "human",
    content: "old",
  } as Message;
  const liveHuman = {
    id: "human-1",
    type: "human",
    content: "live",
  } as Message;
  const oldAi = {
    id: "ai-1",
    type: "ai",
    content: "old",
  } as Message;
  const liveAi = {
    id: "ai-1",
    type: "ai",
    content: "live",
  } as Message;

  expect(mergeMessages([oldHuman, oldAi], [liveHuman, liveAi], [])).toEqual([
    liveHuman,
    liveAi,
  ]);
});

test("mergeMessages preserves historical run metadata on a live checkpoint replacement", () => {
  const persistedAi = {
    id: "ai-1",
    type: "ai",
    content: "persisted",
    additional_kwargs: { turn_duration: 114 },
  } as Message;
  const history = buildVisibleHistoryMessages(
    [
      {
        run_id: "run-1",
        seq: 1,
        content: persistedAi,
        metadata: { caller: "lead_agent" },
        created_at: "2026-07-21T00:00:00Z",
      },
    ],
    new Set(),
  );
  const checkpointAi = {
    id: "ai-1",
    type: "ai",
    content: "live checkpoint",
  } as Message;

  expect(mergeMessages(history, [checkpointAi], [])).toEqual([
    {
      ...checkpointAi,
      run_id: "run-1",
      additional_kwargs: { turn_duration: 114 },
    },
  ]);
});

test("mergeMessages keeps a protected pre-compression input at its canonical position", () => {
  const canonicalInput = {
    id: "input-1",
    type: "human",
    content: "写一个算法PDF",
  } as Message;
  const checkpointInput = {
    id: "input-1",
    type: "human",
    content: [{ type: "text", text: "写一个算法PDF" }],
  } as Message;
  const clarificationCard = {
    id: "clarification-card",
    type: "tool",
    tool_call_id: "clarification-call",
    content: "Create a new PDF",
  } as Message;
  const directionAnswer = {
    id: "input-3",
    type: "human",
    content: "二叉树相关的即可",
  } as Message;
  const canonicalRetainedTail = {
    id: "retained-ai",
    type: "ai",
    content: "persisted tail",
  } as Message;
  const checkpointRetainedTail = {
    id: "retained-ai",
    type: "ai",
    content: "live tail",
  } as Message;

  expect(
    mergeMessages(
      [
        canonicalInput,
        clarificationCard,
        directionAnswer,
        canonicalRetainedTail,
      ],
      [checkpointInput, checkpointRetainedTail],
      [],
    ),
  ).toEqual([
    checkpointInput,
    clarificationCard,
    directionAnswer,
    checkpointRetainedTail,
  ]);
});

test("mergeMessages keeps source order when history and live tail do not overlap", () => {
  const historyAi = {
    id: "history-ai",
    type: "ai",
    content: "persisted",
  } as Message;
  const liveHuman = {
    id: "live-human",
    type: "human",
    content: "live",
  } as Message;

  expect(mergeMessages([historyAi], [liveHuman], [])).toEqual([
    historyAi,
    liveHuman,
  ]);
});

test("mergeMessages appends a trailing live-only segment after newer canonical rows", () => {
  const message = (id: string) =>
    ({ id, type: "human", content: id }) as Message;
  const [a, b, c, d, y] = ["a", "b", "c", "d", "y"].map(message) as [
    Message,
    Message,
    Message,
    Message,
    Message,
  ];

  expect(mergeMessages([a, b, c, d], [b, y], [])).toEqual([a, b, c, d, y]);
});

test("mergeMessages keeps live-only messages between shared anchors in place", () => {
  const message = (id: string) =>
    ({ id, type: "human", content: id }) as Message;
  const [a, b, c, d, x, y] = ["a", "b", "c", "d", "x", "y"].map(message) as [
    Message,
    Message,
    Message,
    Message,
    Message,
    Message,
  ];

  expect(mergeMessages([a, b, c, d], [b, x, d, y], [])).toEqual([
    a,
    b,
    c,
    x,
    d,
    y,
  ]);
});

test("mergeMessages deduplicates tool messages by tool_call_id", () => {
  const oldTool = {
    id: "tool-message-old",
    type: "tool",
    tool_call_id: "call-1",
    content: "old",
  } as Message;
  const liveTool = {
    id: "tool-message-live",
    type: "tool",
    tool_call_id: "call-1",
    content: "live",
  } as Message;

  expect(mergeMessages([oldTool], [liveTool], [])).toEqual([liveTool]);
});

test("mergeMessages keeps a visible history message when a hidden live message reuses its id", () => {
  const historyHuman = {
    id: "human-1",
    type: "human",
    content: "visible user prompt",
  } as Message;
  const hiddenReminder = {
    id: "human-1",
    type: "human",
    content: "<system-reminder>hidden</system-reminder>",
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const liveAi = {
    id: "ai-1",
    type: "ai",
    content: "live answer",
  } as Message;

  expect(mergeMessages([historyHuman], [hiddenReminder, liveAi], [])).toEqual([
    historyHuman,
    liveAi,
  ]);
});

test("mergeMessages lets a visible live message replace overlapping hidden history", () => {
  const hiddenHistoryHuman = {
    id: "human-1",
    type: "human",
    content: "<system-reminder>hidden</system-reminder>",
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const liveHuman = {
    id: "human-1",
    type: "human",
    content: "visible user prompt",
  } as Message;

  expect(mergeMessages([hiddenHistoryHuman], [liveHuman], [])).toEqual([
    liveHuman,
  ]);
});

test("getSummarizationMiddlewareMessages matches DeerFlow summarization update keys", () => {
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "DeerFlowSummarizationMiddleware.before_model": {
        messages: [removeAll, summary],
      },
    }),
  ).toEqual([removeAll, summary]);
});

test("getSummarizationMiddlewareMessages matches base LangChain summarization update keys", () => {
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "SummarizationMiddleware.before_model": {
        messages: [summary],
      },
    }),
  ).toEqual([summary]);
});

test("getSummarizationMiddlewareMessages ignores unrelated suffix-sharing update keys", () => {
  const summary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "summary",
  } as Message;

  expect(
    getSummarizationMiddlewareMessages({
      "OtherSummarizationMiddleware.before_model": {
        messages: [summary],
      },
    }),
  ).toBeUndefined();
});

test("getVisibleOptimisticMessages hides optimistic user input after server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 0, 1)).toEqual([]);
});

test("mergeMessages shows server human instead of optimistic duplicate after first response", () => {
  const serverHuman = {
    id: "server-human-1",
    type: "human",
    content: "hello",
  } as Message;
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;
  const visibleOptimistic = getVisibleOptimisticMessages(
    [optimisticHuman],
    0,
    1,
  );

  expect(mergeMessages([], [serverHuman], visibleOptimistic)).toEqual([
    serverHuman,
  ]);
});

test("getVisibleOptimisticMessages keeps optimistic user input until server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "hello",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 0, 0)).toEqual([
    optimisticHuman,
  ]);
});

test("getVisibleOptimisticMessages keeps non-human optimistic status messages", () => {
  const optimisticAi = {
    id: "opt-ai-1",
    type: "ai",
    content: "Uploading files...",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticAi], 0, 1)).toEqual([
    optimisticAi,
  ]);
});

test("getVisibleOptimisticMessages hides the upload optimistic pair after server human arrives", () => {
  const optimisticHuman = {
    id: "opt-human-1",
    type: "human",
    content: "upload this",
  } as Message;
  const optimisticUploadingAi = {
    id: "opt-ai-uploading",
    type: "ai",
    content: "Uploading files...",
  } as Message;

  expect(
    getVisibleOptimisticMessages(
      [optimisticHuman, optimisticUploadingAi],
      0,
      1,
    ),
  ).toEqual([]);
});

test("getVisibleOptimisticMessages hides optimistic user input after later server turns", () => {
  const optimisticHuman = {
    id: "opt-human-2",
    type: "human",
    content: "follow up",
  } as Message;

  expect(getVisibleOptimisticMessages([optimisticHuman], 3, 4)).toEqual([]);
  expect(getVisibleOptimisticMessages([optimisticHuman], 3, 3)).toEqual([
    optimisticHuman,
  ]);
});

test("areOptimisticMessagesConfirmed returns true when server messages contain every optimistic id", () => {
  const optimisticHuman = {
    id: "replacement-human-1",
    type: "human",
    content: "edited question",
  } as Message;
  const serverHuman = {
    id: "replacement-human-1",
    type: "human",
    content: "edited question",
  } as Message;
  const serverAi = {
    id: "replacement-ai-1",
    type: "ai",
    content: "new answer",
  } as Message;

  expect(
    areOptimisticMessagesConfirmed([optimisticHuman], [serverHuman, serverAi]),
  ).toBe(true);
});

test("areOptimisticMessagesConfirmed ignores optimistic messages without stable ids", () => {
  const optimisticHuman = {
    type: "human",
    content: "edited question",
  } as Message;

  expect(areOptimisticMessagesConfirmed([optimisticHuman], [])).toBe(false);
});

test("buildThreadMessagesPageUrl encodes the thread and backward cursor", () => {
  expect(
    buildThreadMessagesPageUrl(
      "https://api.example.test/",
      "thread/with space",
      18,
    ),
  ).toBe(
    "https://api.example.test/api/threads/thread%2Fwith%20space/messages/page?before_seq=18",
  );
});

test("buildThreadMessagesPageUrl omits before_seq for the latest page", () => {
  expect(
    buildThreadMessagesPageUrl("https://api.example.test", "thread-1"),
  ).toBe("https://api.example.test/api/threads/thread-1/messages/page");
});

test("buildThreadMessagesPageUrl returns a relative URL behind nginx", () => {
  expect(buildThreadMessagesPageUrl("", "thread-1", 42)).toBe(
    "/api/threads/thread-1/messages/page?before_seq=42",
  );
});

test("parseThreadMessagesPageResponse accepts a valid history page", () => {
  const response = {
    data: [runMessage(1), runMessage(2)],
    has_more: true,
    next_before_seq: 1,
  };

  expect(parseThreadMessagesPageResponse(response)).toBe(response);
});

test.each([
  ["missing", undefined],
  ["non-numeric", "2"],
  ["fractional", 2.5],
  ["unsafe", Number.MAX_SAFE_INTEGER + 1],
])(
  "parseThreadMessagesPageResponse rejects a %s row seq",
  (_description, seq) => {
    expect(() =>
      parseThreadMessagesPageResponse({
        data: [{ ...runMessage(1), seq }],
        has_more: false,
        next_before_seq: null,
      }),
    ).toThrow("invalid seq");
  },
);

test("parseThreadMessagesPageResponse rejects duplicate row seq values", () => {
  expect(() =>
    parseThreadMessagesPageResponse({
      data: [runMessage(1), runMessage(1)],
      has_more: false,
      next_before_seq: null,
    }),
  ).toThrow("duplicate seq");
});

test("parseThreadMessagesPageResponse rejects an invalid pagination cursor", () => {
  expect(() =>
    parseThreadMessagesPageResponse({
      data: [runMessage(1)],
      has_more: true,
      next_before_seq: null,
    }),
  ).toThrow("invalid next_before_seq");
});

test("flattenThreadHistoryPages prepends backward pages in global seq order", () => {
  expect(
    flattenThreadHistoryPages([
      {
        data: [runMessage(5), runMessage(6)],
        has_more: true,
        next_before_seq: 5,
      },
      {
        data: [runMessage(3), runMessage(4)],
        has_more: true,
        next_before_seq: 3,
      },
      {
        data: [runMessage(1), runMessage(2)],
        has_more: false,
        next_before_seq: null,
      },
    ]).map((message) => message.seq),
  ).toEqual([1, 2, 3, 4, 5, 6]);
});

test("flattenThreadHistoryPages retains backward pages when the latest page refreshes", () => {
  const olderPage = {
    data: [runMessage(1), runMessage(2)],
    has_more: false,
    next_before_seq: null,
  };

  expect(
    flattenThreadHistoryPages([
      {
        data: [runMessage(3), runMessage(4), runMessage(5)],
        has_more: true,
        next_before_seq: 3,
      },
      olderPage,
    ]).map((message) => message.seq),
  ).toEqual([1, 2, 3, 4, 5]);
});

test("reconcileThreadHistoryRows retains rows displaced from a moving latest page", () => {
  const previousRows = Array.from({ length: 50 }, (_, index) =>
    runMessage(index + 1),
  );
  const currentRows = Array.from({ length: 50 }, (_, index) =>
    runMessage(index + 51),
  );

  expect(
    reconcileThreadHistoryRows(previousRows, currentRows, false).map(
      (message) => message.seq,
    ),
  ).toEqual(Array.from({ length: 100 }, (_, index) => index + 1));
});

test("reconcileThreadHistoryRows refreshes overlapping rows without moving them", () => {
  const stale = runMessage(50);
  const refreshed = {
    ...runMessage(50),
    content: {
      id: "message-50",
      type: "ai",
      content: "final response",
      additional_kwargs: { turn_duration: 704 },
    } as Message,
  };

  const reconciled = reconcileThreadHistoryRows(
    [runMessage(49), stale],
    [refreshed, runMessage(51)],
    false,
  );

  expect(reconciled.map((message) => message.seq)).toEqual([49, 50, 51]);
  expect(reconciled[1]).toBe(refreshed);
});

test("reconcileThreadHistoryRows trusts a complete snapshot and prunes missing rows", () => {
  const currentRows = [runMessage(2), runMessage(3)];

  expect(
    reconcileThreadHistoryRows(
      [runMessage(1), ...currentRows],
      currentRows,
      true,
    ),
  ).toEqual(currentRows);
});

test("reconcileThreadHistoryRows preserves existing history when a row seq is invalid", () => {
  const previousRows = [runMessage(1), runMessage(2)];
  const invalidRow = {
    ...runMessage(3),
    seq: undefined,
  } as unknown as RunMessage;
  const consoleError = rs
    .spyOn(console, "error")
    .mockImplementation(() => undefined);

  expect(reconcileThreadHistoryRows(previousRows, [invalidRow], false)).toBe(
    previousRows,
  );
  expect(consoleError).toHaveBeenCalledOnce();

  consoleError.mockRestore();
});

test("reconcileThreadHistoryRows keeps insertion order on an invalid initial snapshot", () => {
  const first = {
    ...runMessage(1),
    seq: undefined,
    content: { id: "first", type: "human", content: "first" } as Message,
  } as unknown as RunMessage;
  const second = {
    ...runMessage(2),
    seq: undefined,
    content: { id: "second", type: "ai", content: "second" } as Message,
  } as unknown as RunMessage;
  const consoleError = rs
    .spyOn(console, "error")
    .mockImplementation(() => undefined);

  const currentRows = [first, second];

  expect(reconcileThreadHistoryRows([], currentRows, false)).toBe(currentRows);
  expect(consoleError).toHaveBeenCalledOnce();

  consoleError.mockRestore();
});

test("infinite history refetch recalculates older-page cursors from the refreshed newest page", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const queryKey = ["thread-messages", "thread-1"] as const;
  const requestedCursors: Array<number | null> = [];
  let availableSeqs = Array.from({ length: 9 }, (_, index) => index + 1);

  const observer = new InfiniteQueryObserver(queryClient, {
    queryKey,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }): ThreadMessagesPageResponse => {
      requestedCursors.push(pageParam);
      const eligible = availableSeqs.filter(
        (seq) => pageParam === null || seq < pageParam,
      );
      const pageSeqs = eligible.slice(-3);
      return {
        data: pageSeqs.map(runMessage),
        has_more: eligible.length > pageSeqs.length,
        next_before_seq:
          eligible.length > pageSeqs.length ? (pageSeqs[0] ?? null) : null,
      };
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });
  const unsubscribe = observer.subscribe(() => undefined);

  await observer.refetch();
  await observer.fetchNextPage();
  expect(requestedCursors).toEqual([null, 7]);

  availableSeqs = Array.from({ length: 12 }, (_, index) => index + 1);
  requestedCursors.length = 0;
  await queryClient.invalidateQueries({ queryKey });

  expect(requestedCursors).toEqual([null, 10]);
  expect(
    observer
      .getCurrentResult()
      .data?.pages.map((page) => page.data.map((message) => message.seq)),
  ).toEqual([
    [10, 11, 12],
    [7, 8, 9],
  ]);
  expect(observer.getCurrentResult().data?.pageParams).toEqual([null, 10]);

  unsubscribe();
  queryClient.clear();
});

test("infinite history stops and warns when has_more has no cursor", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const requestedCursors: Array<number | null> = [];
  const warnSpy = rs.spyOn(console, "warn").mockImplementation(() => ({}));
  const observer = new InfiniteQueryObserver(queryClient, {
    queryKey: ["thread-messages", "invalid-cursor"],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }): ThreadMessagesPageResponse => {
      requestedCursors.push(pageParam);
      return { data: [], has_more: true, next_before_seq: null };
    },
    getNextPageParam: getThreadHistoryNextPageParam,
  });
  const unsubscribe = observer.subscribe(() => undefined);

  try {
    await observer.refetch();
    await observer.fetchNextPage();

    expect(requestedCursors).toEqual([null]);
    expect(observer.getCurrentResult().hasNextPage).toBe(false);
    expect(warnSpy).toHaveBeenCalledWith(
      "Thread history returned has_more without next_before_seq; pagination cannot continue.",
    );
  } finally {
    unsubscribe();
    warnSpy.mockRestore();
    queryClient.clear();
  }
});

test("removeSetItems removes pending superseded ids after submit failure", () => {
  expect(
    removeSetItems(new Set(["run-old", "run-other"]), ["run-old"]),
  ).toEqual(new Set(["run-other"]));
});

test("buildVisibleHistoryMessages filters superseded runs but keeps regenerated run", () => {
  const oldHuman = {
    id: "human-1",
    type: "human",
    content: "question",
  } as Message;
  const oldAi = {
    id: "ai-old",
    type: "ai",
    content: "old answer",
  } as Message;
  const newHuman = {
    id: "human-1",
    type: "human",
    content: "question",
  } as Message;
  const newAi = {
    id: "ai-new",
    type: "ai",
    content: "new answer",
  } as Message;
  const rows: RunMessage[] = [
    {
      run_id: "run-old",
      seq: 1,
      content: oldHuman,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:00Z",
    },
    {
      run_id: "run-old",
      seq: 2,
      content: oldAi,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:01Z",
    },
    {
      run_id: "run-new",
      seq: 3,
      content: newHuman,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:02Z",
    },
    {
      run_id: "run-new",
      seq: 4,
      content: newAi,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-18T00:00:03Z",
    },
  ];

  // run_id is carried onto each content message (#3779) so historical subtask
  // cards can fetch their persisted step history on expand.
  expect(buildVisibleHistoryMessages(rows, new Set(["run-old"]))).toEqual([
    { ...newHuman, run_id: "run-new" },
    { ...newAi, run_id: "run-new" },
  ]);
});

test("buildVisibleHistoryMessages attaches run_id to each content message (#3779)", () => {
  const rows: RunMessage[] = [
    {
      run_id: "run-1",
      seq: 1,
      content: { id: "ai-1", type: "ai", content: "answer" } as Message,
      metadata: { caller: "lead_agent" },
      created_at: "2026-06-26T00:00:00Z",
    },
  ];

  const result = buildVisibleHistoryMessages(rows, new Set());

  expect((result[0] as { run_id?: string }).run_id).toBe("run-1");
});

// Regression coverage for #3825: after context summarization the backend emits
// RemoveMessage(ALL) + summary + retained, and onUpdateEvent rescues the removed
// messages into a current-stream transient bridge. The bridge fills only the
// journal flush/refetch gap and never mutates canonical history pages.

const summarizationHuman1 = {
  id: "human-1",
  type: "human",
  content: "round 1 question",
} as Message;
const summarizationAi1 = {
  id: "ai-1",
  type: "ai",
  content: "round 1 answer",
} as Message;
const summarizationHuman2 = {
  id: "human-2",
  type: "human",
  content: "round 2 question",
} as Message;
const summarizationAi2 = {
  id: "ai-2",
  type: "ai",
  content: "round 2 answer (retained)",
} as Message;
const summarizationMovedMessages = [
  summarizationHuman1,
  summarizationAi1,
  summarizationHuman2,
];

test("resolveTransientHistoryBridge keeps rescued messages while history state is stale", () => {
  const staleHistory: Message[] = [];

  expect(
    resolveTransientHistoryBridge(staleHistory, summarizationMovedMessages),
  ).toEqual(summarizationMovedMessages);
});

test("resolveTransientHistoryBridge appends rescued messages after canonical history", () => {
  const olderLoadedHuman = {
    id: "older-human",
    type: "human",
    content: "older loaded turn",
  } as Message;

  expect(
    resolveTransientHistoryBridge(
      [olderLoadedHuman],
      summarizationMovedMessages,
    ),
  ).toEqual([olderLoadedHuman, ...summarizationMovedMessages]);
});

test("resolveTransientHistoryBridge does not collapse an unloaded gap before its first canonical anchor", () => {
  // Real regression shape from thread 4e81444d-c6ce-471e-93fd-b6ddb18dc938:
  // the default history page starts at event seq=35, while the clarification
  // conversation lives at seq=2..14. Context compression captured both the
  // old turns and a later message that overlaps the canonical page. The old
  // turns must stay suppressed until their canonical page loads; otherwise
  // the unloaded seq=15..34 gap is visually collapsed before the page anchor.
  const clarificationRequest = {
    id: "clarification-request",
    type: "ai",
    content: "Which PDF should I create?",
  } as Message;
  const clarificationCard = {
    id: "clarification-card",
    tool_call_id: "clarification-call",
    type: "tool",
    content: "Create a new algorithm PDF",
  } as Message;
  const clarificationAnswer = {
    id: "clarification-answer",
    type: "human",
    content: "Create a new algorithm PDF",
  } as Message;
  const directionQuestion = {
    id: "direction-question",
    type: "ai",
    content: "Which topic?",
  } as Message;
  const directionAnswer = {
    id: "direction-answer",
    type: "human",
    content: "Binary trees",
  } as Message;
  const pageAnchor = {
    id: "event-seq-35",
    type: "tool",
    tool_call_id: "event-seq-35-call",
    content: "first message on the latest history page",
  } as Message;
  const latestAnswer = {
    id: "event-seq-88",
    type: "ai",
    content: "latest answer",
  } as Message;
  const captured = [
    summarizationHuman1,
    clarificationRequest,
    clarificationCard,
    clarificationAnswer,
    directionQuestion,
    directionAnswer,
    pageAnchor,
  ];
  const canonical = [pageAnchor, latestAnswer];
  const missingAfterCanonicalRefetch = pruneConfirmedTransientMessages(
    captured,
    canonical,
  );
  const bridgeOrder = mergeTransientHistoryBridgeOrder([], captured);

  expect(
    resolveTransientHistoryBridge(
      canonical,
      missingAfterCanonicalRefetch,
      bridgeOrder,
    ).map((message) => message.id),
  ).toEqual(["event-seq-35", "event-seq-88"]);
});

test("resolveTransientHistoryBridge restores a prefix that was already rendered", () => {
  const protectedPrompt = {
    id: "protected-prompt",
    type: "human",
    content: "/ppt-master 帮我做个ppt",
  } as Message;
  const intermediateReply = {
    id: "intermediate-reply",
    type: "ai",
    content: "正在生成页面",
  } as Message;
  const pageAnchor = {
    id: "page-anchor",
    type: "ai",
    content: "继续导出 SVG",
  } as Message;
  const latestAnswer = {
    id: "latest-answer",
    type: "ai",
    content: "任务仍在执行",
  } as Message;
  const captured = [protectedPrompt, intermediateReply, pageAnchor];
  const bridgeOrder = mergeTransientHistoryBridgeOrder([], captured);
  const previouslyRenderedOrder = [
    protectedPrompt,
    intermediateReply,
    pageAnchor,
    latestAnswer,
  ]
    .map((message) => `message:${message.id}`)
    .filter((identity): identity is string => Boolean(identity));

  expect(
    resolveTransientHistoryBridge(
      [pageAnchor, latestAnswer],
      captured,
      bridgeOrder,
      previouslyRenderedOrder,
    ).map((message) => message.id),
  ).toEqual([
    "protected-prompt",
    "intermediate-reply",
    "page-anchor",
    "latest-answer",
  ]);
});

test("resolveTransientHistoryBridge does not duplicate once canonical history catches up", () => {
  expect(
    resolveTransientHistoryBridge(
      summarizationMovedMessages,
      summarizationMovedMessages,
    ),
  ).toEqual(summarizationMovedMessages);
});

test("resolveTransientHistoryBridge returns history unchanged when the bridge is empty", () => {
  const history = [summarizationHuman1, summarizationAi1];
  expect(resolveTransientHistoryBridge(history, [])).toBe(history);
});

test("resolveThreadTransientHistoryBridge never leaks a bridge across threads", () => {
  const canonical = [
    { id: "older-human", type: "human", content: "older" } as Message,
  ];
  expect(
    resolveThreadTransientHistoryBridge(
      canonical,
      summarizationMovedMessages,
      "thread-a",
      "thread-b",
    ),
  ).toBe(canonical);
  expect(
    resolveThreadTransientHistoryBridge(
      canonical,
      summarizationMovedMessages,
      null,
      null,
    ),
  ).toBe(canonical);
  expect(
    resolveThreadTransientHistoryBridge(
      canonical,
      summarizationMovedMessages,
      "thread-a",
      "thread-a",
    ),
  ).toEqual([canonical[0], ...summarizationMovedMessages]);
});

test("mergeTransientHistoryBridge preserves chronology across repeated compression", () => {
  const human3 = {
    id: "human-3",
    type: "human",
    content: "round 3 question",
  } as Message;
  const firstBridge = mergeTransientHistoryBridge(
    [],
    [summarizationHuman1, summarizationAi1],
  );
  const secondBridge = mergeTransientHistoryBridge(firstBridge, [
    summarizationAi1,
    summarizationHuman2,
    human3,
  ]);

  expect(secondBridge.map((message) => message.id)).toEqual([
    "human-1",
    "ai-1",
    "human-2",
    "human-3",
  ]);
});

test("mergeTransientHistoryBridge does not move a protected input recaptured by later compression", () => {
  const protectedInput = {
    id: "protected-input",
    type: "human",
    content: "写一个算法PDF",
  } as Message;
  const clarification = {
    id: "clarification",
    type: "ai",
    content: "Which kind?",
  } as Message;
  const laterTail = {
    id: "later-tail",
    type: "ai",
    content: "Working on the PDF",
  } as Message;

  const firstBridge = mergeTransientHistoryBridge(
    [],
    [protectedInput, clarification],
  );
  const secondBridge = mergeTransientHistoryBridge(firstBridge, [
    { ...protectedInput, content: [{ type: "text", text: "写一个算法PDF" }] },
    laterTail,
  ]);

  expect(secondBridge.map((message) => message.id)).toEqual([
    "protected-input",
    "clarification",
    "later-tail",
  ]);
  expect(secondBridge[0]?.content).toEqual([
    { type: "text", text: "写一个算法PDF" },
  ]);
});

test("mergeTransientHistoryBridgeOrder retains confirmed overlap as a non-rendering anchor", () => {
  const firstOrder = mergeTransientHistoryBridgeOrder(
    [],
    [summarizationHuman1, summarizationAi1, summarizationHuman2],
  );
  const secondOrder = mergeTransientHistoryBridgeOrder(firstOrder, [
    summarizationHuman2,
    summarizationAi2,
  ]);

  expect(secondOrder).toEqual([
    "message:human-1",
    "message:ai-1",
    "message:human-2",
    "message:ai-2",
  ]);
});

test("mergeTransientHistoryBridgeOrder returns the same array when nothing is new", () => {
  const order = mergeTransientHistoryBridgeOrder(
    [],
    [summarizationHuman1, summarizationAi1],
  );

  // Identity, not just equality: this runs per render while the bridge is
  // active and feeds the coalesced render memo (#4409 Phase 1).
  expect(mergeTransientHistoryBridgeOrder(order, [summarizationAi1])).toBe(
    order,
  );
  expect(
    mergeTransientHistoryBridgeOrder(order, [
      summarizationHuman1,
      summarizationAi1,
    ]),
  ).toBe(order);
  expect(mergeTransientHistoryBridgeOrder(order, [])).toBe(order);
  expect(
    mergeTransientHistoryBridgeOrder(order, [summarizationHuman2]),
  ).not.toBe(order);
});

test("mergeTransientHistoryBridgeOrder keeps a recaptured protected prefix in place", () => {
  const protectedInput = {
    id: "protected-input",
    type: "human",
    content: "first",
  } as Message;
  const oldTail = {
    id: "old-tail",
    type: "ai",
    content: "old",
  } as Message;
  const newTail = {
    id: "new-tail",
    type: "ai",
    content: "new",
  } as Message;

  const firstOrder = mergeTransientHistoryBridgeOrder(
    [],
    [protectedInput, oldTail],
  );
  const secondOrder = mergeTransientHistoryBridgeOrder(firstOrder, [
    protectedInput,
    newTail,
  ]);

  expect(secondOrder).toEqual([
    "message:protected-input",
    "message:old-tail",
    "message:new-tail",
  ]);
});

test("merge keeps the full conversation across summarization even when visibleHistory lags (regression for #3825)", () => {
  // Hidden summary (name === "summary") + the retained latest answer is all the
  // live thread carries after RemoveMessage(ALL).
  const hiddenSummary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "conversation summary",
  } as Message;
  const postSummaryThread = [hiddenSummary, summarizationAi2];

  // The bad render: visibleHistory is still empty, so without the buffer the
  // rescued round-1/2 messages exist in neither merge input and are lost.
  const effectiveHistory = resolveTransientHistoryBridge(
    [],
    summarizationMovedMessages,
  );
  const merged = mergeMessages(effectiveHistory, postSummaryThread, []);

  expect(merged.map((m) => m.id)).toEqual([
    "human-1",
    "ai-1",
    "human-2",
    "summary-1",
    "ai-2",
  ]);
});

test("pruneConfirmedTransientMessages drops canonical identities but keeps the rest", () => {
  // History has caught up on the first two rescued messages only.
  expect(
    pruneConfirmedTransientMessages(summarizationMovedMessages, [
      summarizationHuman1,
      summarizationAi1,
    ]),
  ).toEqual([summarizationHuman2]);
});

test("pruneConfirmedTransientMessages keeps entries while canonical history is stale", () => {
  expect(
    pruneConfirmedTransientMessages(summarizationMovedMessages, []),
  ).toEqual(summarizationMovedMessages);
});

test("resolveTransientHistoryBridge prefers canonical copy over stale transient copy", () => {
  // Same identity, but the buffered copy is an older snapshot. The live history
  // copy (e.g. the finalized answer) must win — the buffer only fills gaps, it
  // must never overwrite a message history already shows.
  const staleBuffered = {
    id: "ai-1",
    type: "ai",
    content: "streaming partial",
  } as Message;
  const liveFinal = {
    id: "ai-1",
    type: "ai",
    content: "finalized answer",
  } as Message;

  expect(resolveTransientHistoryBridge([liveFinal], [staleBuffered])).toEqual([
    liveFinal,
  ]);
});

test("computeSummarizationTransientMessages captures live turns dropped before the retained boundary", () => {
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const hiddenSummary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "conversation summary",
  } as Message;
  const liveThreadBeforeSummary = [
    summarizationHuman1,
    summarizationAi1,
    summarizationHuman2,
    summarizationAi2,
  ];
  // Summarization emits RemoveMessage(ALL) + hidden summary + retained answer.
  const summarizationMessages = [removeAll, hiddenSummary, summarizationAi2];

  expect(
    computeSummarizationTransientMessages(
      liveThreadBeforeSummary,
      summarizationMessages,
      new Set([hiddenSummary.id!]),
    ),
  ).toEqual([summarizationHuman1, summarizationAi1, summarizationHuman2]);
});

test("computeSummarizationTransientMessages rescues rendered processing steps missing from a stale live snapshot", () => {
  const processingMessages = Array.from({ length: 10 }, (_, index) => {
    const step = index + 1;
    return {
      id: `processing-${step}`,
      type: step % 2 === 0 ? "tool" : "ai",
      ...(step % 2 === 0 ? { tool_call_id: `call-${step - 1}` } : {}),
      content: `step ${step}`,
    } as Message;
  });
  // The SDK has already advanced to the 10-message post-compaction window,
  // while the UI's previous committed frame still contains steps 1..10.
  const staleLiveSnapshot = processingMessages.slice(4);
  const summarizationMessages = [
    {
      id: "__remove_all__",
      type: "remove",
      content: "",
    } as Message,
    ...staleLiveSnapshot,
  ];

  expect(
    computeSummarizationTransientMessages(
      staleLiveSnapshot,
      summarizationMessages,
      new Set(),
      processingMessages,
    ),
  ).toEqual(processingMessages.slice(0, 4));
});

test("computeSummarizationTransientMessages rescues steps between a protected input and retained tail", () => {
  const protectedInput = {
    id: "protected-input",
    type: "human",
    content: "Run a long sequential research task",
  } as Message;
  const removedSteps = Array.from({ length: 4 }, (_, index) => ({
    id: `protected-window-step-${index + 1}`,
    type: "ai",
    content: `completed ${index + 1}`,
  })) as Message[];
  const retainedTail = {
    id: "retained-tail",
    type: "tool",
    tool_call_id: "retained-call",
    content: "latest search result",
  } as Message;
  const renderedMessages = [protectedInput, ...removedSteps, retainedTail];
  const retainedWindow = [protectedInput, retainedTail];

  expect(
    computeSummarizationTransientMessages(
      retainedWindow,
      [
        {
          id: "__remove_all__",
          type: "remove",
          content: "",
        } as Message,
        ...retainedWindow,
      ],
      new Set(),
      renderedMessages,
    ),
  ).toEqual(removedSteps);
});

test("repeated compaction keeps every previously rendered processing step in order", () => {
  const processingMessages = Array.from({ length: 12 }, (_, index) => {
    const step = index + 1;
    return {
      id: `repeat-processing-${step}`,
      type: step % 2 === 0 ? "tool" : "ai",
      ...(step % 2 === 0 ? { tool_call_id: `repeat-call-${step - 1}` } : {}),
      content: `step ${step}`,
    } as Message;
  });
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;

  const firstTail = processingMessages.slice(4, 10);
  const firstMoved = computeSummarizationTransientMessages(
    firstTail,
    [removeAll, ...firstTail],
    new Set(),
    processingMessages.slice(0, 10),
  );
  const firstBridge = mergeTransientHistoryBridge([], firstMoved);
  const firstMerged = mergeMessages(firstBridge, firstTail, []);

  const secondTail = processingMessages.slice(6);
  const secondMoved = computeSummarizationTransientMessages(
    secondTail,
    [removeAll, ...secondTail],
    new Set(),
    processingMessages,
  );
  const secondBridge = mergeTransientHistoryBridge(firstBridge, secondMoved);
  const secondMerged = mergeMessages(secondBridge, secondTail, []);

  expect(firstMerged.map((message) => message.id)).toEqual(
    processingMessages.slice(0, 10).map((message) => message.id),
  );
  expect(secondMerged.map((message) => message.id)).toEqual(
    processingMessages.map((message) => message.id),
  );
});

test("rendered message ledger survives rolling live windows before repeated compaction", () => {
  const processingMessages = Array.from({ length: 23 }, (_, index) => {
    const step = index + 1;
    return {
      id: `rolling-processing-${step}`,
      type: "ai",
      content: `completed ${step}/26`,
    } as Message;
  });
  const firstVisibleWindow = processingMessages.slice(0, 13);
  const secondVisibleWindow = processingMessages.slice(8, 18);
  const thirdVisibleWindow = processingMessages.slice(13);

  const firstLedger = mergeRenderedMessageLedger([], firstVisibleWindow);
  const secondLedger = mergeRenderedMessageLedger(
    firstLedger,
    secondVisibleWindow,
  );
  const thirdLedger = mergeRenderedMessageLedger(
    secondLedger,
    thirdVisibleWindow,
  );

  expect(thirdLedger.map((message) => message.id)).toEqual(
    processingMessages.map((message) => message.id),
  );

  // A later compaction retains only 19..23. The accumulated display ledger
  // must still supply 14..18 (and every older displayed step) to the bridge.
  const retainedTail = processingMessages.slice(18);
  const moved = computeSummarizationTransientMessages(
    retainedTail,
    [
      {
        id: "__remove_all__",
        type: "remove",
        content: "",
      } as Message,
      ...retainedTail,
    ],
    new Set(),
    thirdLedger,
  );

  expect(moved.map((message) => message.id)).toEqual(
    processingMessages.slice(0, 18).map((message) => message.id),
  );
});

test("rendered message ledger does not retain explicitly superseded messages", () => {
  const retained = {
    id: "retained-answer",
    type: "ai",
    content: "keep me",
  } as Message;
  const superseded = {
    id: "superseded-answer",
    type: "ai",
    content: "replace me",
  } as Message;

  expect(
    mergeRenderedMessageLedger(
      [retained, superseded],
      [retained],
      new Set([superseded.id!]),
    ),
  ).toEqual([retained]);
});

test("computeSummarizationTransientMessages excludes already-summarized control messages", () => {
  const priorSummary = {
    id: "summary-0",
    type: "human",
    name: "summary",
    content: "earlier summary",
  } as Message;
  const liveThreadBeforeSummary = [
    priorSummary,
    summarizationHuman1,
    summarizationAi1,
    summarizationAi2,
  ];
  const summarizationMessages = [
    { id: "__remove_all__", type: "remove", content: "" } as Message,
    {
      id: "summary-1",
      type: "human",
      name: "summary",
      content: "new summary",
    } as Message,
    summarizationAi2,
  ];

  // priorSummary is in the summarized set, so it must not enter the bridge.
  expect(
    computeSummarizationTransientMessages(
      liveThreadBeforeSummary,
      summarizationMessages,
      new Set([priorSummary.id!, "summary-1"]),
    ),
  ).toEqual([summarizationHuman1, summarizationAi1]);
});

test("full summarization rescue pipeline keeps the conversation when history state lags (regression for #3825)", () => {
  // Exercises the whole rescue algorithm the hook runs: derive the moved
  // messages, buffer them, then merge against the post-summary thread while the
  // canonical run-event page is still stale (empty).
  const removeAll = {
    id: "__remove_all__",
    type: "remove",
    content: "",
  } as Message;
  const hiddenSummary = {
    id: "summary-1",
    type: "human",
    name: "summary",
    content: "conversation summary",
  } as Message;
  const liveThreadBeforeSummary = [
    summarizationHuman1,
    summarizationAi1,
    summarizationHuman2,
    summarizationAi2,
  ];
  const summarizationMessages = [removeAll, hiddenSummary, summarizationAi2];

  const moved = computeSummarizationTransientMessages(
    liveThreadBeforeSummary,
    summarizationMessages,
    new Set([hiddenSummary.id!]),
  );
  const staleHistory: Message[] = [];
  const postSummaryThread = [hiddenSummary, summarizationAi2];

  const merged = mergeMessages(
    resolveTransientHistoryBridge(staleHistory, moved),
    postSummaryThread,
    [],
  );

  expect(merged.map((m) => m.id)).toEqual([
    "human-1",
    "ai-1",
    "human-2",
    "summary-1",
    "ai-2",
  ]);
});

test("refresh reconstructs the same 1-to-6 order from run events without a bridge", () => {
  const canonical = Array.from({ length: 6 }, (_, index) => ({
    id: `message-${index + 1}`,
    type: index % 2 === 0 ? "human" : "ai",
    content: String(index + 1),
  })) as Message[];
  const checkpointTail = canonical.slice(4);

  expect(
    mergeMessages(canonical, checkpointTail, []).map(
      (message) => message.content,
    ),
  ).toEqual(["1", "2", "3", "4", "5", "6"]);
});
