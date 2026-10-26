import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../..");

function source(relativePath: string) {
  return readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

describe("docs search", () => {
  it("builds the Pagefind index that Nextra's search loads", () => {
    const pkg = JSON.parse(source("package.json")) as {
      scripts: Record<string, string>;
      devDependencies: Record<string, string>;
    };

    // Nextra's <Search> imports /_pagefind/pagefind.js at runtime; every build
    // path (Docker, build-static, serve.sh, CI) goes through `pnpm build`.
    expect(pkg.scripts.build).toContain("pnpm run search:index");
    expect(pkg.scripts["search:index"]).toBe(
      "node scripts/build-search-index.mjs",
    );
    expect(pkg.devDependencies.pagefind).toMatch(/^\d+\.\d+\.\d+$/);
    expect(source(".gitignore")).toContain("/public/_pagefind/");
  });
});
