import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "@rstest/core";

const CONTENT_ROOT = join(process.cwd(), "src/content");
const DOC_LANGUAGES = ["en", "zh"] as const;
const DOCS_ORIGIN = "https://docs.example";
const LINK_PATTERN =
  /(?<!!)\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^"']*["'])?\s*\)|\bhref\s*=\s*(?:\{\s*)?["']([^"']+)["'](?:\s*\})?/g;
const UNLOCALIZED_DOCS_PATH = /^\/docs(?=\/|[?#]|$)/;

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

function routeForMdx(path: string, lang: string): string {
  const localeRoot = join(CONTENT_ROOT, lang);
  const relativePath = relative(localeRoot, path).split(sep).join("/");
  const pagePath = relativePath
    .replace(/\.mdx$/, "")
    .replace(/(?:^|\/)index$/, "");
  return `/${lang}/docs${pagePath ? `/${pagePath}` : ""}`;
}

function extractLinks(source: string): Array<{ href: string; line: number }> {
  return [...source.matchAll(LINK_PATTERN)].map((match) => ({
    href: match[1] ?? match[2] ?? match[3] ?? "",
    line: source.slice(0, match.index).split("\n").length,
  }));
}

function resolveDocsPath(
  href: string,
  lang: string,
  sourceRoute: string,
): string | undefined {
  const localizedHref = UNLOCALIZED_DOCS_PATH.test(href)
    ? `/${lang}${href}`
    : href;
  const url = new URL(localizedHref, `${DOCS_ORIGIN}${sourceRoute}`);
  if (
    url.origin !== DOCS_ORIGIN ||
    !/^\/(?:en|zh)\/docs(?:\/|$)/.test(url.pathname)
  ) {
    return undefined;
  }
  return url.pathname.replace(/\/$/, "");
}

describe("documentation content links", () => {
  it("only links to documentation routes backed by MDX pages", () => {
    const mdxFiles = DOC_LANGUAGES.flatMap((lang) =>
      findMdxFiles(join(CONTENT_ROOT, lang)),
    );
    const routes = new Set(
      DOC_LANGUAGES.flatMap((lang) =>
        mdxFiles
          .filter((path) => path.startsWith(join(CONTENT_ROOT, lang)))
          .map((path) => routeForMdx(path, lang)),
      ),
    );

    const brokenLinks = DOC_LANGUAGES.flatMap((lang) =>
      findMdxFiles(join(CONTENT_ROOT, lang)).flatMap((path) => {
        const source = readFileSync(path, "utf8");
        const sourceRoute = routeForMdx(path, lang);
        return extractLinks(source).flatMap(({ href, line }) => {
          const targetRoute = resolveDocsPath(href, lang, sourceRoute);
          if (!targetRoute || routes.has(targetRoute)) {
            return [];
          }
          return [
            `${relative(CONTENT_ROOT, path).split(sep).join("/")}:${line} -> ${href} (${targetRoute})`,
          ];
        });
      }),
    );

    expect(brokenLinks).toEqual([]);
  });
});
