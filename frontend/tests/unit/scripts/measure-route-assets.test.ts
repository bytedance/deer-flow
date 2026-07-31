import { describe, expect, it } from "@rstest/core";

import {
  evaluateBudgets,
  extractAssetPaths,
  ROUTES,
} from "../../../scripts/measure-route-assets.mjs";

describe("route asset measurement", () => {
  it("covers every approved representative route", () => {
    expect(ROUTES).toContain("/login");
  });

  it("extracts unique Next.js scripts and styles", () => {
    const html = `
      <link rel="stylesheet" href="/_next/static/css/app.css?dpl=1">
      <script src="/_next/static/chunks/app.js"></script>
      <script src="/_next/static/chunks/app.js"></script>
      <script src="https://cdn.example.com/external.js"></script>
    `;

    expect(extractAssetPaths(html)).toEqual({
      css: ["css/app.css"],
      js: ["chunks/app.js"],
    });
  });

  it("reports every route budget overage with exact values", () => {
    const result = evaluateBudgets(
      {
        "/": { css: 101, js: 200 },
        "/en/docs": { css: 50, js: 301 },
      },
      {
        "/": { css: 100, js: 200 },
        "/en/docs": { css: 50, js: 300 },
      },
    );

    expect(result).toEqual([
      "/ css: 101 bytes exceeds 100 bytes by 1 byte",
      "/en/docs js: 301 bytes exceeds 300 bytes by 1 byte",
    ]);
  });
});
