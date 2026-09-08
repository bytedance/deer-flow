import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import { listAgents } from "@/core/agents/api";
import { fetch as apiFetch } from "@/core/api/fetcher";
import {
  listChannelConnections,
  listChannelProviders,
} from "@/core/channels/api";
import { fetchFeatures } from "@/core/features/api";
import { loadLarkIntegrationStatus } from "@/core/integrations/lark/api";
import { loadMCPConfig } from "@/core/mcp/api";
import { loadMemory } from "@/core/memory/api";
import {
  createScheduledTask,
  fetchScheduledTaskRuns,
  fetchScheduledTasks,
  fetchThreadScheduledTasks,
} from "@/core/scheduled-tasks/api";
import { loadSkills } from "@/core/skills/api";
import { listSubagents } from "@/core/subagents/api";
import { loadSuggestionsConfig } from "@/core/suggestions/api";
import { fetchSubtaskSteps } from "@/core/tasks/api";
import { fetchThreadTokenUsage } from "@/core/threads/api";

const { env } = rs.hoisted(() => ({
  env: {
    NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "true",
    NEXT_PUBLIC_BACKEND_BASE_URL: "",
  },
}));
rs.mock("@/env", () => ({ env }));

const network = rs.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
  Response.json({}),
);

beforeEach(() => {
  env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY = "true";
  env.NEXT_PUBLIC_BACKEND_BASE_URL = "";
  network.mockReset();
  network.mockResolvedValue(Response.json({}));
  rs.stubGlobal("fetch", network);
});

afterEach(() => {
  rs.unstubAllGlobals();
});

describe("static website API requests", () => {
  it("loads optional capabilities and empty catalogs without the Gateway", async () => {
    await expect(fetchFeatures()).resolves.toMatchObject({
      agents_api: { enabled: false },
      browser_control: { enabled: false },
      mcp_tasks: { enabled: false },
      subagent_batches: { repository_available: false, worker_running: false },
    });
    await expect(listChannelProviders()).resolves.toEqual({
      enabled: false,
      providers: [],
    });
    await expect(listChannelConnections()).resolves.toEqual([]);
    await expect(listAgents()).resolves.toEqual([]);
    await expect(listSubagents()).resolves.toEqual([]);
    await expect(loadSuggestionsConfig()).resolves.toMatchObject({
      enabled: false,
    });
    await expect(fetchScheduledTasks()).resolves.toEqual([]);
    await expect(fetchThreadScheduledTasks("demo / thread")).resolves.toEqual(
      [],
    );
    await expect(fetchScheduledTaskRuns("task / id")).resolves.toEqual([]);
    await expect(fetchSubtaskSteps("thread", "run", "task")).resolves.toEqual(
      [],
    );
    await expect(fetchThreadTokenUsage("demo")).resolves.toBeNull();
    const history = await apiFetch("/api/threads/demo/messages/page?limit=50");
    expect(await history.json()).toEqual({
      data: [],
      has_more: false,
      next_before_seq: null,
    });
    await expect(loadMemory()).resolves.toMatchObject({
      facts: [],
      user: {},
      history: {},
    });
    expect(network).not.toHaveBeenCalled();
  });

  it("uses the existing same-origin settings fixtures even with a configured Gateway", async () => {
    env.NEXT_PUBLIC_BACKEND_BASE_URL = "https://gateway.example/prefix";
    network.mockResolvedValueOnce(Response.json({ skills: [] }));
    await expect(loadSkills()).resolves.toEqual([]);
    network.mockResolvedValueOnce(Response.json({ mcp_servers: {} }));
    await expect(loadMCPConfig()).resolves.toEqual({ mcp_servers: {} });
    network.mockResolvedValueOnce(Response.json({ installed: false }));
    await expect(loadLarkIntegrationStatus()).resolves.toMatchObject({
      installed: false,
    });
    expect(network.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:2026/mock/api/skills",
      "http://localhost:2026/mock/api/mcp/config",
      "http://localhost:2026/mock/api/integrations/lark/status",
    ]);
    await expect(fetchFeatures()).resolves.toMatchObject({
      agents_api: { enabled: false },
    });
    expect(network).toHaveBeenCalledTimes(3);
  });

  it("rejects writes and unsupported endpoints locally instead of reporting fake success", async () => {
    await expect(
      createScheduledTask({
        context_mode: "fresh_thread_per_run",
        title: "Demo",
        prompt: "Demo",
        schedule_type: "once",
        schedule_spec: {},
        timezone: "UTC",
      }),
    ).rejects.toThrow("Unavailable in static demo mode");
    expect((await apiFetch("/api/new-feature")).status).toBe(404);
    expect(
      (
        await apiFetch(
          new Request("http://localhost:2026/api/subagents", {
            method: "DELETE",
          }),
        )
      ).status,
    ).toBe(405);
    expect(network).not.toHaveBeenCalled();
  });

  it("leaves demo assets and unrelated external requests intact", async () => {
    await apiFetch("/demo/threads/demo/thread.json");
    await apiFetch("https://external.example/api/features");
    expect(network).toHaveBeenCalledTimes(2);
  });

  it("uses the current browser origin for fixtures and respects cancellation", async () => {
    rs.stubGlobal("window", { location: { origin: "http://127.0.0.1:3000" } });
    await apiFetch("/api/skills");
    expect(network).toHaveBeenCalledWith(
      "http://127.0.0.1:3000/mock/api/skills",
      expect.anything(),
    );
    network.mockClear();
    const controller = new AbortController();
    controller.abort();
    await expect(
      apiFetch("/api/features", { signal: controller.signal }),
    ).rejects.toThrow();
    expect(
      await (await apiFetch("/api/features", { method: "HEAD" })).text(),
    ).toBe("");
    expect(network).not.toHaveBeenCalled();
  });

  it("preserves normal backend requests unless the flag is exactly true", async () => {
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY = "false";
    network.mockResolvedValue(Response.json({ agents_api: { enabled: true } }));
    await expect(fetchFeatures()).resolves.toMatchObject({
      agents_api: { enabled: true },
    });
    expect(network).toHaveBeenCalledWith(
      "/api/features",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
