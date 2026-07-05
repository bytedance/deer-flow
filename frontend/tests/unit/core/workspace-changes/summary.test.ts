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
