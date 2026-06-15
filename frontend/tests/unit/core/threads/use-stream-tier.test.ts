import { describe, expect, it } from "vitest";

import { isReportPage } from "@/core/threads/use-stream-tier";
import { type StreamModeTier, STREAM_MODE_TIERS } from "@/core/api/stream-mode";

function tierFor(pathname: string): StreamModeTier {
  return isReportPage(pathname) ? "full" : "standard";
}

describe("isReportPage", () => {
  it("returns true for report template pages", () => {
    expect(isReportPage("/workspace/report-templates/abc123")).toBe(true);
  });

  it("returns true for report run pages", () => {
    expect(isReportPage("/workspace/report-runs/run-123")).toBe(true);
  });

  it("returns false for regular chat pages", () => {
    expect(isReportPage("/workspace/chats/thread-1")).toBe(false);
  });

  it("returns false for landing page", () => {
    expect(isReportPage("/")).toBe(false);
  });

  it("does not match partial prefix overlaps", () => {
    expect(isReportPage("/workspace/report-templatesXYZ")).toBe(true);
    expect(isReportPage("/workspace/report")).toBe(false);
  });
});

describe("stream tier selection", () => {
  it("returns 'full' tier for report template pages", () => {
    expect(tierFor("/workspace/report-templates/abc123")).toBe("full");
  });

  it("returns 'full' tier for report run pages", () => {
    expect(tierFor("/workspace/report-runs/run-123")).toBe("full");
  });

  it("returns 'standard' tier for regular chat pages", () => {
    expect(tierFor("/workspace/chats/thread-1")).toBe("standard");
  });

  it("returns 'standard' tier for landing page", () => {
    expect(tierFor("/")).toBe("standard");
  });

  it("full tier includes values mode", () => {
    expect(STREAM_MODE_TIERS.full).toContain("values");
  });

  it("standard tier excludes values mode", () => {
    expect(STREAM_MODE_TIERS.standard).not.toContain("values");
  });
});
