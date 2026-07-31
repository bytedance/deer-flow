import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

const frontendRoot = join(import.meta.dirname, "../../../..");

describe("decorative animation scheduling", () => {
  it("suspends the Galaxy render loop when its container is inactive", () => {
    const source = readFileSync(
      join(frontendRoot, "src/components/landing/hero.tsx"),
      "utf8",
    );

    expect(source).toContain("useRenderActivity");
    expect(source).toContain("renderGalaxy && (");
  });

  it("scopes and coalesces Magic Bento spotlight pointer work", () => {
    const source = readFileSync(
      join(
        frontendRoot,
        "src/components/landing/sections/whats-new-section.tsx",
      ),
      "utf8",
    );

    expect(source).toContain("useRenderActivity");
    expect(source).toContain("enableSpotlight={false}");
    expect(source).toContain('container.addEventListener("pointermove"');
    expect(source).toContain("pendingPointerFrame");
  });
});
