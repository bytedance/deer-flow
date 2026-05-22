/* @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

import {
  collectReportAgentNames,
  filterReportThreads,
} from "@/core/report-templates/useReportThreads";
import type { AgentThread } from "@/core/threads/types";

function makeThread(
  threadId: string,
  agentName?: string,
  updatedAt = "2026-05-20T00:00:00Z",
) {
  return {
    thread_id: threadId,
    status: "idle" as const,
    created_at: "2026-05-01T00:00:00Z",
    updated_at: updatedAt,
    values: { messages: [], title: `Thread ${threadId}` },
    metadata: agentName ? { agent_name: agentName } : {},
  } as unknown as AgentThread;
}

describe("collectReportAgentNames", () => {
  it("collects names of agents with report tag", () => {
    const names = collectReportAgentNames([
      { name: "ai-report--custom", tags: ["report", "custom"] },
      { name: "general-chat", tags: ["chat"] },
      { name: "ai-report--monthly", tags: ["report"] },
    ]);
    expect(names).toEqual(new Set(["ai-report--custom", "ai-report--monthly"]));
  });

  it("returns empty set when no agents have report tag", () => {
    const names = collectReportAgentNames([
      { name: "general-chat", tags: ["chat"] },
      { name: "defect-closure", tags: null },
    ]);
    expect(names.size).toBe(0);
  });

  it("returns empty set when agents list is empty", () => {
    expect(collectReportAgentNames([]).size).toBe(0);
  });

  it("skips agents with null tags", () => {
    const names = collectReportAgentNames([
      { name: "agent-a", tags: null },
      { name: "agent-b", tags: ["report"] },
    ]);
    expect(names).toEqual(new Set(["agent-b"]));
  });
});

describe("filterReportThreads", () => {
  const reportNames = new Set(["ai-report--custom", "ai-report--monthly"]);

  it("keeps threads from report agents", () => {
    const threads = [
      makeThread("t1", "ai-report--custom", "2026-05-22T00:00:00Z"),
      makeThread("t2", "general-chat", "2026-05-21T00:00:00Z"),
    ];
    const result = filterReportThreads(threads, reportNames);
    expect(result).toHaveLength(1);
    expect(result[0]!.thread_id).toBe("t1");
  });

  it("returns empty array when no threads match", () => {
    const threads = [makeThread("t1", "general-chat")];
    expect(filterReportThreads(threads, reportNames)).toEqual([]);
  });

  it("sorts by updated_at descending", () => {
    const threads = [
      makeThread("t1", "ai-report--custom", "2026-05-20T00:00:00Z"),
      makeThread("t2", "ai-report--custom", "2026-05-22T00:00:00Z"),
      makeThread("t3", "ai-report--custom", "2026-05-21T00:00:00Z"),
    ];
    const result = filterReportThreads(threads, reportNames);
    expect(result.map((t) => t.thread_id)).toEqual(["t2", "t3", "t1"]);
  });

  it("respects the limit parameter", () => {
    const threads = [
      makeThread("t1", "ai-report--custom", "2026-05-20T00:00:00Z"),
      makeThread("t2", "ai-report--custom", "2026-05-22T00:00:00Z"),
      makeThread("t3", "ai-report--custom", "2026-05-21T00:00:00Z"),
    ];
    const result = filterReportThreads(threads, reportNames, 2);
    expect(result).toHaveLength(2);
    expect(result.map((t) => t.thread_id)).toEqual(["t2", "t3"]);
  });

  it("skips threads without agent_name metadata", () => {
    const threads = [
      makeThread("t1", undefined),
      makeThread("t2", "ai-report--custom"),
    ];
    const result = filterReportThreads(threads, reportNames);
    expect(result).toHaveLength(1);
    expect(result[0]!.thread_id).toBe("t2");
  });
});
