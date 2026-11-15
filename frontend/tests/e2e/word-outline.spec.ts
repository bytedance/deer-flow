import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  mockOfficePreview,
  officeFixtures,
  officePackage,
} from "./utils/office-preview";

// Use the browser's XML DOM: happy-dom does not implement OOXML namespaces.
test("allocates unique Word outline bookmarks without rescanning existing names", async ({
  page,
}) => {
  await page.route("http://office-preview.test/**", async (route) => {
    const filename = new URL(route.request().url()).pathname.slice(1);
    if (!filename)
      return route.fulfill({
        contentType: "text/html",
        body: "<html><body></body></html>",
      });
    if (!["search.js", "identifiers.js"].includes(filename))
      return route.abort();
    return route.fulfill({
      contentType: "text/javascript",
      body: await readFile(
        path.resolve(
          "../examples/deerflow-extension-office-preview/ui",
          filename,
        ),
      ),
    });
  });
  await page.goto("http://office-preview.test/");
  const result = await page.evaluate(async () => {
    const modulePath = "/search.js";
    const { prepareWordOutline } = await import(modulePath);
    const namespace =
      "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    const count = 2000;
    const existingNames = Array.from(
      { length: count },
      (_, index) => `office-${index}-0`,
    );
    existingNames.push("office-0", "office-1");
    const existingIds = existingNames.map((_, index) => String(100000 + index));
    let document = `<w:document xmlns:w="${namespace}"><w:body>${existingNames.map((name, index) => `<w:bookmarkStart w:name="${name}" w:id="${existingIds[index]}"/><w:bookmarkEnd w:id="${existingIds[index]}"/>`).join("")}
      <w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>Heading</w:t></w:r></w:p>
      <w:p><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>Section</w:t></w:r></w:p>
    </w:body></w:document>`;
    const zip = {
      file: (filename: string, value?: string) => {
        if (filename !== "word/document.xml") return null;
        if (value !== undefined) document = value;
        return { async: async () => document };
      },
    };
    // eslint-disable-next-line @typescript-eslint/unbound-method -- Called with explicit receivers and restored below.
    const startsWith = String.prototype.startsWith;
    let prefixProbes = 0;
    String.prototype.startsWith = function (prefix, position) {
      if (startsWith.call(prefix, "office-")) prefixProbes++;
      return startsWith.call(this, prefix, position);
    };
    let outline;
    try {
      outline = await prepareWordOutline(zip);
    } finally {
      String.prototype.startsWith = startsWith;
    }
    const xml = new DOMParser().parseFromString(document, "application/xml");
    const starts = [...xml.getElementsByTagNameNS(namespace, "bookmarkStart")];
    const names = starts.map((node) => node.getAttributeNS(namespace, "name"));
    const ids = starts.map((node) => node.getAttributeNS(namespace, "id"));
    const ends = [...xml.getElementsByTagNameNS(namespace, "bookmarkEnd")].map(
      (node) => node.getAttributeNS(namespace, "id"),
    );
    return {
      outline,
      names,
      ids,
      ends,
      existingNames,
      existingIds,
      prefixProbes,
    };
  });
  expect(new Set(result.names).size).toBe(result.names.length);
  expect(new Set(result.ids).size).toBe(result.ids.length);
  expect(result.names.slice(0, result.existingNames.length)).toEqual(
    result.existingNames,
  );
  expect(result.ids.slice(0, result.existingIds.length)).toEqual(
    result.existingIds,
  );
  expect(result.outline.map((entry: { title: string }) => entry.title)).toEqual(
    ["Heading", "Section"],
  );
  expect(result.outline.map((entry: { id: string }) => entry.id)).toEqual(
    result.names.slice(result.existingNames.length),
  );
  expect(result.ends).toEqual(result.ids);
  // Deterministic work bound; no timing threshold that varies between machines.
  expect(result.prefixProbes).toBeLessThan(result.existingNames.length * 2);
});

test("packaged Word renderer searches and navigates outlines on a real insecure HTTP origin", async ({
  page,
}) => {
  const manifest = JSON.parse(
    await readFile(path.join(officePackage, "ui_manifest.json"), "utf8"),
  ) as { entry: string };
  await mockOfficePreview(page);
  await page.route("http://office-preview.test/", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<html><body style="height:900px"><div id="preview" style="height:100%"></div></body></html>',
    }),
  );
  await page.route("http://office-preview.test/document.docx", async (route) =>
    route.fulfill({
      body: await readFile(path.join(officeFixtures, "navigation.docx")),
    }),
  );
  await page.goto("http://office-preview.test/");
  const secureContext = await page.evaluate(async (entry) => {
    const { default: contribution } = await import(
      `/api/plugins/office-preview/assets/${"a".repeat(64)}/${entry}`
    );
    const bytes = await (await fetch("/document.docx")).arrayBuffer();
    const root = document.getElementById("preview")!;
    contribution.artifactPreviews[0].mount(root, {
      locale: "en-US",
      filename: "navigation.docx",
      signal: new AbortController().signal,
      readFile: async () => bytes,
      onError: () => {
        root.textContent = "Preview failed";
      },
    });
    return window.isSecureContext;
  }, manifest.entry);
  expect(secureContext).toBe(false);
  const panel = page.locator("#preview");
  await expect(panel.locator("section.docx")).toHaveCount(3);
  const outline = panel.getByRole("navigation", { name: "Document outline" });
  await expect(outline.getByRole("button")).toHaveCount(3);
  await outline
    .getByRole("button", { name: "Final review page", exact: true })
    .click();
  await expect(panel.locator(".tabs")).toContainText("3 / 3");
  await panel
    .getByRole("searchbox", { name: "Find in file", exact: true })
    .fill("Search target");
  await expect(
    panel.getByRole("status", { name: "Search matches" }),
  ).toHaveText("1 / 3");
});
