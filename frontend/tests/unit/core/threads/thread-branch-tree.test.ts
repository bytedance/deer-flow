import { describe, expect, it } from "@rstest/core";

import {
  flattenThreadBranches,
  isBranchThread,
} from "@/core/threads/thread-branch-tree";
import type { AgentThread } from "@/core/threads/types";

function thread(
  id: string,
  updatedAt: string,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: id,
    updated_at: updatedAt,
    created_at: updatedAt,
    metadata,
    status: "idle",
    values: { title: id },
  } as AgentThread;
}

function branch(
  id: string,
  parentId: unknown,
  updatedAt: string,
  metadata: Record<string, unknown> = {},
) {
  return thread(id, updatedAt, {
    deerflow_branch: true,
    branch_parent_thread_id: parentId,
    ...metadata,
  });
}

function summarize(entries: ReturnType<typeof flattenThreadBranches>) {
  return entries.map((entry) => ({
    depth: entry.depth,
    id: entry.thread.thread_id,
    isLastSibling: entry.isLastSibling,
    parentId: entry.parentThread?.thread_id,
  }));
}

describe("isBranchThread", () => {
  it("recognizes a thread with valid branch provenance", () => {
    expect(
      isBranchThread(branch("child", "parent", "2026-01-01T00:00:00Z")),
    ).toBe(true);
  });

  it("rejects missing or malformed branch provenance", () => {
    expect(isBranchThread(thread("regular", "2026-01-01T00:00:00Z"))).toBe(
      false,
    );
    expect(
      isBranchThread(branch("malformed", 42, "2026-01-01T00:00:00Z")),
    ).toBe(false);
    expect(isBranchThread(null)).toBe(false);
  });
});

describe("flattenThreadBranches", () => {
  it("nests loaded siblings and lifts the group by its freshest descendant", () => {
    const parent = thread("parent", "2026-01-01T00:00:00Z");
    const child = branch("child", "parent", "2026-01-04T00:00:00Z");
    const sibling = branch("sibling", "parent", "2026-01-03T00:00:00Z");
    const other = thread("other", "2026-01-02T00:00:00Z");

    expect(
      summarize(flattenThreadBranches([child, sibling, other, parent])),
    ).toEqual([
      {
        depth: 0,
        id: "parent",
        isLastSibling: true,
        parentId: undefined,
      },
      {
        depth: 1,
        id: "child",
        isLastSibling: false,
        parentId: "parent",
      },
      {
        depth: 1,
        id: "sibling",
        isLastSibling: true,
        parentId: "parent",
      },
      {
        depth: 0,
        id: "other",
        isLastSibling: true,
        parentId: undefined,
      },
    ]);
  });

  it("keeps recursive lineage and immediate-parent identity", () => {
    const root = thread("root", "2026-01-04T00:00:00Z");
    const child = branch("child", "root", "2026-01-03T00:00:00Z");
    const grandchild = branch("grandchild", "child", "2026-01-02T00:00:00Z");

    expect(summarize(flattenThreadBranches([root, child, grandchild]))).toEqual(
      [
        {
          depth: 0,
          id: "root",
          isLastSibling: true,
          parentId: undefined,
        },
        {
          depth: 1,
          id: "child",
          isLastSibling: true,
          parentId: "root",
        },
        {
          depth: 2,
          id: "grandchild",
          isLastSibling: true,
          parentId: "child",
        },
      ],
    );
  });

  it("does not move a pinned branch under an unpinned parent", () => {
    const pinnedChild = branch(
      "pinned-child",
      "parent",
      "2026-01-02T00:00:00Z",
      { deerflow_pinned: true },
    );
    const parent = thread("parent", "2026-01-01T00:00:00Z");

    expect(summarize(flattenThreadBranches([pinnedChild, parent]))).toEqual([
      {
        depth: 0,
        id: "pinned-child",
        isLastSibling: true,
        parentId: undefined,
      },
      {
        depth: 0,
        id: "parent",
        isLastSibling: true,
        parentId: undefined,
      },
    ]);
  });

  it("preserves pinned root order while nesting same-state children", () => {
    const first = thread("first", "2026-01-01T00:00:00Z", {
      deerflow_pinned: true,
    });
    const second = thread("second", "2026-01-04T00:00:00Z", {
      deerflow_pinned: true,
    });
    const child = branch("child", "first", "2026-01-05T00:00:00Z", {
      deerflow_pinned: true,
    });

    expect(summarize(flattenThreadBranches([first, second, child]))).toEqual([
      {
        depth: 0,
        id: "first",
        isLastSibling: true,
        parentId: undefined,
      },
      {
        depth: 1,
        id: "child",
        isLastSibling: true,
        parentId: "first",
      },
      {
        depth: 0,
        id: "second",
        isLastSibling: true,
        parentId: undefined,
      },
    ]);
  });

  it("keeps missing, malformed, forged, self-parented, and cyclic branches visible at top level", () => {
    const missing = branch("missing", "not-loaded", "2026-01-06T00:00:00Z");
    const malformed = branch("malformed", 42, "2026-01-05T00:00:00Z");
    const forged = thread("forged", "2026-01-04T00:00:00Z", {
      branch_parent_thread_id: "missing",
    });
    const self = branch("self", "self", "2026-01-03T00:00:00Z");
    const cycleA = branch("cycle-a", "cycle-b", "2026-01-02T00:00:00Z");
    const cycleB = branch("cycle-b", "cycle-a", "2026-01-01T00:00:00Z");

    const entries = flattenThreadBranches([
      missing,
      malformed,
      forged,
      self,
      cycleA,
      cycleB,
    ]);

    expect(entries.map((entry) => entry.thread.thread_id)).toEqual([
      "missing",
      "malformed",
      "forged",
      "self",
      "cycle-a",
      "cycle-b",
    ]);
    expect(entries.every((entry) => entry.depth === 0)).toBe(true);
  });
});
