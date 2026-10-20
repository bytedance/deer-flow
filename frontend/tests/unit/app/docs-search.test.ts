import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  localeForPage,
  withHtmlLang,
} from "../../../scripts/build-search-index.mjs";

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

  it("renders search in the custom docs header, scoped to the page language", () => {
    const layout = source("src/app/[lang]/docs/layout.tsx");

    // The docs layout replaces Nextra's navbar with the landing Header, so the
    // search control must be passed in explicitly or it never renders.
    expect(layout).toMatch(/<Header[\s\S]*search=\{search\}/);
    expect(layout).toContain("data-pagefind-filter={`lang:${lang}`}");
    expect(layout).toContain("searchOptions={{ filters: { lang } }}");
    expect(layout).toContain("aria-label={t.home.searchDocsLabel}");
    // Only the header's instances may exist: a hidden copy in Nextra's own
    // mobile menu would take the Cmd/Ctrl+K shortcut.
    expect(layout).toContain("search={null}");
    expect(layout).toContain("<DocsHtmlLang lang={lang} />");

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

  it("indexes each docs language with its own Pagefind tokenizer", () => {
    // The root layout's <html lang> is fixed; without this Chinese pages are
    // indexed as English and multi-character words like 偏好 never match.
    expect(localeForPage("zh/docs/harness/memory.html")).toBe("zh-CN");
    expect(localeForPage("zh.html")).toBe("zh-CN");
    expect(localeForPage("en/docs/harness/memory.html")).toBe("en-US");
    expect(localeForPage("blog/posts.html")).toBeUndefined();
    expect(
      withHtmlLang(
        '<html lang="en-US" class="x"><body></body></html>',
        "zh-CN",
      ),
    ).toBe('<html lang="zh-CN" class="x"><body></body></html>');
  });

  it("closes the mobile menu when the route changes", () => {
    const mobileNav = source("src/components/landing/mobile-nav.tsx");
    expect(mobileNav).toMatch(
      /if \(pathname !== openedPath\) \{[^}]*setOpen\(false\)/,
    );
  });
});
