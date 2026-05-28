import { beforeEach, expect, test, vi } from "vitest";

const fetchWithAuth = vi.fn();

vi.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

beforeEach(() => {
  fetchWithAuth.mockReset();
});

test("fetchThreadTokenUsage uses shared auth fetch without JSON GET headers", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "thread-1",
      total_input_tokens: 3,
      total_output_tokens: 4,
      total_tokens: 7,
      total_runs: 1,
      by_model: { unknown: { tokens: 7, runs: 1 } },
      by_caller: {
        lead_agent: 0,
        subagent: 0,
        middleware: 0,
      },
    }),
  });

  const { fetchThreadTokenUsage } = await import("@/core/threads/api");

  await expect(fetchThreadTokenUsage("thread-1")).resolves.toMatchObject({
    thread_id: "thread-1",
    total_tokens: 7,
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/token-usage"),
    {
      method: "GET",
    },
  );
});

test("fetchThreadTokenUsage returns null for unavailable token usage", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    status: 404,
  });

  const { fetchThreadTokenUsage } = await import("@/core/threads/api");

  await expect(fetchThreadTokenUsage("thread-1")).resolves.toBeNull();
});

test("createThreadShare posts selected message ids", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      share_id: "share-1",
      title: "Shared answer",
      created_at: "2026-05-28T00:00:00+00:00",
    }),
  });

  const { createThreadShare } = await import("@/core/threads/api");

  await expect(
    createThreadShare({
      threadId: "thread-1",
      messageIds: ["human-1", "ai-1"],
      title: "Shared answer",
    }),
  ).resolves.toMatchObject({ share_id: "share-1" });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/shares/threads/thread-1"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_ids: ["human-1", "ai-1"],
        title: "Shared answer",
      }),
    },
  );
});

test("createThreadShare rejects with backend error detail", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    status: 400,
    json: async () => ({ detail: "Message IDs not found: missing-message" }),
  });

  const { createThreadShare } = await import("@/core/threads/api");

  await expect(
    createThreadShare({
      threadId: "thread-1",
      messageIds: ["missing-message"],
    }),
  ).rejects.toThrow("Message IDs not found: missing-message");
});
