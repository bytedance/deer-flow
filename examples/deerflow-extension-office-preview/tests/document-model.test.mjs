import assert from "node:assert/strict";
import test from "node:test";
import { WorkerXmlParser } from "../ui/worker-xml.js";
import { checkModelBudget, transferBuffers } from "../ui/document-model.js";
import { wordView } from "../ui/word-view.js";

test("worker XML preserves namespace, descendant and escaped-prefix selectors", () => {
  const doc = new WorkerXmlParser().parseFromString(
    '<p:root xmlns:p="urn:p" xmlns:a="urn:a"><p:spPr/><a:lstStyle><a:defRPr><a:solidFill/></a:defRPr></a:lstStyle></p:root>',
    "application/xml",
  );
  assert.equal(doc.querySelector("p\\:spPr, spPr").namespaceURI, "urn:p");
  assert.equal(doc.querySelector("*|lstStyle *|defRPr").localName, "defRPr");
  assert.equal(doc.querySelectorAll("*|solidFill").length, 1);
  assert.equal(doc.firstElementChild, doc.documentElement);
  assert.throws(() => doc.querySelector("div > span"), /unsupported/i);
});
test("parser output budgets reject amplified arrays and strings before transfer", () => {
  assert.throws(() => checkModelBudget({ nodes: new Array(100001) }), /limit/i);
  assert.throws(
    () => checkModelBudget({ html: "x".repeat(17 * 1024 * 1024) }),
    /limit/i,
  );
  const bytes = new Uint8Array(10);
  const model = { bytes, again: bytes.subarray(1) };
  model.self = model;
  assert.deepEqual(transferBuffers(model), [bytes.buffer]);
  assert.doesNotThrow(() => checkModelBudget(model));
});
test("Word resource facade resolves headers and images, deduplicates URLs and revokes on disposal", async () => {
  const image = new Uint8Array([0x89, 0x50]);
  const rel = { id: "image", type: "image", target: "media/image.png" };
  const body = { path: "word/document.xml", rels: [rel] };
  const header = {
    path: "word/header.xml",
    rels: [rel],
    rootElement: { type: "header" },
  };
  body.rels.push(
    { id: "header", target: "header.xml" },
    {
      id: "external",
      target: "https://invalid.test/image.png",
      targetMode: "External",
    },
  );
  const view = wordView({
    word: {
      documentPart: body,
      partsMap: { "word/header.xml": header },
      rels: [],
    },
    images: { "word/media/image.png": image },
  });
  assert.equal(view.document.findPartByRelId("header", body), header);
  const first = await view.document.loadDocumentImage("image");
  assert.ok(first.startsWith("blob:"));
  assert.equal(await view.document.loadDocumentImage("image", header), first);
  assert.equal(await view.document.loadDocumentImage("external"), null);
  assert.equal((await fetch(first)).status, 200);
  view.dispose();
  view.dispose();
  assert.equal(await view.document.loadDocumentImage("image"), null);
  await assert.rejects(fetch(first));
});
