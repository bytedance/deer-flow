import type { WorkspaceChangeSummary, WorkspaceFileChange } from "./types";

export type WorkspaceChangeLineClass =
  | "addition"
  | "context"
  | "deletion"
  | "hunk"
  | "meta";

export function getChangedFileCount(summary: WorkspaceChangeSummary) {
  return summary.created + summary.modified + summary.deleted;
}

export function getWorkspaceChangeBadgeLabel(summary: WorkspaceChangeSummary) {
  const count = getChangedFileCount(summary);
  return `${count} ${count === 1 ? "file" : "files"} changed +${summary.additions} -${summary.deletions}`;
}

export function getWorkspaceChangeLineClass(
  line: string,
): WorkspaceChangeLineClass {
  // Unified-diff file headers are "+++ " / "--- " with a trailing space. A bare
  // "+++"/"---" prefix would also match real content lines that begin with those
  // sequences (e.g. an added line "+++foo"), styling them as meta by mistake.
  if (line.startsWith("+++ ") || line.startsWith("--- ")) {
    return "meta";
  }
  if (line.startsWith("@@")) {
    return "hunk";
  }
  if (line.startsWith("+")) {
    return "addition";
  }
  if (line.startsWith("-")) {
    return "deletion";
  }
  return "context";
}

export function sortWorkspaceChanges(files: WorkspaceFileChange[]) {
  const statusRank = {
    created: 0,
    modified: 1,
    deleted: 2,
  } satisfies Record<WorkspaceFileChange["status"], number>;

  return [...files].sort((left, right) => {
    const rankDiff = statusRank[left.status] - statusRank[right.status];
    if (rankDiff !== 0) {
      return rankDiff;
    }
    return left.path.localeCompare(right.path);
  });
}
