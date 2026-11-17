import { SaxesParser } from "saxes";

// Preview budgets, not Office format limits. Originals remain downloadable.
export const LIMITS = Object.freeze({
  inputBytes: 25 * 1024 * 1024,
  entries: 4000,
  expandedBytes: 100 * 1024 * 1024,
  entryBytes: 16 * 1024 * 1024,
  ratio: 200,
  xmlBytes: 2 * 1024 * 1024,
  xmlElements: 100000,
  xmlDepth: 64,
  renderElements: 20000,
  renderUnits: 2000,
  textCharacters: 2 * 1024 * 1024,
  slides: 50,
  sheets: 20,
  cells: 100000,
  imagePixels: 16 * 1024 * 1024,
  totalImagePixels: 32 * 1024 * 1024,
  preparedBytes: 32 * 1024 * 1024,
});

/** Read bounded central/local metadata before JSZip allocates its object graph. */
export function preflightZip(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength > LIMITS.inputBytes)
    throw new Error("Office archive exceeds preview size limit");
  const view = new DataView(buffer),
    length = buffer.byteLength;
  const u16 = (p) => view.getUint16(p, true);
  const u32 = (p) => view.getUint32(p, true);
  let end = -1;
  for (let p = length - 22; p >= Math.max(0, length - 65557); p--)
    if (u32(p) === 0x06054b50 && p + 22 + u16(p + 20) === length) {
      end = p;
      break;
    }
  if (end < 0) throw new Error("Invalid ZIP archive directory");
  const count = u16(end + 10),
    size = u32(end + 12),
    start = u32(end + 16);
  if (
    u16(end + 4) ||
    u16(end + 6) ||
    u16(end + 8) !== count ||
    count === 0xffff ||
    size === 0xffffffff ||
    start === 0xffffffff
  )
    throw new Error("Unsupported split or ZIP64 archive");
  if (count > LIMITS.entries)
    throw new Error("ZIP archive member limit exceeded");
  if (start + size !== end) throw new Error("Invalid ZIP archive bounds");
  const records = [],
    names = new Set(),
    ranges = [];
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let cursor = start,
    expanded = 0;
  for (let i = 0; i < count; i++) {
    if (cursor + 46 > end || u32(cursor) !== 0x02014b50)
      throw new Error("Invalid ZIP archive entry");
    const flags = u16(cursor + 8),
      method = u16(cursor + 10);
    const compressed = u32(cursor + 20),
      uncompressed = u32(cursor + 24);
    const nameSize = u16(cursor + 28),
      extraSize = u16(cursor + 30);
    const next = cursor + 46 + nameSize + extraSize + u16(cursor + 32);
    const local = u32(cursor + 42);
    if (
      next > end ||
      local + 30 > start ||
      u32(local) !== 0x04034b50 ||
      u16(cursor + 34) ||
      flags & ~0x080e ||
      flags & 1 ||
      ![0, 8].includes(method) ||
      compressed === 0xffffffff ||
      uncompressed === 0xffffffff
    )
      throw new Error("Unsupported or invalid ZIP archive entry");
    expanded += uncompressed;
    if (uncompressed > LIMITS.entryBytes || expanded > LIMITS.expandedBytes)
      throw new Error("Expanded Office archive too large");
    if (uncompressed > Math.max(1, compressed) * LIMITS.ratio)
      throw new Error("ZIP archive compression ratio limit exceeded");
    const name = decoder.decode(new Uint8Array(buffer, cursor + 46, nameSize));
    if (
      !name ||
      name.length > 1024 ||
      name.split("/").length > 32 ||
      names.has(name) ||
      name.includes("\\") ||
      name.includes("\0") ||
      name.startsWith("/") ||
      name.split("/").some((p) => p === ".." || p === ".")
    )
      throw new Error("Invalid or duplicate ZIP archive name");
    names.add(name);
    for (
      let p = cursor + 46 + nameSize;
      p < cursor + 46 + nameSize + extraSize;
    ) {
      if (p + 4 > next || u16(p) === 1)
        throw new Error("Unsupported ZIP64 archive");
      const extraEnd = p + 4 + u16(p + 2);
      if (extraEnd > cursor + 46 + nameSize + extraSize)
        throw new Error("Invalid ZIP archive extra data");
      p = extraEnd;
    }
    const data = local + 30 + u16(local + 26) + u16(local + 28);
    if (
      u16(local + 6) !== flags ||
      u16(local + 8) !== method ||
      data + compressed > start ||
      decoder.decode(new Uint8Array(buffer, local + 30, u16(local + 26))) !==
        name ||
      (!(flags & 8) &&
        (u32(local + 18) !== compressed || u32(local + 22) !== uncompressed))
    )
      throw new Error("Mismatched ZIP archive local entry");
    ranges.push([local, data + compressed]);
    records.push({
      name,
      compressed,
      uncompressed,
      directoryOffset: cursor,
      localOffset: local,
    });
    cursor = next;
  }
  ranges.sort((a, b) => a[0] - b[0]);
  if (
    cursor !== end ||
    ranges.some((range, i) => i && range[0] < ranges[i - 1][1])
  )
    throw new Error("Overlapping or inconsistent ZIP archive entries");
  return records;
}

/** Streaming XML validation runs in the terminable worker, never the UI thread. */
export function inspectXml(
  xml,
  kind,
  budget = { elements: 0, text: 0, units: 0 },
  renderable = true,
) {
  const parser = new SaxesParser({ xmlns: true });
  let depth = 0,
    tables = 0,
    styleId;
  const styleBases = new Map();
  const fail = () => {
    throw new Error("Office XML complexity limit exceeded");
  };
  parser.on("doctype", () => {
    throw new Error("Office XML DOCTYPE is unsupported");
  });
  parser.on("opentag", (tag) => {
    depth++;
    budget.elements++;
    if (["blip", "imagedata"].includes(tag.local))
      budget.imageReferences = (budget.imageReferences ?? 0) + 1;
    if (renderable) budget.renderElements = (budget.renderElements ?? 0) + 1;
    if (
      renderable &&
      ["p", "tr", "br", "sectPr", "sp", "pic", "graphicFrame"].includes(
        tag.local,
      )
    )
      budget.units++;
    if (tag.local === "tbl" && ++tables > 4) fail();
    if (
      depth > LIMITS.xmlDepth ||
      budget.elements > LIMITS.xmlElements ||
      Object.keys(tag.attributes).length > 64 ||
      (kind !== "xlsx" &&
        ((budget.renderElements ?? 0) > LIMITS.renderElements ||
          budget.units > LIMITS.renderUnits))
    )
      fail();
    // Huge table spans/column counts can amplify small XML into large DOM trees.
    for (const attr of Object.values(tag.attributes)) {
      if (attr.value.length > 8192) fail();
      if (
        kind === "pptx" &&
        ((attr.local === "idx" && Number(attr.value) > 10000) ||
          (tag.local === "ptCount" &&
            attr.local === "val" &&
            Number(attr.value) > 10000))
      )
        fail();
      if (
        kind === "xlsx" &&
        tag.local === "row" &&
        attr.local === "r" &&
        Number(attr.value) > 10000
      )
        fail();
      if (kind === "xlsx" && tag.local === "c" && attr.local === "r") {
        const coordinate = /^([A-Z]{1,3})([1-9]\d*)$/.exec(attr.value);
        if (
          !coordinate ||
          Number(coordinate[2]) > 10000 ||
          [...coordinate[1]].reduce(
            (n, c) => n * 26 + c.charCodeAt(0) - 64,
            0,
          ) > 1000
        )
          fail();
      }
      if (
        ["cx", "cy"].includes(attr.local) &&
        Math.abs(Number(attr.value)) > 40000000
      )
        fail();
      if (
        tag.local === "pgSz" &&
        ["w", "h"].includes(attr.local) &&
        Number(attr.value) > 31680
      )
        fail();
      if (
        ["sz", "szCs"].includes(tag.local) &&
        attr.local === "val" &&
        Number(attr.value) > 1024
      )
        fail();
      if (
        ["rPr", "defRPr", "endParaRPr"].includes(tag.local) &&
        attr.local === "sz" &&
        Number(attr.value) > 51200
      )
        fail();
      if (
        ["gridSpan", "vMerge"].includes(tag.local) &&
        attr.local === "val" &&
        Number(attr.value) > 100
      )
        fail();
      if (
        kind === "xlsx" &&
        tag.local === "mergeCell" &&
        attr.local === "ref"
      ) {
        const range = /^([A-Z]{1,3})([1-9]\d*):([A-Z]{1,3})([1-9]\d*)$/.exec(
          attr.value,
        );
        if (!range) fail();
        const column = (value) =>
          [...value].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
        const width = column(range[3]) - column(range[1]) + 1;
        const height = Number(range[4]) - Number(range[2]) + 1;
        budget.mergeCells = (budget.mergeCells ?? 0) + width * height;
        if (width < 1 || height < 1 || budget.mergeCells > LIMITS.cells) fail();
      }
      if (tag.local === "style" && attr.local === "styleId")
        styleId = attr.value;
      if (tag.local === "basedOn" && attr.local === "val" && styleId)
        styleBases.set(styleId, attr.value);
    }
  });
  parser.on("closetag", (tag) => {
    depth--;
    if (tag.local === "tbl") tables--;
    if (tag.local === "style") styleId = undefined;
  });
  const text = (value) => {
    budget.text += value.length;
    if (budget.text > LIMITS.textCharacters) fail();
  };
  parser.on("text", text);
  parser.on("cdata", text);
  // Bound individual parser.write calls as well as cumulative document size.
  for (let offset = 0; offset < xml.length; offset += 16384)
    parser.write(xml.slice(offset, offset + 16384));
  parser.close();
  // Word's inherited styles are recursively resolved by DOM renderers.
  const complete = new Set();
  for (const id of styleBases.keys()) {
    const path = new Set();
    let current = id;
    while (current && !complete.has(current)) {
      if (path.has(current) || path.size >= 64) fail();
      path.add(current);
      current = styleBases.get(current);
    }
    for (const entry of path) complete.add(entry);
  }
  return budget;
}

/** Check decoded raster dimensions before any browser image decoder sees them. */
export function imagePixels(data) {
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  if (data.length >= 24 && view.getUint32(0) === 0x89504e47) {
    for (let offset = 8; offset + 12 <= data.length; ) {
      const length = view.getUint32(offset);
      if (view.getUint32(offset + 4) === 0x6163544c)
        throw new Error("Animated Office preview images are unsupported");
      if (length > data.length - offset - 12) break;
      offset += length + 12;
    }
    return view.getUint32(16) * view.getUint32(20);
  }
  if (data.length >= 4 && view.getUint16(0) === 0xffd8) {
    for (let p = 2; p + 4 <= data.length; ) {
      if (data[p++] !== 0xff) break;
      while (data[p] === 0xff) p++;
      const marker = data[p++];
      if (marker === 0xd9 || marker === 0xda) break;
      if (marker === 1 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      const length = view.getUint16(p);
      if (length < 2 || p + length > data.length) break;
      if ([0xc0, 0xc1, 0xc2].includes(marker) && length >= 7)
        return view.getUint16(p + 3) * view.getUint16(p + 5);
      p += length;
    }
  }
  throw new Error("Unsupported Office preview image format");
}
