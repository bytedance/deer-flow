import { build } from "esbuild";
import { readdir, rm, writeFile } from "node:fs/promises";
const root = "deerflow_extension_office_preview";
await rm(new URL(`./${root}/static/dist/`, import.meta.url), {
  recursive: true,
  force: true,
});
await build({
  entryPoints: { index: "ui/index.js" },
  bundle: true,
  splitting: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  outdir: `${root}/static/dist`,
  entryNames: "[dir]/[name]",
  chunkNames: "chunks/[name]-[hash]",
  outExtension: { ".js": ".mjs" },
  minify: true,
  legalComments: "eof",
});
// Gateway assets carry CSP: sandbox. Keep this worker self-contained: a worker
// with an opaque origin cannot fetch additional authenticated module chunks.
await build({
  entryPoints: ["ui/office-worker.js"],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  outfile: `${root}/static/dist/chunks/office-worker.mjs`,
  minify: true,
  legalComments: "eof",
});
const files = (await readdir(`${root}/static/dist`, { recursive: true }))
  .filter((p) => /\.mjs$/.test(p))
  .map((p) => `static/dist/${p.replaceAll("\\", "/")}`)
  .sort();
await writeFile(
  `${root}/ui_manifest.json`,
  JSON.stringify(
    { schema_version: 1, entry: "static/dist/index.mjs", files },
    null,
    2,
  ) + "\n",
);
