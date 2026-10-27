import { describe, expect, test } from "@rstest/core";

import {
  getChangedFileCount,
  getWorkspaceChangeBadgeLabel,
  getWorkspaceChangeLineClass,
  sortWorkspaceChanges,
} from "@/core/workspace-changes/summary";
import type {
  WorkspaceChangesResponse,
  WorkspaceFileChange,
} from "@/core/workspace-changes/types";

function makeFileChange(
  overrides: Partial<WorkspaceFileChange> &
    Pick<WorkspaceFileChange, "path" | "status">,
): WorkspaceFileChange {
  return {
    root: "workspace",
    binary: false,
    sensitive: false,
    size_before: null,
    size_after: null,
    sha256_before: null,
    sha256_after: null,
    diff: "",
    diff_truncated: false,
    diff_unavailable_reason: null,
    additions: 0,
    deletions: 0,
    symlink: false,
    symlink_target_before: null,
    symlink_target_after: null,
    ...overrides,
  };
}

const changes: WorkspaceChangesResponse = {
  available: true,
  version: 1,
  summary: {
    created: 1,
    modified: 2,
    deleted: 0,
    symlink_created: 0,
    additions: 12,
    deletions: 3,
    truncated: false,
  },
  files: [],
  limits: {},
};

describe("workspace change summary helpers", () => {
  test("counts created, modified, and deleted files", () => {
    expect(getChangedFileCount(changes.summary)).toBe(3);
  });

  test("counts a symlink replacing a file (the only change in a symlink-only run)", () => {
    // Regression: getChangedFileCount previously summed only
    // created + modified + deleted, so a run whose sole change was a
    // symlink replacing a file (reported as `symlink_created`, not
    // `deleted`) produced a count of 0 and the workspace-changes badge
    // was hidden entirely -- the opposite of surfacing the change.
    expect(
      getChangedFileCount({
        created: 0,
        modified: 0,
        deleted: 0,
        symlink_created: 1,
        additions: 0,
        deletions: 0,
        truncated: false,
      }),
    ).toBe(1);
  });

  test("formats the compact badge label", () => {
    expect(getWorkspaceChangeBadgeLabel(changes.summary)).toBe(
      "3 files changed +12 -3",
    );
  });

  test("classifies unified diff lines", () => {
    expect(getWorkspaceChangeLineClass("+new line")).toBe("addition");
    expect(getWorkspaceChangeLineClass("-old line")).toBe("deletion");
    expect(getWorkspaceChangeLineClass("@@ -1 +1 @@")).toBe("hunk");
    expect(getWorkspaceChangeLineClass(" unchanged")).toBe("context");
    expect(getWorkspaceChangeLineClass("+++ b/file.md")).toBe("meta");
    expect(getWorkspaceChangeLineClass("--- a/file.md")).toBe("meta");
  });

  test("treats content lines beginning with +++/--- as add/remove, not meta", () => {
    expect(getWorkspaceChangeLineClass("+++foo")).toBe("addition");
    expect(getWorkspaceChangeLineClass("---bar")).toBe("deletion");
  });

  test("ranks a symlink-created entry with modified files, not before created or after deleted", () => {
    // Regression: statusRank previously had no "symlink_created" entry, so
    // `statusRank[left.status] - statusRank[right.status]` was NaN for any
    // comparison involving a symlink-created file -- violating Array#sort's
    // consistency contract instead of producing a deterministic order.
    const files = [
      makeFileChange({ path: "z-deleted.txt", status: "deleted" }),
      makeFileChange({ path: "m-symlink.txt", status: "symlink_created" }),
      makeFileChange({ path: "a-created.txt", status: "created" }),
    ];

    const sorted = sortWorkspaceChanges(files);

    expect(sorted.map((file) => file.path)).toEqual([
      "a-created.txt",
      "m-symlink.txt",
      "z-deleted.txt",
    ]);
  });

  test("breaks ties between modified and symlink-created entries by path", () => {
    const files = [
      makeFileChange({ path: "z.txt", status: "modified" }),
      makeFileChange({ path: "a.txt", status: "symlink_created" }),
    ];

    const sorted = sortWorkspaceChanges(files);

    expect(sorted.map((file) => file.path)).toEqual(["a.txt", "z.txt"]);
  });
});
