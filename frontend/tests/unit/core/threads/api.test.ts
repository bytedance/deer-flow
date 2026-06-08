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

test("clearThreadContext POSTs to /clear-context and returns parsed response", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      success: true,
      message: "Context cleared",
      checkpoint_id: "ckpt-1",
    }),
  });

  const { clearThreadContext } = await import("@/core/threads/api");

  await expect(clearThreadContext("thread-1")).resolves.toEqual({
    success: true,
    message: "Context cleared",
    checkpoint_id: "ckpt-1",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/clear-context"),
    { method: "POST" },
  );
});

test("clearThreadContext throws with backend detail on error", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "Thread not found" }),
  });

  const { clearThreadContext } = await import("@/core/threads/api");

  await expect(clearThreadContext("thread-1")).rejects.toThrow(
    "Thread not found",
  );
});

test("clearThreadContext falls back to generic message when detail missing", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => {
      throw new Error("no body");
    },
  });

  const { clearThreadContext } = await import("@/core/threads/api");

  await expect(clearThreadContext("thread-1")).rejects.toThrow(
    "Failed to clear context.",
  );
});

test("compactThreadContext POSTs to /compact and returns parsed response with summary", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      success: true,
      message: "Context compacted",
      checkpoint_id: "ckpt-2",
      summary: "Conversation summary.",
    }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(compactThreadContext("thread-1")).resolves.toMatchObject({
    success: true,
    summary: "Conversation summary.",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/compact"),
    { method: "POST" },
  );
});

test("compactThreadContext throws with backend detail on error", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "No messages to compact" }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(compactThreadContext("thread-1")).rejects.toThrow(
    "No messages to compact",
  );
});
