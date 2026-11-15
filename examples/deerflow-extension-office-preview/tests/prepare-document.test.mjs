import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import JSZip from "jszip";
import { prepareDocument } from "../ui/prepare-document.js";
import { LIMITS, preflightZip } from "../ui/resource-limits.js";

const fixtures = new URL(
  "../../../frontend/tests/e2e/fixtures/office-preview/",
  import.meta.url,
);
async function source(name) {
  const bytes = await readFile(new URL(name, fixtures));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length);
}
for (const [name, kind] of [
  ["navigation.xlsx", "xlsx"],
  ["navigation.docx", "docx"],
  ["project-review.pptx", "pptx"],
  ["chart-only.xlsx", "xlsx"],
]) {
  test(`preserves preview data for ${name}`, async () => {
    const bytes = await source(name),
      original = new Uint8Array(bytes).slice();
    const result = await prepareDocument(bytes, kind);
    assert.deepEqual(
      new Uint8Array(bytes),
      original,
      "original download bytes stay unchanged",
    );
    if (kind === "xlsx") {
      assert.ok(result.sheets.length > 0);
      assert.ok(result.sheets[0].rows[0].cells.length > 0);
    } else assert.ok(result.word || result.slides);
  });
}
for (const [kind, name, entry] of [
  ["xlsx", "navigation.xlsx", "xl/worksheets/sheet1.xml"],
  ["docx", "navigation.docx", "word/document.xml"],
  ["pptx", "project-review.pptx", "ppt/slides/slide1.xml"],
]) {
  test(`rejects adversarial ${kind} within the old byte/member limits`, async () => {
    const zip = await JSZip.loadAsync(await source(name));
    zip.file(
      entry,
      "<root>" + "<n/>".repeat(LIMITS.xmlElements + 1) + "</root>",
    );
    const bytes = await zip.generateAsync({
      type: "arraybuffer",
      compression: "STORE",
    });
    assert.ok(bytes.byteLength < LIMITS.inputBytes);
    const records = preflightZip(bytes);
    assert.ok(records.length < 4000);
    assert.ok(
      records.reduce((n, record) => n + record.uncompressed, 0) <
        100 * 1024 * 1024,
    );
    await assert.rejects(prepareDocument(bytes, kind), /complex|limit/i);
  });
}
test("forged metadata is rejected before JSZip loads any archive", async () => {
  const bytes = await source("navigation.docx");
  const record = preflightZip(bytes).find(
    (record) => !record.name.endsWith("/"),
  );
  new DataView(bytes).setUint32(
    record.directoryOffset + 24,
    101 * 1024 * 1024,
    true,
  );
  const load = JSZip.loadAsync;
  JSZip.loadAsync = () =>
    assert.fail("archive parser must not run before metadata validation");
  try {
    await assert.rejects(prepareDocument(bytes, "docx"), /large|limit/i);
  } finally {
    JSZip.loadAsync = load;
  }
});
test("actual inflation is bounded even when local and central sizes both lie", async () => {
  const zip = new JSZip().file(
    "word/document.xml",
    "<r>" + "x".repeat(500000) + "</r>",
    { createFolders: false },
  );
  const bytes = await zip.generateAsync({
    type: "arraybuffer",
    compression: "DEFLATE",
  });
  const view = new DataView(bytes);
  // Read offsets before forging a lower declared expansion. Initial ratio is intentionally excessive.
  const raw = new Uint8Array(bytes);
  let central = -1;
  for (let p = 0; p < raw.length - 4; p++)
    if (view.getUint32(p, true) === 0x02014b50 && raw[p + 46] === 119) {
      central = p;
      break;
    }
  const local = view.getUint32(central + 42, true);
  view.setUint32(central + 24, 1000, true);
  view.setUint32(local + 22, 1000, true);
  await assert.rejects(prepareDocument(bytes, "docx"), /expan|size/i);
});
test("raster dimensions are bounded before DOM decoding", async () => {
  const png = new Uint8Array(24),
    view = new DataView(png.buffer);
  view.setUint32(0, 0x89504e47);
  view.setUint32(16, 100000);
  view.setUint32(20, 100000);
  for (const filename of ["word/media/bomb.png", "word/unexpected.dat"]) {
    const zip = await JSZip.loadAsync(await source("navigation.docx"));
    zip.file(filename, png);
    await assert.rejects(
      prepareDocument(await zip.generateAsync({ type: "arraybuffer" }), "docx"),
      /pixel/i,
    );
  }
});

test("Word leaves the worker as a transferable model, not an archive", async () => {
  const result = await prepareDocument(await source("navigation.docx"), "docx");
  assert.equal(typeof result.bytes, "undefined");
  assert.ok(result.word.documentPart.body.children.length > 0);
  assert.equal(result.headings.length, 3);
  assert.doesNotThrow(() => structuredClone(result));
});
test("PowerPoint leaves the worker as converted bounded slide HTML", async () => {
  const result = await prepareDocument(
    await source("project-review.pptx"),
    "pptx",
  );
  assert.equal(typeof result.bytes, "undefined");
  assert.equal(result.slides.length, 2);
  assert.ok(result.slides.every((slide) => slide.includes("slide")));
});

test("PPT image-reference amplification is bounded before conversion", async () => {
  const zip = await JSZip.loadAsync(await source("project-review.pptx"));
  zip.file(
    "ppt/slides/slide1.xml",
    '<p:sld xmlns:p="urn:p" xmlns:a="urn:a">' +
      "<a:blip/>".repeat(10000) +
      "</p:sld>",
  );
  const bytes = await zip.generateAsync({
    type: "arraybuffer",
    compression: "STORE",
  });
  assert.ok(bytes.byteLength < LIMITS.inputBytes);
  assert.ok(preflightZip(bytes).length < LIMITS.entries);
  await assert.rejects(prepareDocument(bytes, "pptx"), /reuse.*limit/i);
});
