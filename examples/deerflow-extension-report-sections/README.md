# Report sections — sectioned long-form writing plugin example

For the shared edit → test → packaging check → install workflow, see the
[existing-example guide](../README.md).

A compact example of a **stateful model tool**: the agent writes a 万字-scale
long report section by section with `save_section`, and a final
`section_index=999` call assembles every stored section into one markdown
document. The assembled report is returned as a tool artifact (visible in the
UI) with only a short status summary re-entering the model context, so the
full document never consumes the agent's context budget.

Assembly drops a section's leading heading when it restates the section title
(models habitually open each section with `# <title>` while the assembler
already emits `## <title>`), which otherwise produces doubled headings across
the whole report. Sections are scoped per user and per thread in the plugin's
own SQLite file — no host database or host-internal imports.

## Deployment

Install this directory using the existing trusted Python extension manager.
From `backend/`:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-report-sections --yes
```

Then set the deployment-owned `config` on the registered plugin entry before
restarting Gateway. Example configuration:

```yaml
plugins:
  - use: deerflow_extension_report_sections:install
    enabled: true
    config:
      enabled: true
      storage_path: /var/lib/deerflow/report-sections.sqlite
```

The outer `enabled` controls package loading; `config.enabled` controls the
tool contribution. Mount a persistent writable directory for `storage_path`.
The file stores user section data, not deployment settings.

## Tool contract

`save_section(section_index, title, content)`:

- `section_index=0` — store the outline (passed through unwrapped on assembly).
- `1..N` — store one chapter (keep each call within roughly 1200–2000
  characters to stay inside the per-completion output budget; hard cap 24000).
- `999` with `title="__assemble__"` — assemble all stored sections into
  `report-<topic>.md`, delivered as an artifact. Assemblies over 60 KiB are
  refused with a clear status; the sections remain stored.

The tool result envelope is capped at 64 KiB by the host; this example keeps
the model-visible content to one status line and carries the document in the
artifact.

## Tests

From the DeerFlow checkout root with the backend environment prepared:

```sh
uv run --project backend --no-sync python -m pytest backend/tests/test_report_sections_extension.py -q
```
