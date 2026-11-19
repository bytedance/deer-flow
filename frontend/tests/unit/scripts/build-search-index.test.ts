import {
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

const api = rs.hoisted(() => ({
  createIndex: rs.fn(),
  addHTMLFile: rs.fn(),
  writeFiles: rs.fn(),
  close: rs.fn(),
}));

rs.mock("pagefind", () => ({
  createIndex: api.createIndex,
  close: api.close,
}));

import {
  buildSearchIndex,
  localeForPage,
  withHtmlLang,
} from "../../../scripts/build-search-index.mjs";

let root: string;
let siteDir: string;
let outputDir: string;

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "docs-search-index-"));
  siteDir = path.join(root, "site");
  outputDir = path.join(root, "public", "_pagefind");
  await mkdir(path.join(siteDir, "en", "docs"), { recursive: true });
  await mkdir(path.dirname(outputDir), { recursive: true });
  api.createIndex.mockReset().mockResolvedValue({
    index: { addHTMLFile: api.addHTMLFile, writeFiles: api.writeFiles },
    errors: [],
  });
  api.addHTMLFile.mockReset().mockResolvedValue({ errors: [] });
  api.writeFiles.mockReset().mockImplementation(async ({ outputPath }) => {
    await mkdir(outputPath, { recursive: true });
    // Like Pagefind, only write new hashed assets; leave previous files alone.
    await writeFile(
      path.join(outputPath, `fragment-${api.writeFiles.mock.calls.length}`),
      "indexed content",
    );
    return { errors: [] };
  });
  api.close.mockReset().mockResolvedValue(undefined);
  rs.spyOn(console, "log").mockImplementation(() => undefined);
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
  rs.restoreAllMocks();
});

describe("docs search index", () => {
  it("replaces old generated assets on a second build and preserves other public files", async () => {
    const oldPage = path.join(siteDir, "en", "docs", "old.html");
    const logo = path.join(root, "public", "logo.txt");
    await writeFile(oldPage, '<html lang="en-US"><body>Old page</body></html>');
    await writeFile(logo, "unrelated public asset");
    await buildSearchIndex({ siteDir, outputDir });
    expect(await readdir(outputDir)).toEqual(["fragment-1"]);

    await rm(oldPage);
    await writeFile(
      path.join(siteDir, "en", "docs", "renamed.html"),
      '<html lang="en-US"><body>Renamed page</body></html>',
    );
    await buildSearchIndex({ siteDir, outputDir });

    expect(await readdir(outputDir)).toEqual(["fragment-2"]);
    expect(await readFile(logo, "utf8")).toBe("unrelated public asset");
    expect(api.addHTMLFile.mock.calls.map(([page]) => page.url)).toEqual([
      "/en/docs/old.html",
      "/en/docs/renamed.html",
    ]);
    expect(api.close).toHaveBeenCalledTimes(2);
  });

  it("indexes nested HTML with the route language and leaves other assets out", async () => {
    await mkdir(path.join(siteDir, "zh", "docs"), { recursive: true });
    await writeFile(
      path.join(siteDir, "zh", "docs", "sandbox.html"),
      '<html lang="en-US" class="theme"><body>沙箱</body></html>',
    );
    await writeFile(path.join(siteDir, "en", "docs", "image.png"), "image");
    await buildSearchIndex({ siteDir, outputDir });
    expect(api.addHTMLFile).toHaveBeenCalledExactlyOnceWith({
      url: "/zh/docs/sandbox.html",
      content: '<html lang="zh-CN" class="theme"><body>沙箱</body></html>',
    });
  });

  it("uses one tokenizer per supported route language", () => {
    expect(localeForPage("zh/docs/harness/memory.html")).toBe("zh-CN");
    expect(localeForPage("zh.html")).toBe("zh-CN");
    expect(localeForPage("en/docs/harness/memory.html")).toBe("en-US");
    expect(localeForPage("blog/posts.html")).toBeUndefined();
    expect(withHtmlLang('<html lang="en-US" class="theme">', "zh-CN")).toBe(
      '<html lang="zh-CN" class="theme">',
    );
  });

  it("keeps the previous index if reading/indexing pages fails, and closes Pagefind", async () => {
    await mkdir(outputDir, { recursive: true });
    await writeFile(path.join(outputDir, "pagefind.js"), "previous index");
    await writeFile(path.join(siteDir, "en", "docs", "page.html"), "page");
    api.addHTMLFile.mockResolvedValueOnce({ errors: ["indexing failed"] });

    await expect(buildSearchIndex({ siteDir, outputDir })).rejects.toThrow(
      "indexing failed",
    );
    expect(await readFile(path.join(outputDir, "pagefind.js"), "utf8")).toBe(
      "previous index",
    );
    expect(api.writeFiles).not.toHaveBeenCalled();
    expect(api.close).toHaveBeenCalledTimes(1);
  });

  it("reports publication errors and closes Pagefind", async () => {
    api.writeFiles.mockResolvedValueOnce({ errors: ["write failed"] });
    await expect(buildSearchIndex({ siteDir, outputDir })).rejects.toThrow(
      "write failed",
    );
    expect(api.close).toHaveBeenCalledTimes(1);
  });
});
