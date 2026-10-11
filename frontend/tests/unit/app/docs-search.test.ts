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
      "pagefind --site .next/server/app --output-path public/_pagefind",
    );
    expect(pkg.devDependencies.pagefind).toMatch(/^\d+\.\d+\.\d+$/);
    expect(source(".gitignore")).toContain("/public/_pagefind/");
  });

  it("renders search in the custom docs header, scoped to the page language", () => {
    const layout = source("src/app/[lang]/docs/layout.tsx");

    // The docs layout replaces Nextra's navbar with the landing Header, so the
    // search control must be passed in explicitly or it never renders.
    expect(layout).toMatch(/<Header[\s\S]*search=\{search\}/);
    expect(layout).toContain("data-pagefind-filter={`lang:${lang}`}");
    expect(layout).toContain("searchOptions={{ filters: { lang } }}");
    expect(layout).toContain("aria-label={t.home.searchDocsLabel}");

    const header = source("src/components/landing/header.tsx");
    expect(header).toContain("search?: ReactNode");
    expect(header).toContain("search={search}");
  });

  it("keeps search results tappable inside the mobile menu sheet", () => {
    // The results portal renders outside the modal sheet: it must sit above
    // the sheet, ignore the body's pointer-events lock, and not count as an
    // outside click that closes the sheet before navigation.
    const mobileNav = source("src/components/landing/mobile-nav.tsx");
    expect(mobileNav).toContain('".nextra-search-results"');
    expect(mobileNav).toContain("onInteractOutside");

    const css = source("src/styles/globals.css");
    expect(css).toMatch(
      /\.nextra-search-results \{[^}]*z-index: 60;[^}]*pointer-events: auto;/,
    );
  });
});
