# Data analysis skill (`skills/public/data-analysis/`)

```bash
python -m pytest tests/skills -q -k "data_analysis"
```

Tests use real DuckDB. Default tests never download the spatial extension. Excel
and CLI integration tests run only with an installed copy named by
`DEERFLOW_TEST_SPATIAL_DIRECTORY`.

## Table names and SQL

- **Lookup aliases and SQL table names are allocated together**, for CSV files
  and Excel sheets. Neither may shadow an existing name, compared without case.
  Reserve a name only after its table was created.
- **Bind file paths and sheet names as SQL values**, and quote generated
  identifiers.
- **User SQL is never rewritten with regular expressions.** Original names
  resolve through connection-local temporary views over the canonical tables,
  also on a read-only cache hit. Normal CTE shadowing keeps working.

## Cache

- **Cache identity covers input order, file names and content digests.** Moving
  the directory does not change it. Bump the namespace version when the
  table-mapping semantics change.
- **Publish through `open_analysis_cache()`.** Build in a private directory,
  close the writer, reopen read-only, then atomically replace one manifest.
  Metadata is never published while a writer owns the database.
- **Validate the manifest and the physical tables before reuse.** An invalid
  entry is rebuilt.
- **Keep a generation when publication may have happened.** Another process may
  be reading it. Concurrent cold builders can repeat work, and they never share
  a writable database.
- **There is no automatic garbage collection and no power-loss guarantee.**

## Environment and exports

- **Missing DuckDB or openpyxl prints setup instructions.** The skill does not
  start an installer.
- **Export paths resolve against the caller's working directory**, also for a
  bare file name.
- **Markdown export escapes headers and values the same way**, and turns line
  breaks into `<br>`, so one result row stays one table row.
- **JSON export rejects duplicate column names** before it opens the output
  file, and tells the caller to add SQL aliases. CSV and Markdown keep
  duplicates.
- **At the CLI boundary a `ValueError` becomes a short stderr message and a
  non-zero exit.** The connection closes in `finally`.
