## MODIFIED Requirements

### Requirement: Provider registration for daily / weekly / monthly equipment reports

The data-analyst skill SHALL register `daily`, `weekly`, and `monthly` as named provider sources in `_data_providers._PROVIDER_FACTORIES`, each exposing **only** an `ins` mode resolved through `get_provider(source, mode=...)`. The `DEER_FLOW_DATA_PROVIDER` environment variable SHALL no longer gate AI report generation; when set, it MUST be ignored by the daily / weekly / monthly sources (other unrelated sources MAY continue to honor it). The legacy `demo` mode entries for these three sources MUST NOT be registered, and `Demo{Daily,Weekly,Monthly}Provider` classes (and their backing `_demo_*` helpers in the query scripts) MUST be removed.

#### Scenario: InS provider is the only mode

- **WHEN** `get_provider("daily")` (or `"weekly"` / `"monthly"`) is called with `DEER_FLOW_DATA_PROVIDER` unset
- **THEN** the registry returns the `Ins{Daily,Weekly,Monthly}Provider` instance and `list_registered()["daily"]` equals `["ins"]`

#### Scenario: Legacy demo mode raises

- **WHEN** code calls `get_provider("daily", mode="demo")` (or weekly / monthly)
- **THEN** `get_provider` raises `KeyError("no provider registered for source='daily' mode='demo'; registered=['ins']")`

#### Scenario: DEER_FLOW_DATA_PROVIDER is ignored

- **WHEN** `DEER_FLOW_DATA_PROVIDER=demo` is set in the environment and `get_provider("daily")` runs
- **THEN** the registry still returns `InsDailyProvider` — the env var has no effect for these three sources

### Requirement: Wire query scripts to direct InS fetch

`query_daily.py:fetch_day`, `query_weekly.py:fetch_week`, and `query_monthly.py:fetch_month` (and their `_with_provenance` siblings) SHALL invoke the registered InS provider directly via `get_provider(source).fetch(...)` rather than `fetch_with_fallback`. Any `HttpProviderError` raised by the InS provider MUST propagate unchanged to the script's `main()`, where it is rendered as `{"error": "<ExceptionType>: <message>"}` on stdout (matching the existing `_error(...)` helper). Scripts MUST NOT silently substitute synthetic data.

#### Scenario: InS error propagates to script main

- **WHEN** `InsDailyProvider.fetch(...)` raises `HttpProviderError("device <id> not found in InS")` and `query_daily.py` runs as a CLI
- **THEN** the script writes `{"error": "HttpProviderError: device <id> not found in InS"}` to stdout, exits 0 (existing convention), and does NOT write `daily_data.json`

#### Scenario: Compare period error fails the whole report

- **WHEN** the InS fetch for the `current` period succeeds but the `compare` period (e.g. previous day) raises `HttpProviderError`
- **THEN** the entire report fails with the InS error — no demo data is written and no "downgraded" / "fell back" notes are emitted

#### Scenario: features-tool unavailable surfaces an explicit error

- **WHEN** `_FEATURES_TOOL_AVAILABLE` is `False` (e.g. local sandbox without `/opt/features-tool`) and `query_daily.py` runs
- **THEN** the script returns the error `{"error": "HttpProviderError: features-tool not available: <reason>"}` rather than producing a demo-fallback report

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

## REMOVED Requirements

### Requirement: Backward-compatible default behavior

**Reason**: AI report generation no longer has a "default demo" path. With demo removed, scripts cannot produce output absent a working InS connection — there is nothing left to be backward-compatible with. The previous requirement promised that "setting neither `DEER_FLOW_DATA_PROVIDER` nor invoking InS" would still yield deterministic demo output; that promise is intentionally broken by this change.

**Migration**: Operators MUST configure `INS_USERNAME` / `INS_PASSWORD` and run inside the docker sandbox image with `/opt/features-tool` available before invoking daily / weekly / monthly AI reports. Existing tests that asserted demo output (`test_ai_report_daily_query.py` and friends) MUST be rewritten to mock `Ins{Daily,Weekly,Monthly}Provider.fetch` and assert on the `ins` payload shape; tests that asserted demo banner copy MUST be deleted.

### Requirement: Markdown banner reflecting data source

**Reason**: With the demo path removed, the banner has only one possible value (`> ✅ 数据来源：InS 实时接入`), which adds no information for the reader and clutters the rendered report. The banner exists today specifically to warn operators that the report is synthetic; once demo is gone, it has nothing to warn about.

**Migration**: Remove `_data_banner.py`, drop the `data_source_banner` field from KPI output schemas, delete the `data_source_banner` sections from the three builtin DSL templates, and remove banner-related instructions from the three SOUL prompts. Tests that asserted on banner text (e.g. `test_ai_report_daily_export.py::test_*_banner`) MUST be deleted, not rewritten.

### Requirement: Sandbox mode constraint

**Reason**: This requirement guaranteed that local sandbox / non-features-tool environments would silently fall back to demo. With demo removed there is no such fallback — the InS path is mandatory and any environment lacking `/opt/features-tool` MUST fail loudly so operators notice immediately.

**Migration**: Operators running in `LocalSandboxProvider` mode or with a custom sandbox image MUST install `features-tool` (or switch to the `deer-flow-sandbox-features-tool` image) before invoking AI reports. The existing scenarios that asserted "silent demo fallback" become assertions that the script raises an explicit `HttpProviderError` mentioning "features-tool not available", as covered by the modified "Wire query scripts to direct InS fetch" requirement above.
