# Data-analysis source and SQL correctness

`analyze.py` allocates lookup aliases and SQL table names together. Neither may
shadow an existing alias or SQL name (case-insensitively). Both CSV files and Excel
sheets use this allocator; reserve a name only after CREATE TABLE succeeds.

Cache identity includes input order, filesystem-encoded basenames, per-file content
digests, and a namespace version. Directory relocation alone does not change a
readable input's identity. Bump the namespace if table-mapping semantics change.

Cache publication uses `open_analysis_cache()`: build in a private UUID directory
under .data-analysis-cache/generations-v1/, close the DuckDB writer, reopen
read-only, then atomically replace one manifest containing its generation and map.
Never publish metadata while an import writer still owns the database. Validate
the manifest, allocator invariants and physical main-schema tables before reuse;
invalid entries rebuild. Flat legacy caches are ignored, not migrated or deleted.
Remove private builds if manifest preparation fails or an unsuccessful
replacement leaves its unique temporary source in place. Retain a generation
when publication may have happened because another process may be reading it.
Concurrent cold builders can repeat work but never share a writable database.
Stop analyses before manual cache cleanup. There is no automatic garbage
collection or power-loss durability guarantee.
Keep real-DuckDB process-barrier and failure-cleanup regressions in
tests/skills/test_data_analysis_cache_lifecycle.py. Use production CSV loading
to avoid optional spatial setup. The reader at the publication barrier must
reuse the published generation without loading the source again.

Regressions live under the repository's root tests directory. They use
real DuckDB. Excel and CLI integration additionally run with an already installed
official spatial extension via `DEERFLOW_TEST_SPATIAL_DIRECTORY`; default tests
never download that extension. Keep table lookup and persisted-cache checks tied
to distinct source values, rather than only inspecting generated names.

Bind file paths and Excel sheet names as SQL values. Quote generated table and
column identifiers by doubling embedded double quotes. Never rewrite user SQL
with regular expressions: unique original names resolve through temporary views
over canonical tables in the main schema, including on read-only cache hits.
Keep these views connection-local and preserve normal CTE shadowing.

Prepare DuckDB and openpyxl explicitly in the execution environment. Missing
packages produce setup instructions without launching installers; keep those
import-failure regressions offline in the root skill tests.

Export paths resolve relative to the caller's working directory, including bare
filenames. Keep real DuckDB regressions for CSV/JSON/Markdown, empty results,
existing and missing parent directories, and the cache-hit CLI path in
`tests/skills/test_data_analysis_export_paths.py`.

Markdown exports use the same cell escaping for headers and values. Escape
backslashes before pipes and normalize CRLF, CR, and LF to inline `<br>` breaks;
raw newlines must not split one query-result row across Markdown table rows.

JSON exports require unique result column names under case-sensitive JSON key
semantics. Reject duplicate names before opening the output file and direct the
caller to explicit SQL aliases; never silently overwrite one column with another.
CSV and Markdown exports continue to preserve duplicate column headers.
List each duplicate name once in result-column order, using `repr` so embedded
line breaks remain escaped. At the CLI action-dispatch boundary, report
`ValueError` as a short stderr error with a nonzero exit; close the connection
in `finally` for both successful and failed actions. Other exceptions propagate.
