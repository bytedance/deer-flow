import { beforeEach, expect, test, rs } from "@rstest/core";

const fetchWithAuth = rs.fn();

rs.mock("@/core/api/fetcher", () => ({
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

test("branchThreadFromTurn posts the selected turn ids to the gateway", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "branch-thread",
      parent_thread_id: "thread/1",
      parent_checkpoint_id: "checkpoint-2",
      branched_from_message_id: "ai-2",
      workspace_clone_mode: "current_thread_best_effort",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await expect(
    branchThreadFromTurn("thread/1", {
      messageId: "ai-2",
      messageIds: ["ai-1", "ai-2"],
      title: "Branch: original",
    }),
  ).resolves.toMatchObject({
    thread_id: "branch-thread",
    parent_checkpoint_id: "checkpoint-2",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread%2F1/branches"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message_id: "ai-2",
        message_ids: ["ai-1", "ai-2"],
        title: "Branch: original",
      }),
    },
  );
});

test("branchThreadFromTurn surfaces gateway detail on failure", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({
      detail: "This turn can no longer be branched from.",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await expect(
    branchThreadFromTurn("thread-1", {
      messageId: "ai-2",
      messageIds: ["ai-2"],
    }),
  ).rejects.toThrow("This turn can no longer be branched from.");
});

test("compactThreadContext posts agent attribution and abort signal", async () => {
  const controller = new AbortController();
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "thread-1",
      compacted: true,
      removed_message_count: 4,
      preserved_message_count: 2,
      summary_updated: true,
      checkpoint_id: "checkpoint-3",
      total_tokens: 123,
    }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(
    compactThreadContext("thread-1", {
      agentName: "research-agent",
      signal: controller.signal,
    }),
  ).resolves.toMatchObject({
    compacted: true,
    checkpoint_id: "checkpoint-3",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/compact"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        force: true,
        agent_name: "research-agent",
      }),
      signal: controller.signal,
    },
  );
});
