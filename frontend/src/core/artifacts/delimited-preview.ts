import Papa from "papaparse";

import {
  DELIMITED_COLUMN_LIMIT,
  DELIMITED_RECORD_LIMIT,
  type DelimitedPreviewInput,
  type DelimitedPreviewResult,
} from "./delimited-preview-types";

export type { DelimitedPreviewResult } from "./delimited-preview-types";

/** Find the first record separator outside quoted fields, even in a prefix. */
function detectRecordNewline(content: string, delimiter: string) {
  let quoted = false;
  let fieldStart = true;
  for (let index = 0; index < content.length; index++) {
    const char = content[index];
    if (quoted) {
      if (char === '"') {
        if (content[index + 1] === '"') index++;
        else quoted = false;
      }
      continue;
    }
    if (char === '"' && fieldStart) quoted = true;
    else if (char === "\r") return content[index + 1] === "\n" ? "\r\n" : "\r";
    else if (char === "\n") return "\n";
    fieldStart = char === delimiter;
  }
  // No complete record separator: Papa still validates quotes and the caller
  // drops an unfinished terminal record when the input is truncated.
  return "\n";
}

/** Parse only the bounded, already-loaded sample. Runs exclusively in a Worker. */
export function parseDelimitedPreview({
  content,
  delimiter,
  truncated,
}: DelimitedPreviewInput): DelimitedPreviewResult {
  // Papa strips BOM too; strip here so cursor and length use the same coordinates.
  const input = content.startsWith("\uFEFF") ? content.slice(1) : content;
  const result: DelimitedPreviewResult = {
    rows: [],
    columnCount: 0,
    limited: truncated,
    unevenRows: false,
  };
  let cursor = 0;
  let firstWidth: number | undefined;
  Papa.parse<string[]>(input, {
    delimiter,
    // Papa's auto-detection can count CRs inside an unfinished quoted field.
    newline: detectRecordNewline(input, delimiter),
    header: false,
    dynamicTyping: false,
    skipEmptyLines: false,
    worker: false,
    download: false,
    step(record, parser) {
      const nextCursor = record.meta.cursor;
      const terminal = nextCursor === input.length;
      const incompleteQuotes =
        record.errors.length > 0 &&
        record.errors.every((error) => error.code === "MissingQuotes");
      if (record.errors.length > 0) {
        if (truncated && terminal && incompleteQuotes) {
          parser.abort();
          return;
        }
        throw new Error("Invalid delimited file syntax");
      }
      // Papa emits an EOF empty row after a trailing record separator. Its cursor
      // does not advance; actual blank records consume their separator.
      if (nextCursor === cursor) return;
      cursor = nextCursor;
      if (truncated && terminal && !input.endsWith(record.meta.linebreak))
        return;
      const width = record.data.length;
      firstWidth ??= width;
      result.unevenRows ||= width !== firstWidth;
      result.columnCount = Math.max(result.columnCount, width);
      result.rows.push(record.data.slice(0, DELIMITED_COLUMN_LIMIT));
      if (result.rows.length === DELIMITED_RECORD_LIMIT) {
        result.limited ||= cursor < input.length;
        parser.abort();
      }
    },
  });
  return result;
}
