import { describe, expect, it } from "@rstest/core";

import { buildArtifactFileTree } from "@/core/artifacts/file-tree";

describe("buildArtifactFileTree", () => {
  it("groups nested output paths into a stable folder-first tree", () => {
    expect(
      buildArtifactFileTree([
        "/mnt/user-data/outputs/report.md",
        "/mnt/user-data/outputs/src/index.ts",
        "/mnt/user-data/outputs/src/components/button.tsx",
        "/mnt/user-data/outputs/assets/logo.png",
        "/mnt/user-data/outputs/report.md",
      ]),
    ).toEqual([
      {
        type: "directory",
        name: "assets",
        path: "assets",
        children: [
          {
            type: "file",
            name: "logo.png",
            path: "/mnt/user-data/outputs/assets/logo.png",
          },
        ],
      },
      {
        type: "directory",
        name: "src",
        path: "src",
        children: [
          {
            type: "directory",
            name: "components",
            path: "src/components",
            children: [
              {
                type: "file",
                name: "button.tsx",
                path: "/mnt/user-data/outputs/src/components/button.tsx",
              },
            ],
          },
          {
            type: "file",
            name: "index.ts",
            path: "/mnt/user-data/outputs/src/index.ts",
          },
        ],
      },
      {
        type: "file",
        name: "report.md",
        path: "/mnt/user-data/outputs/report.md",
      },
    ]);
  });

  it("handles static-demo roots and ignores empty paths", () => {
    expect(
      buildArtifactFileTree([
        "user-data/outputs/site/index.html",
        "mnt/user-data/outputs/site/style.css",
        "",
      ]),
    ).toEqual([
      {
        type: "directory",
        name: "site",
        path: "site",
        children: [
          {
            type: "file",
            name: "index.html",
            path: "user-data/outputs/site/index.html",
          },
          {
            type: "file",
            name: "style.css",
            path: "mnt/user-data/outputs/site/style.css",
          },
        ],
      },
    ]);
  });
});
