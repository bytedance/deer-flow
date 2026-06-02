import { describe, expect, it } from "vitest";

import { __test_only } from "@/components/workspace/chats/use-deep-link-chat";

const {
  stripControlChars,
  validatePrompt,
  validateAutoSend,
  validateSource,
  validateContext,
  validatePassthroughValue,
  MAX_PROMPT_LEN,
  MAX_SOURCE_LEN,
  MAX_CONTEXT_LEN,
  MAX_PASSTHROUGH_LEN,
} = __test_only;

describe("stripControlChars", () => {
  it("strips null bytes", () => {
    expect(stripControlChars("hello\x00world")).toBe("helloworld");
  });

  it("strips other control characters", () => {
    expect(stripControlChars("a\x01b\x02c")).toBe("abc");
  });

  it("keeps space, tab, newline, carriage return", () => {
    expect(stripControlChars("a\tb\nc\r d")).toBe("a\tb\nc\r d");
  });

  it("returns empty for all-control input", () => {
    expect(stripControlChars("\x00\x01\x02")).toBe("");
  });
});

describe("validatePrompt", () => {
  it("returns trimmed prompt", () => {
    expect(validatePrompt("  hello world  ")).toBe("hello world");
  });

  it("returns null for empty", () => {
    expect(validatePrompt("")).toBeNull();
  });

  it("returns null for whitespace only", () => {
    expect(validatePrompt("   ")).toBeNull();
  });

  it("returns null for null input", () => {
    expect(validatePrompt(null)).toBeNull();
  });

  it("truncates at max length", () => {
    const long = "a".repeat(MAX_PROMPT_LEN + 100);
    expect(validatePrompt(long)).toHaveLength(MAX_PROMPT_LEN);
  });

  it("strips control characters", () => {
    expect(validatePrompt("hello\x00world")).toBe("helloworld");
  });
});

describe("validateAutoSend", () => {
  it("returns true for '1'", () => {
    expect(validateAutoSend("1")).toBe(true);
  });

  it("returns false for anything else", () => {
    expect(validateAutoSend("true")).toBe(false);
    expect(validateAutoSend("yes")).toBe(false);
    expect(validateAutoSend("")).toBe(false);
    expect(validateAutoSend(null)).toBe(false);
  });
});

describe("validateSource", () => {
  it("returns trimmed value", () => {
    expect(validateSource("  grafana  ")).toBe("grafana");
  });

  it("returns null for empty", () => {
    expect(validateSource("")).toBeNull();
    expect(validateSource(null)).toBeNull();
  });

  it("truncates at max length", () => {
    const long = "a".repeat(MAX_SOURCE_LEN + 50);
    expect(validateSource(long)).toHaveLength(MAX_SOURCE_LEN);
  });
});

describe("validateContext", () => {
  it("returns trimmed value", () => {
    expect(validateContext("  ctx-123  ")).toBe("ctx-123");
  });

  it("returns null for empty", () => {
    expect(validateContext("")).toBeNull();
    expect(validateContext(null)).toBeNull();
  });

  it("truncates at max length", () => {
    const long = "a".repeat(MAX_CONTEXT_LEN + 50);
    expect(validateContext(long)).toHaveLength(MAX_CONTEXT_LEN);
  });
});

describe("validatePassthroughValue", () => {
  it("returns trimmed value", () => {
    expect(validatePassthroughValue("  P-203A  ")).toBe("P-203A");
  });

  it("returns null for empty after trim", () => {
    expect(validatePassthroughValue("   ")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(validatePassthroughValue("")).toBeNull();
  });

  it("truncates at max length", () => {
    const long = "a".repeat(MAX_PASSTHROUGH_LEN + 100);
    expect(validatePassthroughValue(long)).toHaveLength(MAX_PASSTHROUGH_LEN);
  });

  it("strips control characters", () => {
    expect(validatePassthroughValue("P-203\x00A")).toBe("P-203A");
  });
});
