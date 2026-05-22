import { expect, test } from "vitest";

import { isArtifactPreviewSupported } from "@/core/artifacts/preview";

test("allows completed html and markdown artifact previews", () => {
  expect(
    isArtifactPreviewSupported({ language: "html", isWriteFile: false }),
  ).toBe(true);
  expect(
    isArtifactPreviewSupported({ language: "markdown", isWriteFile: false }),
  ).toBe(true);
});

test("keeps in-progress html writes out of iframe preview", () => {
  expect(
    isArtifactPreviewSupported({ language: "html", isWriteFile: true }),
  ).toBe(false);
});

test("allows markdown write-file previews", () => {
  expect(
    isArtifactPreviewSupported({ language: "markdown", isWriteFile: true }),
  ).toBe(true);
});
