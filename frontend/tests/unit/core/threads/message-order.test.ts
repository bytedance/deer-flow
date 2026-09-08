import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { getMessageRunId } from "@/core/messages/run-duration";
import {
  buildVisibleHistoryMessages,
  mergeRenderedMessageLedger,
  mergeMessages,
  resolveThreadTransientHistoryBridge,
  resolveTransientHistoryBridge,
} from "@/core/threads/hooks";
import {
  dedupeMessagesByIdentity,
  insertByTrustedSeq,
  MESSAGE_SEQ_KEY,
  mergeMessages as mergeMessagesFromModule,
  messageIdentity,
  trustedMessageSeq,
} from "@/core/threads/message-order";
import type { RunMessage } from "@/core/threads/types";

// mergeMessages is re-exported from hooks for compatibility; both names must
// resolve to the same implementation.
expect(mergeMessagesFromModule).toBe(mergeMessages);

function msg(
  id: string,
  type: "human" | "ai" | "tool" | "system",
  content: string,
  seq?: number,
  extra?: Record<string, unknown>,
): Message {
  return {
    id,
    type,
    content,
    ...(extra ?? {}),
    additional_kwargs: seq !== undefined ? { [MESSAGE_SEQ_KEY]: seq } : {},
  } as Message;
}

function withKwargs(
  message: Message,
  kwargs: Record<string, unknown>,
): Message {
  return {
    ...message,
    additional_kwargs: { ...message.additional_kwargs, ...kwargs },
  } as Message;
}

function row(
  runId: string,
  seq: number,
  content: Message,
  index = 0,
): RunMessage {
  return {
    run_id: runId,
    seq,
    content,
    metadata: { caller: "lead_agent" },
    created_at: `2026-09-08T00:00:${String(index).padStart(2, "0")}Z`,
  };
}

function seqsOf(messages: Message[]): unknown[] {
  return messages.map(
    (message) => message.additional_kwargs?.[MESSAGE_SEQ_KEY],
  );
}

function idsOf(messages: Message[]): (string | undefined)[] {
  return messages.map((message) => message.id);
}

test("messageIdentity collapses X and X__user and keys tools by tool_call_id", () => {
  expect(messageIdentity(msg("req-1", "human", "q"))).toBe("message:req-1");
  expect(messageIdentity(msg("req-1__user", "human", "q"))).toBe(
    "message:req-1",
  );
  // Only human copies collapse: a hidden system reminder legitimately reuses
  // the original id and keeps its own identity.
  expect(messageIdentity(msg("req-1", "system", "reminder"))).toBe(
    "message:req-1",
  );
  expect(
    messageIdentity({
      id: "tool-own-id",
      type: "tool",
      content: "result",
      tool_call_id: "call-1",
    } as Message),
  ).toBe("tool:call-1");
});

test("trustedMessageSeq accepts only positive safe integers", () => {
  expect(trustedMessageSeq(msg("a", "ai", "x", 3))).toBe(3);
  expect(trustedMessageSeq(msg("a", "ai", "x"))).toBeUndefined();
  const invalid = [
    null,
    "7",
    Number.NaN,
    1.5,
    0,
    -2,
    Number.MAX_SAFE_INTEGER + 1,
  ];
  for (const value of invalid) {
    expect(
      trustedMessageSeq(
        withKwargs(msg("a", "ai", "x"), { [MESSAGE_SEQ_KEY]: value }),
      ),
      `seq=${String(value)}`,
    ).toBeUndefined();
  }
});

test("live content refresh without seq preserves seq, run_id, and turn_duration", () => {
  const history = [
    withKwargs(
      {
        ...msg("h1", "human", "question", 1),
        run_id: "run-1",
      } as unknown as Message,
      { turn_duration: 42 },
    ),
    msg("a1", "ai", "draft", 2),
  ];
  const live = [msg("h1", "human", "question"), msg("a1", "ai", "final")];

  const merged = mergeMessages(history, live, []);

  expect(idsOf(merged)).toEqual(["h1", "a1"]);
  expect(merged.map((message) => message.content)).toEqual([
    "question",
    "final",
  ]);
  expect(seqsOf(merged)).toEqual([1, 2]);
  expect(getMessageRunId(merged[0]!)).toBe("run-1");
  expect(merged[0]!.additional_kwargs?.turn_duration).toBe(42);
});

test("hidden control copy never overwrites the visible human or its position", () => {
  // DynamicContextMiddleware shape: hidden SystemMessage(id=X) plus the
  // visible HumanMessage(id=X__user). One visible message survives, carrying
  // the trusted position.
  const hiddenControl = withKwargs(msg("req-1", "system", "reminder", 4), {
    hide_from_ui: true,
  });
  const visibleHuman = msg("req-1__user", "human", "real question", 5);

  const merged = mergeMessages(
    [visibleHuman],
    [hiddenControl, msg("req-1__user", "human", "real question")],
    [],
  );

  expect(idsOf(merged)).toEqual(["req-1__user"]);
  // The surviving message is the visible human — never the hidden control —
  // and the hidden reminder's earlier row does not drag it off its visible
  // position.
  expect(merged[0]!.type).toBe("human");
  expect(merged[0]!.additional_kwargs?.[MESSAGE_SEQ_KEY]).toBe(5);
});

test("tool results dedupe by tool_call_id and keep the known position", () => {
  const historyTool = {
    id: "tool-old-row",
    type: "tool",
    content: "partial",
    tool_call_id: "call-1",
    additional_kwargs: { [MESSAGE_SEQ_KEY]: 6 },
  } as Message;
  const liveTool = {
    id: "tool-new-row",
    type: "tool",
    content: "complete",
    tool_call_id: "call-1",
  } as Message;

  const merged = mergeMessages(
    [msg("h1", "human", "q", 5), historyTool],
    [msg("h1", "human", "q"), liveTool],
    [],
  );

  expect(merged).toHaveLength(2);
  const tool = merged.find((message) => message.type === "tool")!;
  expect(tool.content).toBe("complete");
  expect(tool.tool_call_id).toBe("call-1");
  expect(tool.additional_kwargs?.[MESSAGE_SEQ_KEY]).toBe(6);
});

test("invalid seq values never overwrite a trusted position or break the merge", () => {
  const invalid = [null, "7", Number.NaN, 1.5, Number.MAX_SAFE_INTEGER + 1];
  for (const bad of invalid) {
    const history = [msg("h1", "human", "q", 3), msg("a1", "ai", "a", 4)];
    const live = [
      withKwargs(msg("h1", "human", "q"), { [MESSAGE_SEQ_KEY]: bad }),
      withKwargs(msg("a1", "ai", "a2"), { [MESSAGE_SEQ_KEY]: bad }),
    ];
    const merged = mergeMessages(history, live, []);
    expect(idsOf(merged), `seq=${String(bad)}`).toEqual(["h1", "a1"]);
    expect(seqsOf(merged), `seq=${String(bad)}`).toEqual([3, 4]);
    expect(merged[1]!.content).toBe("a2");
  }
});

test("a live-only message with seq fills the window-internal gap (1,3,5 + 2,5)", () => {
  const history = [
    msg("h1", "human", "first", 1),
    msg("a1", "ai", "second", 3),
    msg("a2", "ai", "last", 5),
  ];
  const live = [msg("h2", "human", "middle", 2), msg("a2", "ai", "last", 5)];

  expect(seqsOf(mergeMessages(history, live, []))).toEqual([1, 2, 3, 5]);
});

test("seq positions merge even when the two sides share no identity", () => {
  const history = [
    msg("old-1", "human", "old q", 10),
    msg("old-2", "ai", "old a", 11),
  ];
  const live = [
    msg("rescued", "human", "rescued turn", 2),
    msg("tail-step", "ai", "streaming step"),
  ];

  const merged = mergeMessages(history, live, []);

  expect(idsOf(merged)).toEqual(["rescued", "old-1", "old-2", "tail-step"]);
});

test("two no-seq segments between known anchors keep their internal order", () => {
  const history = [msg("h1", "human", "q1", 1), msg("a9", "ai", "a9", 9)];
  const live = [
    msg("h1", "human", "q1"),
    msg("s1", "ai", "step 1"),
    msg("s2", "tool", "step 2"),
    msg("a9", "ai", "a9"),
    msg("s3", "ai", "step 3"),
    msg("s4", "ai", "step 4"),
  ];

  const merged = mergeMessages(history, live, []);

  expect(idsOf(merged)).toEqual(["h1", "s1", "s2", "a9", "s3", "s4"]);
});

test("repeated feed updates keep latest content at the earliest visible position", () => {
  // Real feed shape for an identity persisted by several run events: the same
  // message id occupies multiple rows. The backend resolves such an identity
  // to its earliest feed position (get_message_seqs), so the visible copy
  // must carry the newest content with the earliest seq.
  const rows = [
    row("run-1", 1, msg("h1", "human", "question"), 0),
    row("run-1", 2, msg("a1", "ai", "first draft"), 1),
    row("run-1", 3, msg("a1", "ai", "updated answer"), 2),
  ];

  const visible = buildVisibleHistoryMessages(rows, new Set());

  expect(visible.map((message) => message.content)).toEqual([
    "question",
    "updated answer",
  ]);
  expect(seqsOf(visible)).toEqual([1, 2]);
});

test("a hidden control row does not contribute the visible position", () => {
  const hiddenRow = row(
    "run-1",
    2,
    withKwargs(msg("req-1", "system", "reminder"), { hide_from_ui: true }),
    0,
  );
  const visibleRow = row("run-1", 5, msg("req-1__user", "human", "q"), 1);

  const visible = buildVisibleHistoryMessages(
    [visibleRow, hiddenRow],
    new Set(),
  );

  expect(visible).toHaveLength(1);
  expect(visible[0]!.type).toBe("human");
  // Earliest *visible* row wins; the hidden control copy at seq 2 must not
  // pull the user message forward.
  expect(visible[0]!.additional_kwargs?.[MESSAGE_SEQ_KEY]).toBe(5);
});

test("an established seq order is never reversed by a conflicting live order", () => {
  const history = [msg("h1", "human", "q", 1), msg("a1", "ai", "a", 2)];
  // Live delivers the same identities in inverted order: the skeleton keeps
  // the server-settled sequence.
  const live = [msg("a1", "ai", "a", 2), msg("h1", "human", "q", 1)];

  expect(seqsOf(mergeMessages(history, live, []))).toEqual([1, 2]);
});

test("merging is idempotent and insensitive to duplicate redelivery order", () => {
  const history = [
    msg("h1", "human", "q1", 1),
    msg("a1", "ai", "a1", 2),
    msg("h2", "human", "q2", 4),
  ];
  const live = [msg("a2", "ai", "a2 streaming", 5), msg("h2", "human", "q2")];
  const optimistic = [msg("opt-1", "human", "draft")];

  const once = mergeMessages(history, live, optimistic);
  const twice = mergeMessages(once, live, optimistic);
  expect(idsOf(twice)).toEqual(idsOf(once));
  expect(seqsOf(twice)).toEqual(seqsOf(once));

  // The same deterministic information delivered in a different order
  // converges to the same sequence (optimistic tail keeps arrival order).
  const reordered = mergeMessages(
    [...history].reverse(),
    [...live].reverse(),
    optimistic,
  );
  expect(idsOf(reordered)).toEqual(idsOf(once));
});

test("mergeMessages never mutates its inputs", () => {
  const history = [msg("h1", "human", "q", 1)];
  const live = [msg("h1", "human", "q"), msg("a1", "ai", "a")];
  const historySnapshot = JSON.stringify(history);
  const liveSnapshot = JSON.stringify(live);

  mergeMessages(history, live, []);

  expect(JSON.stringify(history)).toBe(historySnapshot);
  expect(JSON.stringify(live)).toBe(liveSnapshot);
});

test("two compactions with a moving window keep visible identities and never revive superseded runs", () => {
  // Turn 1 and 2 rendered; compaction 1 retains a tail; the page window moves;
  // compaction 2 fires. Across both cycles every displayed identity survives
  // in ascending seq order, and the superseded run's rows stay hidden.
  const supersededRun = "run-old";
  const rows = [
    row(supersededRun, 1, msg("h-old", "human", "superseded question"), 0),
    row(supersededRun, 2, msg("a-old", "ai", "superseded answer"), 1),
    row("run-2", 3, msg("h1", "human", "q1"), 2),
    row("run-2", 4, msg("a1", "ai", "a1"), 3),
    row("run-3", 5, msg("h2", "human", "q2"), 4),
    row("run-3", 6, msg("a2", "ai", "a2"), 5),
  ];
  const history = buildVisibleHistoryMessages(rows, new Set([supersededRun]));
  expect(idsOf(history)).toEqual(["h1", "a1", "h2", "a2"]);

  // First compaction: live window keeps only the recent tail.
  const firstLedger = mergeRenderedMessageLedger([], history);
  const firstCompactionLive = [msg("h2", "human", "q2"), msg("a2", "ai", "a2")];
  const afterFirst = mergeMessages(history, firstCompactionLive, []);
  expect(idsOf(afterFirst)).toEqual(["h1", "a1", "h2", "a2"]);

  // The window moves: the refreshed page no longer reaches turn 1. The
  // rendered ledger still anchors it.
  const movedWindow = [msg("h2", "human", "q2", 5), msg("a2", "ai", "a2", 6)];
  const ledger = mergeRenderedMessageLedger(firstLedger, movedWindow);
  // Second compaction removes everything again; the ledger plus the fresh
  // window must still reconstruct the full visible conversation in order.
  const afterSecond = mergeMessages(ledger, movedWindow, []);
  expect(idsOf(afterSecond)).toEqual(["h1", "a1", "h2", "a2"]);
  expect(seqsOf(afterSecond)).toEqual([3, 4, 5, 6]);
  // Superseded rows never reappear, even though the ledger has seen them not.
  expect(idsOf(afterSecond)).not.toContain("h-old");
  expect(idsOf(afterSecond)).not.toContain("a-old");
});

test("bridge resolution never inherits positions across threads", () => {
  const historyB = [msg("hb", "human", "thread B question", 1)];
  const transientA = [msg("ha", "human", "thread A rescued", 7)];

  // Wrong-thread bridge is rejected outright, seq or not.
  expect(
    resolveThreadTransientHistoryBridge(
      historyB,
      transientA,
      "thread-a",
      "thread-b",
    ),
  ).toBe(historyB);
});

test("bridge places a rescued message with trusted seq inside the loaded window", () => {
  const history = [msg("h1", "human", "q1", 1), msg("a1", "ai", "a1", 3)];
  const rescued = [msg("mid", "ai", "rescued step", 2)];

  const resolved = resolveTransientHistoryBridge(history, rescued);

  expect(idsOf(resolved)).toEqual(["h1", "mid", "a1"]);
  expect(seqsOf(resolved)).toEqual([1, 2, 3]);
});

test("insertByTrustedSeq keeps the tail for positions beyond every known seq", () => {
  const base = [msg("h1", "human", "q", 1), msg("a1", "ai", "a", 2)];
  const positioned = [msg("new", "ai", "late", 9)];
  expect(idsOf(insertByTrustedSeq(base, positioned))).toEqual([
    "h1",
    "a1",
    "new",
  ]);
  expect(insertByTrustedSeq(base, [])).toBe(base);
});

test("dedupeMessagesByIdentity keeps the last visible copy per identity", () => {
  const hidden = withKwargs(msg("x", "human", "hidden"), {
    hide_from_ui: true,
  });
  const visible = msg("x", "human", "visible");
  expect(dedupeMessagesByIdentity([hidden, visible])).toEqual([visible]);
});

test("a seq carried only by a hidden control copy still positions its visible twin", () => {
  // Fallback path: no *visible* copy of the identity carries a seq, so the
  // hidden control copy's valid seq is the only trustworthy position. Using
  // it keeps the visible twin inside the skeleton instead of dropping it to
  // the unpositioned tail; a visible copy with its own seq would win instead
  // (covered by the hidden-control test above).
  const hiddenControl = withKwargs(msg("m1", "system", "control", 2), {
    hide_from_ui: true,
  });
  const history = [
    msg("h0", "human", "q", 1),
    hiddenControl,
    msg("a3", "ai", "tail", 3),
  ];
  const live = [msg("m1", "ai", "visible twin")];

  const merged = mergeMessages(history, live, []);

  expect(idsOf(merged)).toEqual(["h0", "m1", "a3"]);
  expect(seqsOf(merged)).toEqual([1, 2, 3]);
  expect(merged[1]!.content).toBe("visible twin");
});

test("live-only sequenced results anchor preceding unsequenced steps", () => {
  const start = msg("start", "human", "start", 1);
  const end = msg("end", "ai", "end", 9);
  const step = msg("step", "ai", "step");
  const result = msg("result", "ai", "result", 3);
  expect(
    idsOf(mergeMessages([start, end], [start, step, result, end], [])),
  ).toEqual(["start", "step", "result", "end"]);
});

test.each(["before", "after"] as const)(
  "bridge keeps an unsequenced step %s its rescued sequenced neighbor",
  (side) => {
    const start = msg("start", "human", "start", 1);
    const end = msg("end", "ai", "end", 9);
    const step = msg("step", "ai", "step");
    const result = msg("result", "ai", "result", 3);
    const rescued = side === "before" ? [step, result] : [result, step];
    const previous = [start, ...rescued, end];
    const order = previous.map((message) => messageIdentity(message)!);
    const resolved = resolveTransientHistoryBridge(
      [start, end],
      rescued,
      order,
      order,
    );
    expect(idsOf(resolved)).toEqual(idsOf(previous));
    expect(idsOf(mergeMessages(resolved, [], []))).toEqual(idsOf(previous));
  },
);
