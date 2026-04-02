import { describe, expect, it } from "vitest";

import { pairVsfxSiblingMetadata } from "./pairing";

describe("pairVsfxSiblingMetadata", () => {
  it("pairs exact same-directory siblings for a vsfx artifact", () => {
    expect(
      pairVsfxSiblingMetadata({
        openedPath: "/artifacts/widget.vsfx",
        artifactPaths: [
          "/artifacts/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ],
      }),
    ).toEqual({
      primary: "/artifacts/widget.vsfx",
      cda: "/artifacts/widget.cda.json",
      properties: "/artifacts/widget.Properties.json",
    });
  });

  it("returns null for missing sibling files", () => {
    expect(
      pairVsfxSiblingMetadata({
        openedPath: "/artifacts/widget.vsfx",
        artifactPaths: ["/artifacts/widget.vsfx"],
      }),
    ).toEqual({
      primary: "/artifacts/widget.vsfx",
      cda: null,
      properties: null,
    });
  });

  it("does not pair files from other directories", () => {
    expect(
      pairVsfxSiblingMetadata({
        openedPath: "/artifacts/models/widget.vsfx",
        artifactPaths: [
          "/artifacts/models/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ],
      }),
    ).toEqual({
      primary: "/artifacts/models/widget.vsfx",
      cda: null,
      properties: null,
    });
  });

  it("does not pair near matches while still accepting lowercase properties siblings", () => {
    expect(
      pairVsfxSiblingMetadata({
        openedPath: "/artifacts/widget.vsfx",
        artifactPaths: [
          "/artifacts/widget.vsfx",
          "/artifacts/widget-1.cda.json",
          "/artifacts/widget-copy.Properties.json",
          "/artifacts/widget.vsfx.cda.json",
          "/artifacts/widget.Properties.json.bak",
          "/artifacts/widget.properties.json",
          "/artifacts/WIDGET.cda.json",
        ],
      }),
    ).toEqual({
      primary: "/artifacts/widget.vsfx",
      cda: null,
      properties: "/artifacts/widget.properties.json",
    });
  });

  it("supports multi-dot basenames", () => {
    expect(
      pairVsfxSiblingMetadata({
        openedPath: "/artifacts/assembly.v2.final.vsfx",
        artifactPaths: [
          "/artifacts/assembly.v2.final.vsfx",
          "/artifacts/assembly.v2.final.cda.json",
          "/artifacts/assembly.v2.final.Properties.json",
        ],
      }),
    ).toEqual({
      primary: "/artifacts/assembly.v2.final.vsfx",
      cda: "/artifacts/assembly.v2.final.cda.json",
      properties: "/artifacts/assembly.v2.final.Properties.json",
    });
  });
});
