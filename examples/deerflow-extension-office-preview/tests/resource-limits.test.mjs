import assert from "node:assert/strict";
import test from "node:test";
import JSZip from "jszip";
import { preflightZip, inspectXml, LIMITS } from "../ui/resource-limits.js";
import { prepareOffice } from "../ui/worker-client.js";

async function archive(name = "word/document.xml", value = "<document/>") {
  return new JSZip()
    .file(name, value)
    .generateAsync({ type: "arraybuffer", compression: "STORE" });
}

test("ZIP preflight accepts standard OOXML before any parser is loaded", async () => {
  const bytes = await archive();
  assert.ok(
    preflightZip(bytes).some((entry) => entry.name === "word/document.xml"),
  );
});

test("ZIP preflight rejects forged expansion, truncated directories and duplicate local records", async () => {
  const bytes = await archive();
  const view = new DataView(bytes);
  const entries = preflightZip(bytes);
  view.setUint32(entries[0].directoryOffset + 24, 101 * 1024 * 1024, true);
  assert.throws(() => preflightZip(bytes), /large|limit/i);
  assert.throws(() => preflightZip(bytes.slice(0, -1)), /ZIP|archive/i);
  const duplicate = await new JSZip()
    .file("a", "x")
    .file("b", "y")
    .generateAsync({ type: "arraybuffer" });
  const records = preflightZip(duplicate);
  new DataView(duplicate).setUint32(
    records[1].directoryOffset + 42,
    records[0].localOffset,
    true,
  );
  assert.throws(() => preflightZip(duplicate), /ZIP|archive|overlap/i);
});

test("ZIP preflight rejects ZIP64, encryption, unsupported compression and excessive ratios", async () => {
  for (const [field, value] of [
    [20, 0xffffffff],
    [8, 1],
    [10, 99],
    [24, 1000000],
  ]) {
    const bytes = await archive();
    const entry = preflightZip(bytes)[0];
    const view = new DataView(bytes);
    if (field === 8 || field === 10)
      view.setUint16(entry.directoryOffset + field, value, true);
    else view.setUint32(entry.directoryOffset + field, value, true);
    assert.throws(() => preflightZip(bytes), /ZIP|archive|limit|large|ratio/i);
  }
});

test("XML complexity rejects crafted documents well below original ZIP byte limits", () => {
  for (const kind of ["xlsx", "docx", "pptx"]) {
    assert.throws(
      () =>
        inspectXml(
          "<root>" + "<a/>".repeat(LIMITS.xmlElements + 1) + "</root>",
          kind,
        ),
      /complex|limit/i,
    );
    assert.throws(
      () => inspectXml("<a>".repeat(70) + "</a>".repeat(70), kind),
      /depth|complex|limit/i,
    );
    assert.throws(
      () => inspectXml('<!DOCTYPE x [<!ENTITY e "abc">]><x>&e;</x>', kind),
      /DTD|DOCTYPE/i,
    );
    assert.throws(() => inspectXml("<a></b>", kind));
  }
});

test("XML accepts real namespaces, styles and text while enforcing document-wide budgets", () => {
  const budget = { elements: 0, text: 0, units: 0 };
  inspectXml(
    '<w:document xmlns:w="urn:word"><w:p><w:r><w:t>Search target</w:t></w:r></w:p></w:document>',
    "docx",
    budget,
  );
  assert.ok(budget.elements > 0);
  assert.throws(
    () =>
      inspectXml(
        "<r>" + "<p/>".repeat(LIMITS.renderUnits + 1) + "</r>",
        "docx",
      ),
    /complex|limit/i,
  );
});

class FakeWorker {
  terminated = false;
  postMessage() {}
  terminate() {
    this.terminated = true;
  }
}
test("deadline terminates an unresponsive parser instead of merely rejecting its promise", async () => {
  const worker = new FakeWorker();
  await assert.rejects(
    prepareOffice(new ArrayBuffer(2), "xlsx", new AbortController().signal, {
      timeoutMs: 10,
      workerFactory: () => worker,
    }),
    /timed out/i,
  );
  assert.equal(worker.terminated, true);
});
test("cancellation terminates the worker and ignores a late result", async () => {
  const worker = new FakeWorker(),
    controller = new AbortController();
  const pending = prepareOffice(new ArrayBuffer(2), "docx", controller.signal, {
    workerFactory: () => worker,
  });
  const late = worker.onmessage;
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(worker.terminated, true);
  late?.({ data: { result: { stale: true } } });
});
test("worker failures terminate the parser and already-aborted requests never start it", async () => {
  const worker = new FakeWorker();
  const pending = prepareOffice(
    new ArrayBuffer(2),
    "pptx",
    new AbortController().signal,
    { workerFactory: () => worker },
  );
  worker.onerror({ preventDefault() {} });
  await assert.rejects(pending, /preview|worker/i);
  assert.equal(worker.terminated, true);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    prepareOffice(new ArrayBuffer(2), "pptx", controller.signal, {
      workerFactory: () => assert.fail("must not create worker"),
    }),
    { name: "AbortError" },
  );
});

test("rejects small XML that amplifies merge allocation, nested layout or recursive styles", () => {
  assert.throws(
    () => inspectXml('<r><mergeCell ref="A1:XFD1048576"/></r>', "xlsx"),
    /complex|limit/i,
  );
  assert.throws(
    () =>
      inspectXml(
        "<r>" + "<tbl>".repeat(5) + "</tbl>".repeat(5) + "</r>",
        "docx",
      ),
    /complex|limit/i,
  );
  assert.throws(
    () =>
      inspectXml(
        '<r><style styleId="a"><basedOn val="b"/></style><style styleId="b"><basedOn val="a"/></style></r>',
        "docx",
      ),
    /complex|limit/i,
  );
});

test("render budgets exclude unused style metadata while XML budgets still apply", () => {
  const budget = { elements: 0, text: 0, units: 0 };
  inspectXml("<r>" + "<n/>".repeat(21000) + "</r>", "docx", budget, false);
  inspectXml("<r><p>Visible</p></r>", "docx", budget);
  assert.equal(budget.renderElements, 2);
  assert.ok(budget.elements > 20000);
});

test("workbook merge budgets accumulate across parts and sparse coordinates are bounded", () => {
  const budget = { elements: 0, text: 0, units: 0 };
  inspectXml('<r><mergeCell ref="A1:CV600"/></r>', "xlsx", budget);
  assert.throws(
    () => inspectXml('<r><mergeCell ref="A1:CV600"/></r>', "xlsx", budget),
    /complex|limit/i,
  );
  assert.throws(
    () =>
      inspectXml('<r><row r="1048576"><c r="XFD1048576"/></row></r>', "xlsx"),
    /complex|limit/i,
  );
  assert.throws(
    () => inspectXml('<r><pgSz w="1000000" h="1000000"/></r>', "docx"),
    /complex|limit/i,
  );
});

test("worker phase messages never complete a pending conversion", async () => {
  const worker = new FakeWorker();
  let settled = false;
  const pending = prepareOffice(
    new ArrayBuffer(2),
    "docx",
    new AbortController().signal,
    { workerFactory: () => worker },
  ).then((result) => {
    settled = true;
    return result;
  });
  worker.onmessage({ data: { phase: "docx" } });
  await Promise.resolve();
  assert.equal(settled, false);
  worker.onmessage({ data: { result: { word: {} } } });
  assert.deepEqual(await pending, { word: {} });
  assert.equal(worker.terminated, true);
});

test("sparse PowerPoint chart indices cannot amplify small XML into giant arrays", () => {
  assert.throws(
    () =>
      inspectXml(
        '<c:root xmlns:c="urn:chart"><c:pt idx="4294967294"><c:v>1</c:v></c:pt></c:root>',
        "pptx",
      ),
    /complex|limit/i,
  );
});
