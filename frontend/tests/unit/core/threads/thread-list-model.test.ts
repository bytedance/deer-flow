import { describe, expect, it } from "@rstest/core";

import { buildThreadListModel } from "@/core/threads/thread-list-model";
import type { AgentThread } from "@/core/threads/types";

function thread(id: string, updatedAt: string): AgentThread {
  return {
    thread_id: id,
    updated_at: updatedAt,
    created_at: updatedAt,
    metadata: {},
    status: "idle",
    values: {},
  } as AgentThread;
}

describe("thread list model", () => {
  it("deduplicates once and caps retained display rows at 200", () => {
    const pages = Array.from({ length: 5 }, (_, page) =>
      Array.from({ length: 50 }, (_, index) => {
        const id = String(page * 50 + index);
        return thread(id, new Date(2026, 0, 1, 0, 0, Number(id)).toISOString());
      }),
    );
    pages[1]![0] = pages[0]![0]!;

    const model = buildThreadListModel(pages);

    expect(model.threads).toHaveLength(200);
    expect(model.byId.size).toBe(200);
    expect(model.canLoadMore).toBe(false);
  });

  it("returns the same normalized model for unchanged page identity", () => {
    const pages = [[thread("a", "2026-01-01T00:00:00.000Z")]];
    expect(buildThreadListModel(pages)).toBe(buildThreadListModel(pages));
  });
});
