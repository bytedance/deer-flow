import { describe, expect, it } from "@rstest/core";

import { truncateToCodePoints } from "@/core/utils/text";

const loneSurrogate = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])/;

describe("truncateToCodePoints", () => {
  it("returns a value that fits the code-point budget unchanged", () => {
    // 120 code points but 121 UTF-16 units: the whole value fits.
    const fits = `${"a".repeat(118)}😀b`;
    expect(truncateToCodePoints(fits, 120)).toBe(fits);
  });

  it("never splits a surrogate pair at the cut", () => {
    // 122 code points / 123 UTF-16 units: the cut lands after the whole emoji.
    const overflow = `${"a".repeat(119)}😀bc`;
    const truncated = truncateToCodePoints(overflow, 120);
    expect(truncated).toBe(`${"a".repeat(119)}😀`);
    expect(truncated).not.toMatch(loneSurrogate);
  });

  it("spends the ellipsis inside the budget", () => {
    const overflow = `${"a".repeat(139)}😀x`;
    const truncated = truncateToCodePoints(overflow, 140, "...");
    expect(truncated).toBe(`${"a".repeat(137)}...`);
    expect(truncated.length).toBeLessThanOrEqual(140);
    expect(truncated).not.toMatch(loneSurrogate);
  });

  it("falls back to a plain cut when the budget cannot hold the ellipsis", () => {
    expect(truncateToCodePoints("abcd", 2, "...")).toBe("ab");
    expect(truncateToCodePoints("abcd", 3, "...")).toBe("abc");
  });
});
