import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

describe("large artifact preview", () => {
  it("requires an explicit full load before mounting the code editor", () => {
    const source = readFileSync(
      join(
        import.meta.dirname,
        "../../../../../src/components/workspace/artifacts/artifact-file-detail.tsx",
      ),
      "utf8",
    );

    expect(source).toContain("loadFullContent");
    expect(source).toContain("!truncated &&");
    expect(source).toContain("artifactPreview.loadFullFile");
    expect(source).toContain("ArtifactPreviewError");
    expect(source).toContain("artifactPreview.previewFailed");
    expect(source).toContain("download: true");
  });
});
