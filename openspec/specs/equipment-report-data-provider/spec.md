# Equipment Report Data Provider

## Purpose

Specifies how equipment report data providers are registered and wired across the three per-report-type skills (`daily-report`, `weekly-report`, `monthly-report`), including direct InS fetch routing, `data_source` output field semantics, and the removal of the markdown data-source banner.

## Requirements

### Requirement: Provider registration for daily / weekly / monthly equipment reports

The `daily-report`, `weekly-report`, and `monthly-report` skills SHALL each independently register their respective provider source (`daily`, `weekly`, `monthly`) in their own `_data_providers._PROVIDER_FACTORIES`, each exposing **only** an `ins` mode resolved through `get_provider(source, mode=...)`. The `DEER_FLOW_DATA_PROVIDER` environment variable SHALL no longer gate AI report generation; when set, it MUST be ignored by the daily / weekly / monthly sources (other unrelated sources MAY continue to honor it). The legacy `demo` mode entries for these three sources MUST NOT be registered, and `Demo{Daily,Weekly,Monthly}Provider` classes (and their backing `_demo_*` helpers in the query scripts) MUST be removed.

Each skill's `_data_providers.py` is a fully independent copy; changes to one skill's provider registry SHALL NOT affect the other two skills.

#### Scenario: InS provider is the only mode

- **WHEN** `get_provider("daily")` (or `"weekly"` / `"monthly"`) is called within the respective skill with `DEER_FLOW_DATA_PROVIDER` unset
- **THEN** the registry returns the `Platform{Daily,Weekly,Monthly}Provider` instance and `list_registered()["daily"]` equals `["ins"]`

#### Scenario: Legacy demo mode raises

- **WHEN** code calls `get_provider("daily", mode="demo")` (or weekly / monthly)
- **THEN** `get_provider` raises `KeyError("no provider registered for source='daily' mode='demo'; registered=['ins']")`

#### Scenario: DEER_FLOW_DATA_PROVIDER is ignored

- **WHEN** `DEER_FLOW_DATA_PROVIDER=demo` is set in the environment and `get_provider("daily")` runs
- **THEN** the registry still returns `PlatformDailyProvider` — the env var has no effect for these three sources

#### Scenario: Each skill has independent provider registry

- **WHEN** a bug fix is applied to `daily-report/scripts/_data_providers.py`
- **THEN** `weekly-report` and `monthly-report` provider registries are unaffected and continue to function with their existing copies

### Requirement: Wire query scripts to direct InS fetch

`query_daily.py:fetch_day`, `query_weekly.py:fetch_week`, and `query_monthly.py:fetch_month` (and their `_with_provenance` siblings) SHALL invoke the registered InS provider directly via `get_provider(source).fetch(...)` rather than `fetch_with_fallback`. Each skill's copy of these scripts is independent. Any `HttpProviderError` raised by the InS provider MUST propagate unchanged to the script's `main()`, where it is rendered as `{"error": "<ExceptionType>: <message>"}` on stdout (matching the existing `_error(...)` helper). Scripts MUST NOT silently substitute synthetic data.

For `eq_type` values `rotating_machinery` and `reciprocating_machinery`, the InS provider SHALL fill the `alarms` field with real machine drop events fetched from the 8K or 9K `getMachineDrops` endpoint respectively. For all other `eq_type` values, `alarms` SHALL remain `[]`.

#### Scenario: InS error propagates to script main

- **WHEN** `PlatformDailyProvider.fetch(...)` raises `HttpProviderError("device <id> not found in InS")` and `query_daily.py` runs as a CLI
- **THEN** the script writes `{"error": "HttpProviderError: device <id> not found in InS"}` to stdout, exits 0 (existing convention), and does NOT write `daily_data.json`

#### Scenario: Compare period error fails the whole report

- **WHEN** the InS fetch for the `current` period succeeds but the `compare` period (e.g. previous day) raises `HttpProviderError`
- **THEN** the entire report fails with the InS error — no demo data is written and no "downgraded" / "fell back" notes are emitted

#### Scenario: features-tool unavailable surfaces an explicit error

- **WHEN** `_FEATURES_TOOL_AVAILABLE` is `False` (e.g. local sandbox without `/opt/features-tool`) and `query_daily.py` runs
- **THEN** the script returns the error `{"error": "HttpProviderError: features-tool not available: <reason>"}` rather than producing a demo-fallback report

#### Scenario: Rotating machinery reports include real alarms

- **WHEN** `PlatformDailyProvider.fetch(...)` runs with `eq_type="rotating_machinery"` and InS returns machine drop events
- **THEN** the `current.alarms` field in the output contains a list of non-empty alarm entries with `time`, `equipment`, `level`, `message` fields

#### Scenario: Event fetch failure does not fail the report

- **WHEN** `getMachineDrops` call fails (e.g. network timeout) during a rotating machinery report fetch
- **THEN** `current.alarms` is `[]` and the KPI data fetch proceeds normally — the event fetch failure is logged but does not propagate as an error

### Requirement: data_source field in script output

`query_daily.py`, `query_weekly.py`, and `query_monthly.py` SHALL write a single top-level field `data_source` with the constant value `"ins"` into their output JSON files (`daily_data.json` / `weekly_data.json` / `monthly_data.json`). The `data_notes` top-level field MUST also be present and MUST be an empty list (`[]`) on every successful run; it MUST NOT carry "fell back" / "downgraded" messages. Downstream `daily_kpi.py` / `weekly_kpi.py` / `monthly_kpi.py` transforms SHALL preserve both fields verbatim and SHALL NOT default `data_source` to `"demo_fallback"` when the field is missing — a missing field MUST raise a `KeyError` so an upstream regression cannot quietly produce demo-tagged output.

#### Scenario: Successful run writes ins with empty notes

- **WHEN** the script runs with a working InS path
- **THEN** the output JSON contains `"data_source": "ins"` and `"data_notes": []` at the top level

#### Scenario: KPI transform preserves data_source

- **WHEN** `daily_kpi.py` reads a `daily_data.json` containing `data_source="ins"` and `data_notes=[]`
- **THEN** the resulting `daily_kpi.json` carries the same two values at its top level

#### Scenario: Missing data_source surfaces a regression

- **WHEN** `daily_kpi.py` reads a payload that omits `data_source`
- **THEN** loading raises `KeyError("data_source")` instead of silently substituting `"demo_fallback"`

### Requirement: Markdown banner removed from AI report rendering

The `export_report.render_markdown` function SHALL NOT emit a data-source banner line for the AI report payloads (daily / weekly / monthly). The shared helper `_data_banner.format_banner` MUST be removed from the AI report rendering path; the file `_data_banner.py`, the `data_source_banner` field in KPI outputs, and the `data_source_banner` markdown sections in the builtin DSL templates (`agents/builtin/report-templates/{daily,weekly,monthly}-equipment/default.yaml`) MUST be removed. The three SOUL prompts (`agents/builtin/ai-report--{daily,weekly,monthly}/SOUL.md`) MUST drop any instructions about preserving a "first-line banner" or "demo fallback" copy.

Each skill's independent `export_report.py` copy SHALL implement this requirement separately.

#### Scenario: Rendered markdown has no banner line

- **WHEN** `export_report.render_markdown(payload)` runs against an `ins`-tagged payload
- **THEN** the first non-empty line of the rendered markdown is the report title (e.g. `# 设备运行日报`) — no `> ✅ 数据来源` or `> ⚠️ 当前使用演示数据` line precedes it

#### Scenario: KPI output contains no data_source_banner field

- **WHEN** `daily_kpi.py` writes `daily_kpi.json`
- **THEN** the JSON does NOT contain a `data_source_banner` key (the field is removed from the schema)

#### Scenario: Builtin DSL templates have no banner section

- **WHEN** `pytest backend/tests/test_builtin_report_templates.py` runs after this change
- **THEN** none of the three `{daily,weekly,monthly}-equipment/default.yaml` files contain a section referencing `data_source_banner`, and the validator still passes

#### Scenario: SOUL prompts no longer reference banners

- **WHEN** `agents/builtin/ai-report--daily/SOUL.md` (and weekly / monthly) is loaded
- **THEN** it contains no occurrence of "横幅", "banner", "demo", or "fallback" copy
