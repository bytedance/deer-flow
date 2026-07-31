import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "@rstest/core";

const frontendRoot = join(import.meta.dirname, "../../../..");

describe("decorative animation scheduling", () => {
  it("suspends the Galaxy render loop when its container is inactive", () => {
    const source = readFileSync(
      join(frontendRoot, "src/components/ui/galaxy.jsx"),
      "utf8",
    );

    expect(source).toContain("observeRenderActivity");
    expect(source).toContain("if (!renderActive)");
  });

  it("scopes and coalesces Magic Bento spotlight pointer work", () => {
    const source = readFileSync(
      join(frontendRoot, "src/components/ui/magic-bento.tsx"),
      "utf8",
    );

    expect(source).not.toContain(
      'document.addEventListener("mousemove", handleMouseMove)',
    );
    expect(source).toContain('section.addEventListener("pointermove"');
    expect(source).toContain("pendingPointerFrame");
  });
});
