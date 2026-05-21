## Why

AI report generation currently hides InS outages and unmapped KPIs behind a synthetic/demo fallback, which can make a report look valid even when the production data path is broken. Removing that path makes the report behavior honest: it uses real InS data or fails explicitly, instead of silently substituting placeholder content.

## What Changes

- Remove the demo fallback path from daily, weekly, and monthly AI report generation.
- Make the report pipeline InS-only so data lookup, mapping, and trend retrieval failures surface as errors instead of producing demo output.
- Keep the successful output contract stable where possible, but fix report provenance to `data_source=ins` with empty `data_notes`.
- Remove demo-specific banner text and report copy from markdown rendering, report templates, and agent prompts.
- Update docs and tests to reflect that AI reports now require a working InS data path.

## Capabilities

### Modified Capabilities
- `equipment-report-data-provider`: the AI report path now requires real InS data only; demo providers, demo fallback, and demo banners are removed from this capability.

## Impact

Affected areas include the data-analyst report scripts and provider wiring, markdown rendering, builtin report templates, SOUL prompts, documentation, and tests. This simplifies the runtime path, but makes InS availability a hard requirement for AI report generation.
