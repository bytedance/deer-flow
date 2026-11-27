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

  it("passes resolved locale to Footer and avoids outer px-10 header gutters in docs and blog layouts", () => {
    const docsLayout = source("src/app/[lang]/docs/layout.tsx");
    const blogLayout = source("src/app/blog/layout.tsx");

    expect(docsLayout).toContain('<Footer className="mt-0" locale={locale} />');
    expect(blogLayout).toContain("<Footer locale={locale} />");
    expect(docsLayout).not.toContain("px-10");
    expect(blogLayout).not.toContain("px-10");
  });

  it("loads bundled local fonts without build-time next/font/google network requests", () => {
    const rootLayout = source("src/app/layout.tsx");

    expect(rootLayout).toContain('from "next/font/local"');
    expect(rootLayout).not.toContain("next/font/google");
    expect(rootLayout).toContain("--font-landing-serif");
    expect(rootLayout).toContain("--font-landing-sans");
    expect(rootLayout).toContain("--font-mono");
  });
});
