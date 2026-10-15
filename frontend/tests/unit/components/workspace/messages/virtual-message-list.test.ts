import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

describe("message history virtualization", () => {
  it("uses measured stable-key rows and keeps the active tail mounted", () => {
    const source = readFileSync(
      path.resolve(
        __dirname,
        "../../../../../src/components/workspace/messages/virtual-message-list.tsx",
      ),
      "utf8",
    );

    expect(source).toContain("useVirtualizer");
    expect(source).toContain("measureElement");
    expect(source).toContain("getItemKey");
    expect(source).toContain("activeIndex");
    expect(source).toContain("overscan: 8");
  });
});
