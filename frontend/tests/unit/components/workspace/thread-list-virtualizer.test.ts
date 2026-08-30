import { describe, expect, it } from "@rstest/core";

import { calculateScrollMargin } from "@/components/workspace/thread-list-virtualizer";

describe("calculateScrollMargin", () => {
  it("keeps a nested list aligned to its scrolling ancestor", () => {
    expect(calculateScrollMargin(180, 40, 0)).toBe(140);
    expect(calculateScrollMargin(-320, 40, 500)).toBe(140);
  });

  it("does not produce a negative virtual-list origin", () => {
    expect(calculateScrollMargin(20, 40, 0)).toBe(0);
  });
});
