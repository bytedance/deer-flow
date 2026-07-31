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

function pinnedThread(id: string, updatedAt: string): AgentThread {
  return {
    ...thread(id, updatedAt),
    metadata: { deerflow_pinned: true },
  };
}

describe("thread list model", () => {
  it("deduplicates once while only bounding recent sidebar rows", () => {
    const pages = Array.from({ length: 5 }, (_, page) =>
      Array.from({ length: 50 }, (_, index) => {
        const id = String(page * 50 + index);
        return thread(id, new Date(2026, 0, 1, 0, 0, Number(id)).toISOString());
      }),
    );
    pages[1]![0] = pages[0]![0]!;

    const model = buildThreadListModel(pages);

    expect(model.threads).toHaveLength(249);
    expect(model.byId.size).toBe(249);
    expect(model.displayedThreads).toHaveLength(200);
    expect(model.canLoadMore).toBe(false);
  });

  it("keeps every loaded pinned thread in addition to the recent window", () => {
    const recent = Array.from({ length: 201 }, (_, index) =>
      thread(
        `recent-${index}`,
        new Date(2026, 0, 1, 0, 0, index).toISOString(),
      ),
    );
    const pinned = pinnedThread("pinned-after-window", "2025-01-01T00:00:00Z");

    const model = buildThreadListModel([recent, [pinned]]);

    expect(model.threads).toHaveLength(202);
    expect(model.displayedThreads).toHaveLength(201);
    expect(model.displayedThreads[0]).toBe(pinned);
    expect(model.displayedThreads).not.toContain(recent.at(-1));
  });

  it("continues loading until the sidebar has 200 non-pinned rows", () => {
    const pinned = Array.from({ length: 200 }, (_, index) =>
      pinnedThread(`pinned-${index}`, "2026-01-01T00:00:00Z"),
    );

    const model = buildThreadListModel([pinned]);

    expect(model.displayedThreads).toHaveLength(200);
    expect(model.canLoadMore).toBe(true);
  });

  it("returns the same normalized model for unchanged page identity", () => {
    const pages = [[thread("a", "2026-01-01T00:00:00.000Z")]];
    expect(buildThreadListModel(pages)).toBe(buildThreadListModel(pages));
  });
});
