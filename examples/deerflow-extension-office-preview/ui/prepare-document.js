import JSZip from "jszip";
import {
  LIMITS,
  preflightZip,
  inspectXml,
  imagePixels,
} from "./resource-limits.js";

function inflateEntry(entry, record, budget) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let length = 0,
      stopped = false;
    const stream = entry.internalStream("uint8array");
    stream.on("data", (chunk) => {
      if (stopped) return;
      length += chunk.length;
      budget.bytes += chunk.length;
      if (
        length > record.uncompressed ||
        length > LIMITS.entryBytes ||
        budget.bytes > LIMITS.expandedBytes
      ) {
        stopped = true;
        stream.pause();
        reject(new Error("Actual Office expansion exceeds preview limit"));
      } else chunks.push(chunk);
    });
    stream.on("error", reject);
    stream.on("end", () => {
      if (stopped) return;
      if (length !== record.uncompressed) {
        reject(new Error("Invalid Office archive expanded size"));
        return;
      }
      const result = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        result.set(chunk, offset);
        offset += chunk.length;
      }
      resolve(result);
    });
    stream.resume();
  });
}

/** Called only by a dedicated worker; exported for offline adversarial tests. */
export async function prepareDocument(bytes, kind, onPhase = () => {}) {
  if (!["xlsx", "docx", "pptx"].includes(kind))
    throw new Error("Unsupported Office preview format");
  const records = preflightZip(bytes);
  const xmlRecords = records.filter((record) =>
    /\.(xml|rels|vml)$/i.test(record.name),
  );
  if (xmlRecords.some((record) => record.uncompressed > LIMITS.xmlBytes))
    throw new Error("Office XML size limit exceeded");
  if (
    records.filter((record) => /^ppt\/slides\/slide\d+\.xml$/.test(record.name))
      .length > LIMITS.slides
  )
    throw new Error("Office slide limit exceeded");
  const zip = await JSZip.loadAsync(bytes, { createFolders: false });
  if (
    Object.keys(zip.files).length !== records.length ||
    records.some((record) => !Object.hasOwn(zip.files, record.name))
  )
    throw new Error("Inconsistent Office ZIP names");
  const budget = { bytes: 0, pixels: 0, elements: 0, text: 0, units: 0 };
  // Serial inflation avoids allocating every uncompressed member concurrently.
  for (const record of records) {
    if (record.name.endsWith("/")) continue;
    const data = await inflateEntry(zip.files[record.name], record, budget);
    const isXml = /\.(xml|rels|vml)$/i.test(record.name);
    if (isXml) {
      const xml = new TextDecoder("utf-8", { fatal: true }).decode(data);
      // docx-preview ignores this alternate style tree. Still validate it under
      // worker XML budgets, without charging it twice to the DOM layout budget.
      inspectXml(
        xml,
        kind,
        budget,
        record.name !== "word/stylesWithEffects.xml",
      );
    }
    if (!isXml) {
      // Font/object parts cannot be used to smuggle an unchecked image to the UI.
      if (
        /\/(embeddings|printerSettings)\//i.test(record.name) ||
        /\.(odttf|ttf|otf|woff2?)$/i.test(record.name)
      ) {
        zip.remove(record.name);
        continue;
      }
      if (kind !== "xlsx") {
        const pixels = imagePixels(data);
        budget.pixelsBytes = (budget.pixelsBytes ?? 0) + data.byteLength;
        budget.pixels += pixels;
        if (
          !pixels ||
          pixels > LIMITS.imagePixels ||
          budget.pixels > LIMITS.totalImagePixels
        )
          throw new Error("Office image pixel limit exceeded");
      }
    }
    // Cache validated uncompressed bytes; later parsers cannot inflate unchecked data.
    zip.file(record.name, data, { createFolders: false });
  }
  onPhase(kind);
  if (kind === "xlsx") return { kind, sheets: await prepareWorkbook(zip) };
  if (budget.bytes > LIMITS.preparedBytes)
    throw new Error("Office render size limit exceeded");
  const slides = records.filter((record) =>
    /^ppt\/slides\/slide\d+\.xml$/.test(record.name),
  ).length;
  if (
    kind === "pptx" &&
    ((budget.pixelsBytes ?? 0) *
      Math.max(1, slides) *
      Math.max(1, budget.imageReferences ?? 0) *
      4) /
      3 >
      LIMITS.preparedBytes
  )
    throw new Error("Office image reuse size limit exceeded");
  const { prepareWord, preparePresentation } =
    await import("./worker-documents.js");
  return kind === "docx" ? prepareWord(zip) : preparePresentation(zip);
}

async function prepareWorkbook(zip) {
  const { default: ExcelJS } = await import("exceljs");
  // Cell-only preview: discard drawing/media parts in our copy, keeping originals intact.
  zip.remove("xl/drawings");
  zip.remove("xl/media");
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(
    await zip.generateAsync({ type: "arraybuffer", compression: "STORE" }),
    {
      ignoreNodes: ["drawing", "picture", "extLst", "tableParts"],
    },
  );
  const sheets = workbook.worksheets.filter(
    (sheet) => sheet.state === "visible",
  );
  if (sheets.length > LIMITS.sheets)
    throw new Error("Office worksheet limit exceeded");
  let cells = 0,
    characters = 0;
  const color = (argb) =>
    /^[A-Fa-f0-9]{8}$/.test(argb ?? "") ? argb : undefined;
  return sheets.map((sheet) => {
    const rows = Math.min(sheet.rowCount, 500),
      cols = Math.min(sheet.columnCount, 50);
    cells += rows * cols;
    if (cells > LIMITS.cells)
      throw new Error("Office preview cell limit exceeded");
    return {
      id: sheet.id,
      name: sheet.name,
      rowCount: sheet.rowCount,
      columnCount: sheet.columnCount,
      columns: Array.from({ length: cols }, (_, index) => {
        const column = sheet.getColumn(index + 1);
        return { hidden: !!column.hidden, width: column.width };
      }),
      merges: Object.values(sheet._merges).map((merge) => merge.model),
      rows: Array.from({ length: rows }, (_, index) => {
        const row = sheet.getRow(index + 1);
        return {
          hidden: !!row.hidden,
          cells: Array.from({ length: cols }, (_, c) => {
            const cell = row.getCell(c + 1),
              text = cell.text,
              formula = cell.formula;
            characters += text.length + (formula?.length ?? 0);
            if (
              characters > LIMITS.textCharacters ||
              text.length > 8192 ||
              (formula?.length ?? 0) > 8192
            )
              throw new Error("Office preview cell text limit exceeded");
            return {
              address: cell.address,
              text,
              formula,
              isMerged: cell.isMerged,
              master: { address: cell.master.address },
              font: {
                bold: !!cell.font?.bold,
                italic: !!cell.font?.italic,
                color: { argb: color(cell.font?.color?.argb) },
              },
              fill: { fgColor: { argb: color(cell.fill?.fgColor?.argb) } },
              alignment: {
                horizontal: ["left", "center", "right"].includes(
                  cell.alignment?.horizontal,
                )
                  ? cell.alignment.horizontal
                  : undefined,
              },
            };
          }),
        };
      }),
    };
  });
}
