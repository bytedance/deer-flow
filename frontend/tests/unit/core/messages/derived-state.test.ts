import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "@rstest/core";

import {
  deriveAssistantTurnUsageState,
  deriveStableMessageGroups,
} from "@/core/messages/derived-state";
import { getMessageGroups } from "@/core/messages/utils";

function message(type: Message["type"], id: string, content: string): Message {
  return { type, id, content } as Message;
}

describe("incremental message derivation", () => {
  it("reuses completed groups when only the streaming turn changes", () => {
    const messages = Array.from({ length: 1_000 }, (_, turn) => [
      message("human", `h-${turn}`, `question ${turn}`),
      message("ai", `a-${turn}`, `answer ${turn}`),
    ]).flat();
    const initial = deriveStableMessageGroups(messages, false, [], false);
    const nextMessages = [
      ...messages.slice(0, -1),
      message("ai", "a-999", "answer 999 streaming"),
    ];

    const next = deriveStableMessageGroups(nextMessages, true, initial, false);

    expect(next).toHaveLength(initial.length);
    expect(next[0]).toBe(initial[0]);
    expect(next.at(-3)).toBe(initial.at(-3));
    expect(next.at(-1)).not.toBe(initial.at(-1));
  });

  it("does not reuse a historical group when a same-id message changes", () => {
    const messages = [
      message("human", "h-1", "question"),
      message("ai", "a-1", "original answer"),
      message("human", "h-2", "next question"),
    ];
    const initial = deriveStableMessageGroups(messages, false, [], false);
    const refreshed = deriveStableMessageGroups(
      [messages[0]!, message("ai", "a-1", "corrected answer"), messages[2]!],
      false,
      initial,
      false,
    );

    expect(refreshed[1]).not.toBe(initial[1]);
    expect(refreshed[1]?.messages[0]?.content).toBe("corrected answer");
  });

  it("matches the reference grouping when older history is prepended during streaming", () => {
    const currentTurn = [
      message("human", "h-2", "current question"),
      message("ai", "a-2", "streaming answer"),
    ];
    const initial = deriveStableMessageGroups(currentTurn, true, [], false);
    const withHistory = [
      message("human", "h-1", "older question"),
      message("ai", "a-1", "older answer"),
      ...currentTurn,
    ];

    const derived = deriveStableMessageGroups(withHistory, true, initial, true);

    expect(derived).toEqual(
      getMessageGroups(withHistory, { isCurrentTurnLoading: true }),
    );
    expect(derived.map((group) => group.id)).toContain("h-1");
  });

  it("matches the reference grouping across append, tool, reconnect, and hidden-message updates", () => {
    const toolCalling = {
      ...message("ai", "a-tool", ""),
      tool_calls: [{ id: "call-1", name: "bash", args: {} }],
    } as Message;
    const toolResult = {
      ...message("tool", "tool-1", "done"),
      name: "bash",
      tool_call_id: "call-1",
    } as Message;
    const hidden = {
      ...message("ai", "summary-1", "hidden summary"),
      name: "summary",
    } as Message;
    const states: Array<{ messages: Message[]; loading: boolean }> = [
      { messages: [message("human", "h-1", "question")], loading: true },
      {
        messages: [message("human", "h-1", "question"), toolCalling],
        loading: true,
      },
      {
        messages: [
          message("human", "h-1", "question"),
          toolCalling,
          toolResult,
        ],
        loading: true,
      },
      {
        messages: [
          message("human", "h-1", "question"),
          { ...toolCalling },
          { ...toolResult },
          hidden,
          message("ai", "a-final", "answer"),
        ],
        loading: false,
      },
    ];

    let previousGroups: ReturnType<typeof getMessageGroups> = [];
    let previousIsLoading = false;
    for (const state of states) {
      const derived = deriveStableMessageGroups(
        state.messages,
        state.loading,
        previousGroups,
        previousIsLoading,
      );
      expect(derived).toEqual(
        getMessageGroups(state.messages, {
          isCurrentTurnLoading: state.loading,
        }),
      );
      previousGroups = derived;
      previousIsLoading = state.loading;
    }
  });

  it("reuses completed turn usage arrays on a tail-only update", () => {
    const messages = [
      message("human", "h-1", "one"),
      message("ai", "a-1", "answer one"),
      message("human", "h-2", "two"),
      message("ai", "a-2", "answer two"),
    ];
    const groups = deriveStableMessageGroups(messages, false, [], false);
    const initial = deriveAssistantTurnUsageState(groups);
    const nextMessages = [
      ...messages.slice(0, -1),
      message("ai", "a-2", "answer two streaming"),
    ];
    const nextGroups = deriveStableMessageGroups(
      nextMessages,
      true,
      groups,
      false,
    );
    const next = deriveAssistantTurnUsageState(nextGroups, initial);

    expect(next.byGroupIndex[1]).toBe(initial.byGroupIndex[1]);
    expect(next.byGroupIndex.at(-1)).not.toBe(initial.byGroupIndex.at(-1));
  });
});

it("keeps pre-clarification answers stable through hidden replies, reconnect, and settlement", () => {
  const history = [
    message("human", "h", "Plan a deployment"),
    message("ai", "plan", "Completed plan"),
    {
      ...message("ai", "ask", ""),
      tool_calls: [{ id: "call", name: "ask_clarification", args: {} }],
    },
    {
      ...message("tool", "request", "Which environment?"),
      name: "ask_clarification",
      tool_call_id: "call",
    },
  ] as Message[];
  const reply = {
    ...message("human", "reply", "staging"),
    additional_kwargs: { hide_from_ui: true },
  } as Message;
  const continued = [
    ...history,
    reply,
    message("ai", "next", "Starting deployment"),
  ];
  const waiting = deriveStableMessageGroups(history, false, [], false);
  const running = deriveStableMessageGroups(continued, true, waiting, false);
  const reconnect = deriveStableMessageGroups(continued, true, [], false);
  const settled = deriveStableMessageGroups(continued, false, running, true);
  for (const groups of [waiting, running, reconnect, settled]) {
    expect(groups.find((group) => group.id === "plan")?.type).toBe("assistant");
    expect(
      groups
        .flatMap((group) => group.messages)
        .filter((item) => item.id === "plan"),
    ).toHaveLength(1);
  }
  expect(
    running
      .find((group) => group.id === "ask")
      ?.messages.map((item) => item.id),
  ).toEqual(["ask", "request"]);
  expect(running.find((group) => group.id === "plan")).toBe(
    waiting.find((group) => group.id === "plan"),
  );
  const nextVisibleTurn = [
    ...continued,
    message("human", "followup", "Check status"),
    message("ai", "status", "Checking"),
  ];
  expect(
    deriveStableMessageGroups(nextVisibleTurn, true, running, true),
  ).toEqual(getMessageGroups(nextVisibleTurn, { isCurrentTurnLoading: true }));
  expect(running).toEqual(reconnect);
  expect(running.find((group) => group.id === "next")?.type).toBe(
    "assistant:processing",
  );
  expect(settled.find((group) => group.id === "next")?.type).toBe("assistant");
});
