import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "@rstest/core";

import { localizeDocsHref } from "@/components/docs/localized-links";

const CONTENT_ROOT = join(process.cwd(), "src/content");

function findMdxFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory()
      ? findMdxFiles(path)
      : entry.name.endsWith(".mdx")
        ? [path]
        : [];
  });
}

describe("localizeDocsHref", () => {
  it.each([
    ["/docs", "en", "/en/docs"],
    ["/docs/introduction", "en", "/en/docs/introduction"],
    [
      "/docs/introduction?tab=overview#next",
      "zh",
      "/zh/docs/introduction?tab=overview#next",
    ],
  ])("localizes %s for %s", (href, lang, expected) => {
    expect(localizeDocsHref(href, lang)).toBe(expected);
  });

  it.each([
    ["/en/docs/introduction", "zh"],
    ["/zh/docs/introduction", "en"],
    ["https://example.com/docs", "en"],
    ["#overview", "zh"],
    ["mailto:docs@example.com", "en"],
    ["/workspace", "zh"],
    ["/docs-extra", "en"],
    ["/docs/introduction", "fr"],
    ["/docs/introduction", undefined],
  ])("leaves %s unchanged for language %s", (href, lang) => {
    expect(localizeDocsHref(href, lang)).toBe(href);
  });
});

describe("documentation Cards imports", () => {
  it("does not bypass the locale-aware MDX Cards component", () => {
    const violations = findMdxFiles(CONTENT_ROOT)
      .filter((path) => {
        const source = readFileSync(path, "utf8");
        const nextraImports = source.matchAll(
          /import\s*\{([^}]*)\}\s*from\s*["']nextra\/components["']/g,
        );
        return [...nextraImports].some((match) =>
          match[1]?.split(",").some((name) => name.trim() === "Cards"),
        );
      })
      .map((path) => relative(CONTENT_ROOT, path));

    expect(violations).toEqual([]);
  });
});
