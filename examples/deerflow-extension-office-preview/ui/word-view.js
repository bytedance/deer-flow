import { resolvePartPath } from "./document-model.js";

/** Minimal resource/relationship facade for docx-preview's public renderDocument API. */
export function wordView(prepared) {
  const urls = new Map();
  let disposed = false;
  const resource = (part, id) => {
    if (disposed) return null;
    const rel = part?.rels?.find(
      (entry) => entry.id === id && entry.targetMode !== "External",
    );
    if (!rel) return null;
    const path = resolvePartPath(part.path, rel.target);
    if (urls.has(path)) return urls.get(path);
    const image = Object.hasOwn(prepared.images, path)
      ? prepared.images[path]
      : null;
    if (!image) return null;
    const type = image[0] === 0x89 ? "image/png" : "image/jpeg";
    const url = URL.createObjectURL(new Blob([image], { type }));
    urls.set(path, url);
    return url;
  };
  const word = prepared.word;
  return {
    document: {
      ...word,
      findPartByRelId(id, base = null) {
        const rel = (base?.rels ?? word.rels).find(
          (entry) => entry.id === id && entry.targetMode !== "External",
        );
        const path = rel ? resolvePartPath(base?.path ?? "", rel.target) : "";
        return Object.hasOwn(word.partsMap, path) ? word.partsMap[path] : null;
      },
      async loadDocumentImage(id, part) {
        return resource(part ?? word.documentPart, id);
      },
      async loadNumberingImage(id) {
        return resource(word.numberingPart, id);
      },
      async loadFont() {
        return null;
      },
      async loadAltChunk() {
        return null;
      },
    },
    dispose() {
      disposed = true;
      for (const url of urls.values()) URL.revokeObjectURL(url);
      urls.clear();
    },
  };
}
