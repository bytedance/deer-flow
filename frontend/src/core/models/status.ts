/**
 * Canonical lifecycle status types — single source of truth for all DeerFlow objects.
 *
 * ISSUE-02: Unify execution lifecycle and state semantics.
 * Aligned with ISSUE-01 primary flow and object model baseline.
 */

// =============================================================================
// Thread — conversation thread
// =============================================================================

/** Aggregated from subordinate Run statuses, not set manually. */
export type ThreadStatus = "idle" | "active" | "archived";

// =============================================================================
// Run — agent execution run
// =============================================================================

/** Unified execution lifecycle for agent runs. */
export type RunStatus =
  | "pending"
  | "running"
  | "success"
  | "failed" // was "error" — see RunFailureCategory for sub-classification
  | "cancelled";

/** Sub-classification when RunStatus is "failed". */
export type RunFailureCategory =
  | "execution_failed"
  | "upload_failed"
  | "external_dependency_unavailable";

/** Which architectural layer caused the failure. */
export type FailedLayer = "runtime" | "gateway" | "external";

// =============================================================================
// Upload — file upload
// =============================================================================

/** Lifecycle of a user-uploaded file. */
export type UploadStatus =
  | "uploading"
  | "converting"
  | "ready"
  | "failed";

// =============================================================================
// Artifact — agent-generated output file
// =============================================================================

/** Lifecycle of an agent-produced artifact. */
export type ArtifactStatus = "generating" | "ready" | "failed";

// =============================================================================
// Constants — runtime-accessible value sets
// =============================================================================

export const THREAD_STATUS_VALUES: ThreadStatus[] = [
  "idle",
  "active",
  "archived",
];

export const RUN_STATUS_VALUES: RunStatus[] = [
  "pending",
  "running",
  "success",
  "failed",
  "cancelled",
];

export const RUN_FAILURE_CATEGORY_VALUES: RunFailureCategory[] = [
  "execution_failed",
  "upload_failed",
  "external_dependency_unavailable",
];

export const FAILED_LAYER_VALUES: FailedLayer[] = [
  "runtime",
  "gateway",
  "external",
];

export const UPLOAD_STATUS_VALUES: UploadStatus[] = [
  "uploading",
  "converting",
  "ready",
  "failed",
];

export const ARTIFACT_STATUS_VALUES: ArtifactStatus[] = [
  "generating",
  "ready",
  "failed",
];
