import { beforeEach, expect, test, vi } from "vitest";

const fetchWithAuth = vi.fn();

vi.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://localhost:8001",
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

test("clearThreadContext calls POST clear-context endpoint", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      success: true,
      message: "Context cleared",
      checkpoint_id: "ckpt-1",
    }),
  });

  const { clearThreadContext } = await import("@/core/threads/api");

  const result = await clearThreadContext("thread-1");

  expect(result).toEqual({
    success: true,
    message: "Context cleared",
    checkpoint_id: "ckpt-1",
  });
  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/clear-context"),
    { method: "POST" },
  );
});

test("clearThreadContext throws on failure", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "Not found" }),
  });

  const { clearThreadContext } = await import("@/core/threads/api");

  await expect(clearThreadContext("bad-thread")).rejects.toThrow("Not found");
});

test("compactThreadContext calls POST compact endpoint and returns summary", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      success: true,
      message: "Context compacted",
      summary: "User discussed testing",
      checkpoint_id: "ckpt-2",
    }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  const result = await compactThreadContext("thread-1");

  expect(result).toEqual({
    success: true,
    message: "Context compacted",
    summary: "User discussed testing",
    checkpoint_id: "ckpt-2",
  });
  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/compact"),
    { method: "POST" },
  );
});

test("compactThreadContext throws on failure", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "No messages to compact" }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(compactThreadContext("empty-thread")).rejects.toThrow(
    "No messages to compact",
  );
});
