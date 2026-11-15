/** Rehydrate bounded plain preview data, without importing ExcelJS on the UI thread. */
export function workbookViews(sheets) {
  return sheets.map((sheet) => ({
    ...sheet,
    _merges: Object.fromEntries(
      sheet.merges.map((model) => [`${model.top}:${model.left}`, { model }]),
    ),
    getColumn: (c) => sheet.columns[c - 1] ?? {},
    getRow: (r) => ({
      ...sheet.rows[r - 1],
      getCell: (c) => sheet.rows[r - 1].cells[c - 1],
    }),
    getCell: (r, c) => sheet.rows[r - 1].cells[c - 1],
  }));
}
