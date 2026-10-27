import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

const CONTENT_ROOT = join(process.cwd(), "src/content");
// An unquoted frontmatter scalar containing ": " parses as a nested mapping and
// makes Nextra's YAML frontmatter fail, which 500s every page in the section.
// Only `next build` (or a dev-server render) compiles MDX, so the unit suite has
// to keep this guard on its own.
const UNQUOTED_MAPPING_VALUE = /^([A-Za-z_][\w-]*):[ \t]*(?![|>])/;
const SAFE_VALUE = /^(".*"|'.*'|\[.*\]|\{.*\}|[|>]|$)/;

describe("docs frontmatter", () => {
  const files = readdirSync(CONTENT_ROOT, { recursive: true })
    .map((entry) => join(CONTENT_ROOT, String(entry)))
    .filter((path) => path.endsWith(".mdx"));

  it("finds the content tree it is meant to guard", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it("keeps every frontmatter block YAML-parseable", () => {
    const offenders = files.flatMap((path) => {
      const source = readFileSync(path, "utf8");
      if (!source.startsWith("---\n")) {
        return [];
      }
      const displayPath = path
        .slice(CONTENT_ROOT.length + 1)
        .split("\\")
        .join("/");
      return source
        .slice(4, source.indexOf("\n---", 4))
        .split("\n")
        .flatMap((line, index) => {
          const key = UNQUOTED_MAPPING_VALUE.exec(line);
          if (key === null) {
            return [];
          }
          const value = line.slice(key[0].length);
          return !SAFE_VALUE.test(value) && value.includes(": ")
            ? [
                `${displayPath}:${index + 2}: unquoted "${key[1]}" value contains ": "`,
              ]
            : [];
        });
    });

    expect(offenders).toEqual([]);
  });
});
