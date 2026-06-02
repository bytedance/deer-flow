import type { Message } from "@langchain/langgraph-sdk";
import { beforeEach, expect, test, vi } from "vitest";

const { fetchWithAuth } = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
}));

vi.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

import { fetchRunHistoryMessages } from "@/core/threads/api";

function makeRunMessage(
  seq: number,
  overrides: Partial<{
    id: string;
    type: Message["type"];
    content: string;
    name: string;
    tool_call_id: string;
    caller: string;
  }> = {},
) {
  const type = overrides.type ?? "ai";
  const content = overrides.content ?? `message-${seq}`;

  const message: Message =
    type === "tool"
      ? ({
          id: overrides.id ?? `tool-${seq}`,
          type: "tool",
          content,
          name: overrides.name ?? "ask_clarification",
          tool_call_id: overrides.tool_call_id ?? `call-${seq}`,
        } as Message)
      : ({
          id: overrides.id ?? `message-${seq}`,
          type,
          content,
        } as Message);

  return {
    run_id: "run-1",
    seq,
    content: message,
    metadata: {
      caller: overrides.caller ?? "lead_agent",
    },
    created_at: `2026-06-02T00:00:${String(seq).padStart(2, "0")}Z`,
  };
}

beforeEach(() => {
  fetchWithAuth.mockReset();
});

test("fetchRunHistoryMessages keeps paginating a run until has_more is false", async () => {
  const clarification = makeRunMessage(10, {
    type: "tool",
    content: "Which option do you want?",
    name: "ask_clarification",
    tool_call_id: "clarify-1",
  });
  const latestAi = makeRunMessage(60, {
    type: "ai",
    content: "Latest answer",
  });

  fetchWithAuth
    .mockResolvedValueOnce({
      json: async () => ({
        data: [makeRunMessage(11), latestAi],
        has_more: true,
      }),
    })
    .mockResolvedValueOnce({
      json: async () => ({
        data: [clarification],
        has_more: false,
      }),
    });

  await expect(fetchRunHistoryMessages("thread-1", "run-1")).resolves.toEqual([
    clarification,
    makeRunMessage(11),
    latestAi,
  ]);

  expect(fetchWithAuth).toHaveBeenNthCalledWith(
    1,
    expect.stringContaining("/api/threads/thread-1/runs/run-1/messages"),
    expect.objectContaining({ method: "GET" }),
  );
  expect(fetchWithAuth).toHaveBeenNthCalledWith(
    2,
    expect.stringContaining("before_seq=11"),
    expect.objectContaining({ method: "GET" }),
  );
});

test("fetchRunHistoryMessages also accepts camelCase hasMore from mocks", async () => {
  const older = makeRunMessage(5, { type: "tool", tool_call_id: "clarify-2" });
  const newer = makeRunMessage(15);

  fetchWithAuth
    .mockResolvedValueOnce({
      json: async () => ({
        data: [newer],
        hasMore: true,
      }),
    })
    .mockResolvedValueOnce({
      json: async () => ({
        data: [older],
        hasMore: false,
      }),
    });

  await expect(fetchRunHistoryMessages("thread-1", "run-1")).resolves.toEqual([
    older,
    newer,
  ]);
});
