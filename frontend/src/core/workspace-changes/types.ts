export type WorkspaceChangeStatus =
  | "created"
  | "modified"
  | "deleted"
  | "symlink_created";

export type DiffUnavailableReason =
  | "binary"
  | "large"
  | "sensitive"
  | "truncated"
  | "symlink";

export interface WorkspaceChangeSummary {
  created: number;
  modified: number;
  deleted: number;
  symlink_created: number;
  additions: number;
  deletions: number;
  truncated: boolean;
}

export interface WorkspaceFileChange {
  path: string;
  root: string;
  status: WorkspaceChangeStatus;
  binary: boolean;
  sensitive: boolean;
  size_before: number | null;
  size_after: number | null;
  sha256_before: string | null;
  sha256_after: string | null;
  diff: string;
  diff_truncated: boolean;
  diff_unavailable_reason: DiffUnavailableReason | null;
  additions: number;
  deletions: number;
  symlink: boolean;
  symlink_target_before: string | null;
  symlink_target_after: string | null;
}

export interface WorkspaceChangesResponse {
  available: boolean;
  version: number;
  summary: WorkspaceChangeSummary;
  files: WorkspaceFileChange[];
  limits: Record<string, unknown>;
}
