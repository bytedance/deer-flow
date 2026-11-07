import { describe, expect, test } from "@rstest/core";

import {
  resolveAuthNextPath,
  validateAuthNextPath,
} from "@/core/auth/next-path";

describe("auth next path validation", () => {
  test("accepts local absolute paths", () => {
    expect(validateAuthNextPath("/workspace")).toBe("/workspace");
    expect(validateAuthNextPath("/workspace/chats/new?tab=recent#top")).toBe(
      "/workspace/chats/new?tab=recent#top",
    );
  });

  test("rejects external and ambiguous redirects", () => {
    expect(validateAuthNextPath(null)).toBeNull();
    expect(validateAuthNextPath("workspace")).toBeNull();
    expect(validateAuthNextPath("//evil.example")).toBeNull();
    expect(validateAuthNextPath("https://evil.example")).toBeNull();
    expect(validateAuthNextPath("/:evil")).toBeNull();
    expect(validateAuthNextPath("/\\evil.example")).toBeNull();
    expect(validateAuthNextPath("/foo\\bar")).toBeNull();
  });

  test("rejects control characters the URL parser would delete", () => {
    // Tab, LF and CR are deleted before parsing, which turns each of these
    // into a protocol-relative URL for evil.example.
    expect(validateAuthNextPath("/\t//evil.example")).toBeNull();
    expect(validateAuthNextPath("/\n//evil.example")).toBeNull();
    expect(validateAuthNextPath("/\r//evil.example")).toBeNull();
    expect(validateAuthNextPath("/\n/evil.example")).toBeNull();
    expect(validateAuthNextPath("/workspace\u0000")).toBeNull();
    expect(validateAuthNextPath("/workspace\u007f")).toBeNull();
    // Percent-encoded forms are not decoded by the parser and stay local.
    expect(validateAuthNextPath("/%0A//evil.example")).toBe(
      "/%0A//evil.example",
    );
  });

  test("falls back for unsafe paths", () => {
    expect(resolveAuthNextPath("/\\evil.example")).toBe("/workspace");
    expect(resolveAuthNextPath("/\n//evil.example")).toBe("/workspace");
    expect(resolveAuthNextPath("/safe", "/fallback")).toBe("/safe");
  });
});
