/**
 * ISSUE-02 regression: unified status types and constants.
 */

import { describe, expect, it } from "vitest";

import {
  ARTIFACT_STATUS_VALUES,
  FAILED_LAYER_VALUES,
  RUN_FAILURE_CATEGORY_VALUES,
  RUN_STATUS_VALUES,
  THREAD_STATUS_VALUES,
  UPLOAD_STATUS_VALUES,
} from "@/core/models/status";

import type {
  ArtifactStatus,
  FailedLayer,
  RunFailureCategory,
  RunStatus,
  ThreadStatus,
  UploadStatus,
} from "@/core/models/status";

// =============================================================================
// Thread status
// =============================================================================

describe("ThreadStatus", () => {
  it("has exactly three states", () => {
    expect(THREAD_STATUS_VALUES).toEqual(["idle", "active", "archived"]);
  });

  it("type accepts only valid values", () => {
    const valid: ThreadStatus[] = ["idle", "active", "archived"];
    expect(valid).toHaveLength(3);
  });
});

// =============================================================================
// Run status
// =============================================================================

describe("RunStatus", () => {
  it("has all canonical states", () => {
    expect(RUN_STATUS_VALUES).toEqual([
      "pending",
      "running",
      "success",
      "failed",
      "cancelled",
    ]);
  });

  it("no longer uses 'error' as canonical (it was renamed to 'failed')", () => {
    // ISSUE-02: "error" → "failed"
    expect(RUN_STATUS_VALUES).not.toContain("error");
  });

  it("type accepts only valid canonical values", () => {
    const valid: RunStatus[] = [
      "pending",
      "running",
      "success",
      "failed",
      "cancelled",
    ];
    expect(valid).toHaveLength(5);
  });
});

// =============================================================================
// Failure category
// =============================================================================

describe("RunFailureCategory", () => {
  it("has exactly three categories", () => {
    expect(RUN_FAILURE_CATEGORY_VALUES).toEqual([
      "execution_failed",
      "upload_failed",
      "external_dependency_unavailable",
    ]);
  });

  it("type accepts only valid values", () => {
    const valid: RunFailureCategory[] = [
      "execution_failed",
      "upload_failed",
      "external_dependency_unavailable",
    ];
    expect(valid).toHaveLength(3);
  });
});

// =============================================================================
// Failed layer
// =============================================================================

describe("FailedLayer", () => {
  it("has exactly three layers", () => {
    expect(FAILED_LAYER_VALUES).toEqual(["runtime", "gateway", "external"]);
  });

  it("type accepts only valid values", () => {
    const valid: FailedLayer[] = ["runtime", "gateway", "external"];
    expect(valid).toHaveLength(3);
  });
});

// =============================================================================
// Upload status
// =============================================================================

describe("UploadStatus", () => {
  it("has all four states", () => {
    expect(UPLOAD_STATUS_VALUES).toEqual([
      "uploading",
      "converting",
      "ready",
      "failed",
    ]);
  });

  it("no longer uses 'uploaded' (it was renamed to 'ready')", () => {
    // ISSUE-02: "uploaded" → "ready"
    expect(UPLOAD_STATUS_VALUES).not.toContain("uploaded");
  });

  it("type accepts only valid values", () => {
    const valid: UploadStatus[] = ["uploading", "converting", "ready", "failed"];
    expect(valid).toHaveLength(4);
  });
});

// =============================================================================
// Artifact status
// =============================================================================

describe("ArtifactStatus", () => {
  it("has exactly three states", () => {
    expect(ARTIFACT_STATUS_VALUES).toEqual([
      "generating",
      "ready",
      "failed",
    ]);
  });

  it("type accepts only valid values", () => {
    const valid: ArtifactStatus[] = ["generating", "ready", "failed"];
    expect(valid).toHaveLength(3);
  });
});

// =============================================================================
// ISSUE-02: spelling regression
// =============================================================================

describe("ISSUE-02 spelling", () => {
  it("uses 'cancelled' (double-l), not 'canceled'", () => {
    expect(RUN_STATUS_VALUES).toContain("cancelled");
    expect(RUN_STATUS_VALUES).not.toContain("canceled");
  });

  it("report-templates RunStatus is the same type as status.ts RunStatus", () => {
    const status: import("@/core/report-templates/types").RunStatus = "cancelled";
    const rtStatus: RunStatus = status;
    expect(rtStatus).toBe("cancelled");
  });
});
