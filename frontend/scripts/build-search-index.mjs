#!/usr/bin/env node

// Builds the Pagefind index that Nextra's docs <Search> loads from
// /_pagefind/. The root layout renders a fixed <html lang>, so the Pagefind
// CLI would index every page as English and leave Chinese text unsegmented.
// Rewrite each page's lang from its /{lang}/ route prefix first, so Pagefind
// writes one correctly tokenized index per language.

import { readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import * as pagefind from "pagefind";

const SITE_DIR = ".next/server/app";
const OUTPUT_DIR = "public/_pagefind";
const LOCALE_BY_PREFIX = { en: "en-US", zh: "zh-CN" };

async function* htmlFiles(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* htmlFiles(fullPath);
    } else if (entry.name.endsWith(".html")) {
      yield fullPath;
    }
  }
}

export function localeForPage(relativePath) {
  const prefix = relativePath.split(/[/\\.]/)[0];
  return LOCALE_BY_PREFIX[prefix];
}

export function withHtmlLang(html, locale) {
  return html.replace(
    /<html\b([^>]*?)\blang="[^"]*"/,
    `<html$1lang="${locale}"`,
  );
}

export async function buildSearchIndex({
  siteDir = SITE_DIR,
  outputDir = OUTPUT_DIR,
} = {}) {
  try {
    const { index, errors } = await pagefind.createIndex();
    if (!index) throw new Error(errors.join("\n"));

    let pages = 0;
    for await (const file of htmlFiles(siteDir)) {
      const sourcePath = path.relative(siteDir, file);
      const html = await readFile(file, "utf8");
      const locale = localeForPage(sourcePath);
      const result = await index.addHTMLFile({
        // Pagefind derives the result URL from sourcePath, relative to the site.
        url: `/${sourcePath.split(path.sep).join("/")}`,
        content: locale ? withHtmlLang(html, locale) : html,
      });
      if (result.errors.length) throw new Error(result.errors.join("\n"));
      pages += 1;
    }

    // Pagefind never deletes older content-hashed fragments. Rebuild this
    // generated directory so removed pages and previous builds do not accumulate.
    await rm(outputDir, { recursive: true, force: true });
    const written = await index.writeFiles({ outputPath: outputDir });
    if (written.errors.length) throw new Error(written.errors.join("\n"));
    console.log(`Pagefind: scanned ${pages} HTML files into ${outputDir}`);
  } finally {
    await pagefind.close();
  }
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  buildSearchIndex().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
