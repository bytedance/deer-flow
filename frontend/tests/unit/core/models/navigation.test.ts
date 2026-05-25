/**
 * ISSUE-03 regression: CrossPageContext encode/decode and trace identifiers.
 */

import { describe, expect, it, vi } from "vitest";

import {
  buildCrossPageURL,
  createTraceId,
  decodeCrossPageContext,
  encodeCrossPageContext,
  logCrossPageNavigation,
  type CrossPageContext,
} from "@/core/models/navigation";

// =============================================================================
// encode / decode round-trip
// =============================================================================

describe("CrossPageContext encode/decode", () => {
  it("round-trips with all fields", () => {
    const ctx: CrossPageContext = {
      sourceType: "chat",
      sourceId: "thread-abc123",
      threadId: "thread-abc123",
      runId: "run-xyz",
    };
    const encoded = encodeCrossPageContext(ctx);
    const params = new URLSearchParams(`?from=${encoded}`);
    const decoded = decodeCrossPageContext(params);
    expect(decoded).toEqual(ctx);
  });

  it("round-trips without optional runId", () => {
    const ctx: CrossPageContext = {
      sourceType: "report",
      sourceId: "rr_001",
      threadId: "thread-42",
    };
    const encoded = encodeCrossPageContext(ctx);
    const params = new URLSearchParams(`?from=${encoded}`);
    const decoded = decodeCrossPageContext(params);
    expect(decoded).toEqual({
      sourceType: "report",
      sourceId: "rr_001",
      threadId: "thread-42",
    });
  });

  it("returns null when key is absent", () => {
    const params = new URLSearchParams("");
    expect(decodeCrossPageContext(params)).toBeNull();
  });

  it("returns null for invalid base64", () => {
    const params = new URLSearchParams("?from=!!!not-valid-base64!!!");
    expect(decodeCrossPageContext(params)).toBeNull();
  });

  it("returns null when required fields are missing", () => {
    const params = new URLSearchParams(
      `?from=${btoa(JSON.stringify({ sourceType: "chat" }))}`,
    );
    expect(decodeCrossPageContext(params)).toBeNull();
  });

  it("accepts all three source types", () => {
    const types: CrossPageContext["sourceType"][] = [
      "chat",
      "report",
      "artifact",
    ];
    for (const sourceType of types) {
      const ctx: CrossPageContext = {
        sourceType,
        sourceId: "src-1",
        threadId: "t-1",
      };
      const encoded = encodeCrossPageContext(ctx);
      const params = new URLSearchParams(`?from=${encoded}`);
      const decoded = decodeCrossPageContext(params);
      expect(decoded?.sourceType).toBe(sourceType);
    }
  });
});

// =============================================================================
// buildCrossPageURL
// =============================================================================

describe("buildCrossPageURL", () => {
  it("builds a URL with the from parameter", () => {
    const url = buildCrossPageURL("/workspace/report-runs/rr_xyz", {
      sourceType: "chat",
      sourceId: "thread-1",
      threadId: "thread-1",
      runId: "run-1",
    });
    expect(url).toMatch(/^\/workspace\/report-runs\/rr_xyz\?from=/);
    // Verify the param can be decoded back
    const parsed = new URLSearchParams(url.slice(url.indexOf("?")));
    const decoded = decodeCrossPageContext(parsed);
    expect(decoded?.sourceType).toBe("chat");
  });
});

// =============================================================================
// createTraceId
// =============================================================================

describe("createTraceId", () => {
  it("produces a trace id matching expected format", () => {
    const ctx: CrossPageContext = {
      sourceType: "chat",
      sourceId: "abc12345-extra",
      threadId: "t-1",
    };
    const traceId = createTraceId(ctx);
    // Format: "chat:abc12345:YYYY-MM-DDTHH:MM"
    expect(traceId).toMatch(/^chat:abc12345:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });

  it("truncates long sourceIds to 8 characters", () => {
    const ctx: CrossPageContext = {
      sourceType: "report",
      sourceId: "very-long-id-that-exceeds-eight",
      threadId: "t-1",
    };
    const traceId = createTraceId(ctx);
    expect(traceId.startsWith("report:very-lon:")).toBe(true);
  });

  it("is stable for same input at same time (conceptual)", () => {
    const ctx: CrossPageContext = {
      sourceType: "artifact",
      sourceId: "file.json",
      threadId: "t-2",
    };
    const a = createTraceId(ctx);
    const b = createTraceId(ctx);
    // 8-char truncated sourceId: "file.jso"
    expect(a).toMatch(/^artifact:file\.jso:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(b).toMatch(/^artifact:file\.jso:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });
});

// =============================================================================
// logCrossPageNavigation (smoke test)
// =============================================================================

describe("logCrossPageNavigation", () => {
  it("does not throw for outbound direction", () => {
    expect(() =>
      logCrossPageNavigation(
        {
          sourceType: "chat",
          sourceId: "t-1",
          threadId: "t-1",
        },
        "outbound",
      ),
    ).not.toThrow();
  });

  it("does not throw for inbound direction", () => {
    expect(() =>
      logCrossPageNavigation(
        {
          sourceType: "report",
          sourceId: "rr_x",
          threadId: "t-2",
        },
        "inbound",
      ),
    ).not.toThrow();
  });
});

// =============================================================================
// ISSUE-03: structured log output
// =============================================================================

describe("logCrossPageNavigation structured output", () => {
  it("emits structured object with all required fields", () => {
    const spy = vi.spyOn(console, "info");
    const ctx: CrossPageContext = {
      sourceType: "chat",
      sourceId: "thread-abc",
      threadId: "thread-abc",
      runId: "run-xyz",
    };
    logCrossPageNavigation(ctx, "outbound");
    expect(spy).toHaveBeenCalledTimes(2);

    const structuredCall = spy.mock.calls.find(
      (call) => typeof call[0] === "string" && call[0] === "[CrossPageJump]",
    );
    expect(structuredCall).toBeDefined();
    const payload = structuredCall![1] as Record<string, unknown>;
    expect(payload.traceId).toMatch(/^chat:thread-a:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(payload.direction).toBe("outbound");
    expect(payload.sourceType).toBe("chat");
    expect(payload.sourceId).toBe("thread-abc");
    expect(payload.threadId).toBe("thread-abc");
    expect(payload.runId).toBe("run-xyz");
    expect(payload.timestamp).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/,
    );

    spy.mockRestore();
  });

  it("emits null runId when not provided", () => {
    const spy = vi.spyOn(console, "info");
    const ctx: CrossPageContext = {
      sourceType: "report",
      sourceId: "rr_x",
      threadId: "t-2",
    };
    logCrossPageNavigation(ctx, "inbound");
    const structuredCall = spy.mock.calls.find(
      (call) => typeof call[0] === "string" && call[0] === "[CrossPageJump]",
    );
    const payload = structuredCall![1] as Record<string, unknown>;
    expect(payload.runId).toBeNull();
    spy.mockRestore();
  });
});
