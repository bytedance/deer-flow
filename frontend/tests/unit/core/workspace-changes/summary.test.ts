import { describe, expect, test } from "@rstest/core";

import {
  getChangedFileCount,
  getWorkspaceChangeBadgeLabel,
  getWorkspaceChangeLineClass,
} from "@/core/workspace-changes/summary";
import type { WorkspaceChangesResponse } from "@/core/workspace-changes/types";

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
});
