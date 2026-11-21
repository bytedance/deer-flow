import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "@rstest/core";
import GithubSlugger from "github-slugger";

import { localizeDocsHref } from "@/components/docs/localized-links";

const CONTENT_ROOT = join(process.cwd(), "src/content");
const DOC_LANGUAGES = ["en", "zh"] as const;
const DOCS_ORIGIN = "https://docs.example";
const LINK_PATTERN =
  /(?<!!)\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^"']*["'])?\s*\)|\bhref\s*=\s*(?:\{\s*)?["']([^"']+)["'](?:\s*\})?/g;

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

function extractHeadingIds(source: string): Set<string> {
  const slugger = new GithubSlugger();
  const ids = new Set<string>();
  let fence = "";

  for (const line of source.split(/\r?\n/)) {
    const marker = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (marker) {
      const delimiter = marker[1]!;
      if (!fence) {
        fence = delimiter;
      } else if (delimiter.startsWith(fence) && !marker[2]!.trim()) {
        fence = "";
      }
      continue;
    }
    if (fence) continue;

    // Section links currently target ATX headings, not MDX component anchors.
    const heading = /^ {0,3}#{2,6}[\t ]+(.+?)(?:[\t ]+#+)?[\t ]*$/.exec(line);
    if (heading) ids.add(slugger.slug(heading[1]!));
  }
  return ids;
}

function resolveDocsURL(
  href: string,
  lang: string,
  sourceRoute: string,
): URL | undefined {
  const localizedHref = localizeDocsHref(href, lang);
  const url = new URL(localizedHref, `${DOCS_ORIGIN}${sourceRoute}`);
  if (
    url.origin !== DOCS_ORIGIN ||
    !/^\/(?:en|zh)\/docs(?:\/|$)/.test(url.pathname)
  ) {
    return undefined;
  }
  return url;
}

describe("documentation content links", () => {
  it("extracts section IDs outside code fences", () => {
    const source = [
      "# Title",
      "## Overview",
      "```md",
      "## Overview",
      "````",
      "~~~",
      "## 示例",
      "~~~",
      "## Overview",
      "### 故障隔离 ###",
    ].join("\n");

    expect([...extractHeadingIds(source)]).toEqual([
      "overview",
      "overview-1",
      "故障隔离",
    ]);
  });

  it("only links to existing documentation pages and sections", () => {
    const mdxFiles = DOC_LANGUAGES.flatMap((lang) =>
      findMdxFiles(join(CONTENT_ROOT, lang)),
    );
    const routes = new Map(
      DOC_LANGUAGES.flatMap((lang) =>
        mdxFiles
          .filter((path) => path.startsWith(join(CONTENT_ROOT, lang)))
          .map(
            (path) =>
              [
                routeForMdx(path, lang),
                extractHeadingIds(readFileSync(path, "utf8")),
              ] as const,
          ),
      ),
    );

    const brokenLinks = DOC_LANGUAGES.flatMap((lang) =>
      findMdxFiles(join(CONTENT_ROOT, lang)).flatMap((path) => {
        const source = readFileSync(path, "utf8");
        const sourceRoute = routeForMdx(path, lang);
        return extractLinks(source).flatMap(({ href, line }) => {
          const target = resolveDocsURL(href, lang, sourceRoute);
          if (!target) return [];
          const targetRoute = target.pathname.replace(/\/$/, "");
          const headings = routes.get(targetRoute);
          if (
            headings &&
            (!target.hash ||
              headings.has(decodeURIComponent(target.hash.slice(1))))
          ) {
            return [];
          }
          return [
            `${relative(CONTENT_ROOT, path).split(sep).join("/")}:${line} -> ${href} (${targetRoute}${target.hash})`,
          ];
        });
      }),
    );

    expect(brokenLinks).toEqual([]);
  });

  it("documents the custom-agent create request naming contract", () => {
    const customAgentApiDocs = DOC_LANGUAGES.map((lang) =>
      readFileSync(
        join(CONTENT_ROOT, lang, "application/agents-and-threads.mdx"),
        "utf8",
      ),
    );
    const customAgentDocs = [
      ...customAgentApiDocs,
      ...DOC_LANGUAGES.map((lang) =>
        readFileSync(
          join(CONTENT_ROOT, lang, "harness/lead-agent.mdx"),
          "utf8",
        ),
      ),
    ];

    for (const source of customAgentDocs) {
      expect(source).toContain("agents_api.enabled");
      expect(source).toContain("agent_storage.backend: file");
      expect(source).toContain("agent_storage.backend: db");
      expect(source).toContain("database.backend: sqlite");
      expect(source).toContain("database.backend: postgres");
      expect(source).toContain("backend/scripts/migrate_agents_to_db.py");
      expect(source).toContain("users/{user_id}/agents/{name}/config.yaml");
      expect(source).not.toContain("display_name");
    }

    for (const source of customAgentApiDocs) {
      expect(source).toContain("^[A-Za-z0-9-]+$");
      expect(source).toContain("backend/scripts/migrate_user_isolation.py");
    }

    const chineseApiGuide = readFileSync(
      join(CONTENT_ROOT, "zh/application/agents-and-threads.mdx"),
      "utf8",
    );
    expect(chineseApiGuide).toContain('"name": "data-analyst"');
    expect(chineseApiGuide).toContain("下一次 Agent 调用时自动加载，无需重启");

    const englishApiGuide = readFileSync(
      join(CONTENT_ROOT, "en/application/agents-and-threads.mdx"),
      "utf8",
    );
    expect(englishApiGuide).toContain(
      "changes are picked up on the agent's next invocation",
    );
  });
});
