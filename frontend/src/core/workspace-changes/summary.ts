import type { WorkspaceChangeSummary, WorkspaceFileChange } from "./types";

export type WorkspaceChangeLineClass =
  | "addition"
  | "context"
  | "deletion"
  | "hunk"
  | "meta";

export function getChangedFileCount(summary: WorkspaceChangeSummary) {
  return (
    summary.created +
    summary.modified +
    summary.deleted +
    summary.symlink_created
  );
}

export function getWorkspaceChangeBadgeLabel(summary: WorkspaceChangeSummary) {
  const count = getChangedFileCount(summary);
  return `${count} ${count === 1 ? "file" : "files"} changed +${summary.additions} -${summary.deletions}`;
}

/**
 * Classify one unified-diff line. `inHunk` must be true once the diff's first
 * "@@" line has been seen; to render a whole diff, use
 * `classifyWorkspaceDiffLines`, which tracks that for you.
 */
export function getWorkspaceChangeLineClass(
  line: string,
  inHunk: boolean,
): WorkspaceChangeLineClass {
  if (line.startsWith("@@")) {
    return "hunk";
  }
  // Unified-diff file headers are "+++ " / "--- " with a trailing space, and
  // they only appear before the first hunk. Inside a hunk the same prefix is
  // content: deleting the SQL comment "-- get users" yields "--- get users".
  if (!inHunk && (line.startsWith("+++ ") || line.startsWith("--- "))) {
    return "meta";
  }
  if (line.startsWith("+")) {
    return "addition";
  }
  if (line.startsWith("-")) {
    return "deletion";
  }
  return "context";
}

/** Classify every line of one unified diff, tracking whether a hunk has started. */
export function classifyWorkspaceDiffLines(
  lines: readonly string[],
): { line: string; lineClass: WorkspaceChangeLineClass }[] {
  let inHunk = false;
  return lines.map((line) => {
    const lineClass = getWorkspaceChangeLineClass(line, inHunk);
    if (lineClass === "hunk") {
      inHunk = true;
    }
    return { line, lineClass };
  });
}

export function sortWorkspaceChanges(files: WorkspaceFileChange[]) {
  // `symlink_created` shares modified's rank: it is a distinct change kind
  // (a symlink replacing a file) that otherwise renders like a modification
  // (see StatusIcon / statusLabel). This `satisfies Record<...>` guard forces
  // every WorkspaceChangeStatus variant to have a rank, so adding a new status
  // without updating this table is a compile error instead of a silent NaN
  // from an unranked lookup (which broke Array#sort's ordering contract).
  const statusRank = {
    created: 0,
    modified: 1,
    symlink_created: 1,
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
