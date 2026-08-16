import { describe, expect, it } from "@rstest/core";

import {
  formatToolCallPayload,
  TOOL_CALL_PAYLOAD_LIMIT,
} from "@/components/workspace/messages/generic-tool-call-details";

describe("formatToolCallPayload", () => {
  it("formats nested JSON-compatible values", () => {
    expect(
      formatToolCallPayload({
        query: "deer flow",
        options: { limit: 3, enabled: true },
      }),
    ).toEqual({
      text: `{
  "query": "deer flow",
  "options": {
    "limit": 3,
    "enabled": true
  }
}`,
      truncated: false,
    });
  });

  it("bounds large strings without serializing the complete payload", () => {
    const formatted = formatToolCallPayload("x".repeat(100_000));

    expect(formatted.truncated).toBe(true);
    expect(formatted.text.length).toBeLessThanOrEqual(TOOL_CALL_PAYLOAD_LIMIT);
    expect(formatted.text.startsWith('"xxx')).toBe(true);
    expect(formatted.text.endsWith('"')).toBe(true);
  });

  it("marks oversized collections as truncated", () => {
    const formatted = formatToolCallPayload(
      Array.from({ length: 101 }, (_, index) => index),
      10_000,
    );

    expect(formatted.truncated).toBe(true);
    expect(formatted.text).toContain("99");
    expect(formatted.text).not.toContain("100");
  });

  it("handles circular diagnostic data without throwing", () => {
    const value: Record<string, unknown> = { id: "call-1" };
    value.self = value;

    expect(formatToolCallPayload(value)).toEqual({
      text: `{
  "id": "call-1",
  "self": "[Circular]"
}`,
      truncated: false,
    });
  });
});
