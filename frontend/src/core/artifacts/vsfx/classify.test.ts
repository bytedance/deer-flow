import { describe, expect, test } from "vitest";

import { classifyVsfxArtifactPath } from "./classify";

describe("classifyVsfxArtifactPath", () => {
  test("classifies canonical VSFX family names", () => {
    expect(classifyVsfxArtifactPath("/Artifacts/Example.vsfx")).toEqual({
      kind: "vsfx",
      filepath: "/Artifacts/Example.vsfx",
      directory: "/Artifacts",
      basename: "Example",
    });

    expect(classifyVsfxArtifactPath("/Artifacts/Example.cda.json")).toEqual({
      kind: "cda-json",
      filepath: "/Artifacts/Example.cda.json",
      directory: "/Artifacts",
      basename: "Example",
    });

    expect(
      classifyVsfxArtifactPath("/Artifacts/Example.Properties.json"),
    ).toEqual({
      kind: "properties-json",
      filepath: "/Artifacts/Example.Properties.json",
      directory: "/Artifacts",
      basename: "Example",
    });
  });

  test("matches suffixes case-insensitively while preserving original path casing", () => {
    expect(classifyVsfxArtifactPath("/Artifacts/Mixed/Part.ReV1.VSfX")).toEqual({
      kind: "vsfx",
      filepath: "/Artifacts/Mixed/Part.ReV1.VSfX",
      directory: "/Artifacts/Mixed",
      basename: "Part.ReV1",
    });

    expect(
      classifyVsfxArtifactPath("/Artifacts/Mixed/Part.ReV1.pRoPeRtIeS.JsOn"),
    ).toEqual({
      kind: "properties-json",
      filepath: "/Artifacts/Mixed/Part.ReV1.pRoPeRtIeS.JsOn",
      directory: "/Artifacts/Mixed",
      basename: "Part.ReV1",
    });
  });

  test("preserves directory segments and multi-dot basenames", () => {
    expect(classifyVsfxArtifactPath("nested/path/A.rev1.cda.json")).toEqual({
      kind: "cda-json",
      filepath: "nested/path/A.rev1.cda.json",
      directory: "nested/path",
      basename: "A.rev1",
    });
  });

  test("rejects non-matching suffixes", () => {
    expect(classifyVsfxArtifactPath("foo.json")).toEqual({
      kind: "other",
      filepath: "foo.json",
      directory: "",
      basename: "foo.json",
    });

    expect(classifyVsfxArtifactPath("foo.properties")).toEqual({
      kind: "other",
      filepath: "foo.properties",
      directory: "",
      basename: "foo.properties",
    });

    expect(classifyVsfxArtifactPath("foo.skill")).toEqual({
      kind: "other",
      filepath: "foo.skill",
      directory: "",
      basename: "foo.skill",
    });
  });
});
