# Legacy XLS fixture

`workbook.xls` is a real Excel 97-2003 BIFF workbook in an OLE container,
created locally with xlwt 1.3.0 (test fixture generation only; not a runtime dependency).
It contains no downloaded or personal data.

- `owner's sales`: headers amount/date/note/active; rows 7/2026-01-02/first/true and 3/2026-01-03/blank/false. Dates use YYYY-MM-DD number formatting.
- `Mixed`: value column with numeric 1, text, and a blank retained by a value in the adjacent column.
- `Empty`: no cells.

The regression checks the OLE magic bytes, then reads this fixture through the
production XLS loader and a real DuckDB connection. xlwt is not required to run tests.

To regenerate: install `xlwt==1.3.0` in a temporary environment and run
`python generate_fixture.py` from this directory.

`literal-text.xls` contains a single `Identifiers` sheet with text cells:
`NA`/`00123`, `NULL`/`00456`, and `N/A`/`00789`. These are literal strings,
not missing values or numeric IDs. The same generator produces both files.

`sparse-mixed.xls.gz` is a gzip-compressed real BIFF workbook with one `Mixed`
sheet, header `value`, and 10001 data rows: numeric 1 everywhere except zero-based
row 1001 (the 1002nd data row), which contains the string `text`. That text lies
outside DuckDB's default dataframe sampling positions and exposes incomplete
mixed-column inference. Tests decompress it before calling the production loader.
The same generator produces this fixture with deterministic gzip metadata.

`mixed-types.xls` contains a `MixedTypes` sheet with boolean/integer,
date/integer and boolean/decimal columns alongside a compatible numeric
`amount` column. The third row has only an amount so the other cells are null.
A separate `Control` sheet previously masked the missing mixed sheet by loading
successfully. The regression queries the mixed rows in both the first load and
a cache hit from a fresh process.
