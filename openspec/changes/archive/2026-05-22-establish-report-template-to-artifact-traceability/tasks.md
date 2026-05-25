## 1. Backend — Run list/detail enrichment

- [x] 1.1 Extend `GET /api/report-runs` list response to include `data_file_count` per run (scan `{run_output_dir}/data/` directory, count JSON files)
- [x] 1.2 Extend `GET /api/report-runs/{id}` response to include `data_files` array (list of `{name, path}` for files under `{run_output_dir}/data/`)
- [x] 1.3 Ensure `template_version` and `template_version_ref` are always present in list and detail responses

## 2. Backend — Error code standardization

- [x] 2.1 Define error code constants (`TEMPLATE_UNAVAILABLE`, `KB_UNAVAILABLE`, `RUN_INTERRUPTED`, `DATA_STEP_FAILED`) in `records.py`
- [x] 2.2 Update `report_template_prepare_run` tool to check template status and set `TEMPLATE_UNAVAILABLE` on archived/deleted templates
- [x] 2.3 Update `report_template_run_data_steps` tool to set `DATA_STEP_FAILED` with step identifier on script failure
- [x] 2.4 Update cancel path to set `RUN_INTERRUPTED` error code

## 3. Frontend — Template version traceability

- [x] 3.1 Update `report-run-detail-page.tsx` template link to point to version-specific URL (`?version={template_version}`)
- [x] 3.2 Handle builtin template case: display `template_version_ref` as non-clickable label when `template_version` is null
- [x] 3.3 Add template version column to `report-runs-page.tsx` table

## 4. Frontend — Input source visibility

- [x] 4.1 Add "Source Chat" section to `report-run-detail-page.tsx` with link to originating thread (reuse existing `thread_id` link pattern)
- [x] 4.2 Add "Data Files" section to run detail page listing downloadable data step outputs
- [x] 4.3 Add raw parameters download link when `parameters_path` is present

## 5. Frontend — Error display

- [x] 5.1 Map the four error code prefixes to user-facing Chinese/English messages in the run detail error section
- [x] 5.2 Display error messages with severity-appropriate styling (destructive for DATA_STEP_FAILED/KB_UNAVAILABLE, warning for TEMPLATE_UNAVAILABLE)

## 6. Tests — End-to-end traceability verification

- [x] 6.1 Create `test_report_template_traceability_e2e.py` with `test_full_chain_template_to_artifact` that creates a template, publishes it, simulates prepare→data→assemble→export, and verifies: run record references correct template version, payload contains template/run metadata, artifact paths point to existing files
- [x] 6.2 Run full test suite and verify all tests pass (new + existing)
