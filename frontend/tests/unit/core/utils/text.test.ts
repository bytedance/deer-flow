import { describe, expect, it } from "@rstest/core";

import {
  snapForwardToCodePoint,
  truncateToCodePoints,
} from "@/core/utils/text";

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

describe("snapForwardToCodePoint", () => {
  const emoji = "😀"; // U+1F600: one high + one low surrogate unit

  it("moves a cut between surrogate halves forward one unit", () => {
    const text = `a${emoji}b`;
    expect(snapForwardToCodePoint(text, 2)).toBe(3);
  });

  it("leaves cuts at pair boundaries and between BMP characters untouched", () => {
    const text = `a${emoji}b`;
    expect(snapForwardToCodePoint(text, 0)).toBe(0);
    expect(snapForwardToCodePoint(text, 1)).toBe(1);
    expect(snapForwardToCodePoint(text, 3)).toBe(3);
    expect(snapForwardToCodePoint(text, 4)).toBe(4);
  });

  it("returns out-of-range indices unchanged", () => {
    expect(snapForwardToCodePoint("ab", 5)).toBe(5);
    expect(snapForwardToCodePoint("", 0)).toBe(0);
  });
});
