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
    expect(source).toContain(
      'dynamic(() => import("@/components/ui/galaxy"), { ssr: false })',
    );
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
    expect(source).toContain('import("@/components/ui/magic-bento")');
    expect(source).toContain("ssr: false");
    expect(source).toContain(
      "useRenderActivity(bentoContainerRef, false, false)",
    );
    expect(source).toContain("disableAnimations={reducedMotion}");
    expect(source).toContain('container.addEventListener("pointermove"');
    expect(source).toContain("pendingPointerFrame");
  });

  it("does not load the skills animation before its section is visible", () => {
    const source = readFileSync(
      join(frontendRoot, "src/components/landing/sections/skills-section.tsx"),
      "utf8",
    );

    expect(source).toContain('import("../progressive-skills-animation")');
    expect(source).toContain("ssr: false");
    expect(source).toContain("useRenderActivity(animationRef, false)");
    expect(source).toContain(
      "renderAnimation && <ProgressiveSkillsAnimation />",
    );
  });
});
