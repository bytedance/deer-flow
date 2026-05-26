import { describe, expect, it } from "vitest";

import { truncateFactPreview } from "@/core/memory/utils";

describe("truncateFactPreview", () => {
  it("returns short content unchanged", () => {
    expect(truncateFactPreview("hello world")).toBe("hello world");
  });

  it("normalizes whitespace", () => {
    expect(truncateFactPreview("  hello   world  ")).toBe("hello world");
  });

  it("truncates long content with ellipsis", () => {
    const long = "a".repeat(250);
    const result = truncateFactPreview(long);
    expect(result).toHaveLength(200);
    expect(result.endsWith("...")).toBe(true);
  });

  it("respects custom maxLength", () => {
    const result = truncateFactPreview("abcdefghij", 7);
    expect(result).toBe("abcd...");
    expect(result).toHaveLength(7);
  });

  it("returns exact content when length equals maxLength", () => {
    const content = "12345";
    expect(truncateFactPreview(content, 5)).toBe("12345");
  });

  it("handles empty string", () => {
    expect(truncateFactPreview("")).toBe("");
  });

  it("handles whitespace-only string", () => {
    expect(truncateFactPreview("   \n\t  ")).toBe("");
  });
});
