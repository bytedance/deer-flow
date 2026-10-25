import { describe, expect, it } from "@rstest/core";

import { snapForwardToCodePoint } from "@/core/utils/text";

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
