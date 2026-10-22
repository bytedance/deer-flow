# Data-analysis source and SQL correctness

`analyze.py` allocates lookup aliases and SQL table names together. Neither may
shadow an existing alias or SQL name (case-insensitively). Both CSV files and Excel
sheets use this allocator; reserve a name only after CREATE TABLE succeeds.

Cache identity includes input order, filesystem-encoded basenames, per-file content
digests, and a namespace version. Directory relocation alone does not change a
readable input's identity. Bump the namespace if table-mapping semantics change.

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

Markdown exports use the same cell escaping for headers and values. Escape
backslashes before pipes and normalize CRLF, CR, and LF to inline `<br>` breaks;
raw newlines must not split one query-result row across Markdown table rows.
