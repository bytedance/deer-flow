import { describe, expect, it } from "@rstest/core";

import { isSafeHref } from "@/components/workspace/messages/markdown-link";

describe("isSafeHref", () => {
  it("allows web URLs and same-origin paths", () => {
    expect(isSafeHref("https://example.com/path")).toBe(true);
    expect(isSafeHref("http://example.com/path")).toBe(true);
    expect(isSafeHref("/workspace/chats/1")).toBe(true);
    expect(isSafeHref("#section")).toBe(true);
  });

  it("rejects executable, local, and malformed URLs", () => {
    expect(isSafeHref("javascript:alert(1)")).toBe(false);
    expect(isSafeHref("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(isSafeHref("file:///etc/passwd")).toBe(false);
    expect(isSafeHref("//example.com/path")).toBe(false);
    expect(isSafeHref("relative/path")).toBe(false);
    expect(isSafeHref(undefined)).toBe(false);
  });
});
