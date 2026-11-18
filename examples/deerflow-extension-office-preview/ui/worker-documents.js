import { WorkerXmlParser, installWorkerXml } from "./worker-xml.js";
import { prepareWordOutline } from "./search.js";
import { resolvePartPath, checkModelBudget } from "./document-model.js";

/** Strip parser/ZIP instances and parent links; the renderer reconstructs parents. */
function plainModel(value, seen = new Map()) {
  if (!value || typeof value !== "object") return value;
  if (seen.has(value)) return seen.get(value);
  const result = Array.isArray(value) ? [] : Object.create(null);
  seen.set(value, result);
  for (const [key, child] of Object.entries(value)) {
    if (key.startsWith("_") || key === "parent") continue;
    if (typeof child === "function" || child?.nodeType)
      throw new Error("Unsupported Word model value");
    result[key] = plainModel(child, seen);
  }
  return result;
}

export async function prepareWord(zip) {
  installWorkerXml();
  const headings = await prepareWordOutline(zip);
  const { parseAsync } = await import("docx-preview");
  const document = await parseAsync(
    await zip.generateAsync({ type: "arraybuffer", compression: "STORE" }),
    {
      ignoreFonts: true,
      renderAltChunks: false,
      useBase64URL: false,
    },
  );
  const selected = { rels: document.rels, partsMap: document.partsMap };
  for (const [name, part] of Object.entries(document))
    if (name.endsWith("Part")) selected[name] = part;
  const word = plainModel(selected);
  const images = {};
  for (const part of document.parts)
    for (const rel of part.rels ?? []) {
      if (!rel.type.endsWith("/image") || rel.targetMode === "External")
        continue;
      const path = resolvePartPath(part.path, rel.target);
      const entry = zip.file(path);
      if (entry && !Object.hasOwn(images, path))
        images[path] = await entry.async("uint8array");
    }
  const result = { kind: "docx", word, headings, images };
  checkModelBudget(result);
  return result;
}

export async function preparePresentation(zip) {
  installWorkerXml();
  // The converter omits paragraph defaults. Normalize only the worker's private ZIP.
  for (const entry of Object.values(zip.files).filter((entry) =>
    /^ppt\/slides\/slide\d+\.xml$/.test(entry.name),
  )) {
    const xml = new WorkerXmlParser().parseFromString(
      await entry.async("string"),
      "application/xml",
    );
    let changed = false;
    for (const paragraph of xml.getElementsByTagNameNS("*", "p")) {
      const defaults = [...paragraph.children]
        .find((node) => node.localName === "pPr")
        ?.getElementsByTagNameNS("*", "defRPr")[0];
      if (!defaults) continue;
      for (const run of [...paragraph.children].filter(
        (node) => node.localName === "r",
      )) {
        let properties = [...run.children].find(
          (node) => node.localName === "rPr",
        );
        if (!properties) {
          properties = xml.createElementNS(defaults.namespaceURI, "a:rPr");
          run.insertBefore(properties, run.firstChild);
        }
        for (const attr of defaults.attributes)
          if (!properties.hasAttribute(attr.name))
            properties.setAttribute(attr.name, attr.value);
        for (const child of defaults.children)
          if (
            ![...properties.children].some(
              (node) => node.localName === child.localName,
            )
          )
            properties.appendChild(child.cloneNode(true));
        changed = true;
      }
    }
    if (changed)
      zip.file(entry.name, new XMLSerializer().serializeToString(xml), {
        createFolders: false,
      });
  }
  const { pptxToHtml } = await import("@jvmr/pptx-to-html");
  const slides = await pptxToHtml(
    await zip.generateAsync({ type: "arraybuffer", compression: "STORE" }),
    {
      width: 960,
      height: 540,
      scaleToFit: true,
      domParserFactory: () => new WorkerXmlParser(),
    },
  );
  if (slides.some((slide) => slide.length > 512 * 1024))
    throw new Error("Office slide HTML limit exceeded");
  const result = { kind: "pptx", slides };
  checkModelBudget(result);
  return result;
}
