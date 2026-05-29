## MODIFIED Requirements

### Requirement: Report scripts route through platform services via CLI subprocess bridge

The existing report query scripts (`query_daily.py`, `query_weekly.py`, `query_monthly.py`) SHALL support routing their data queries through the platform integration service layer via a CLI subprocess bridge. This approach preserves the sandbox dependency-free constraint — scripts cannot import `deerflow.*` (which would pull in langchain/langgraph).

The platform layer SHALL provide a CLI entry point:

```text
python -m deerflow.integrations.cli --capability "monitoring.trend" --params '{"equipment_id": "123", ...}'
```

The CLI SHALL:

1. Accept `--capability` and `--params` (JSON string) arguments
2. Construct the appropriate service call
3. Route through `CapabilityRouter` to the correct adapter
4. Output the canonical model as JSON to stdout
5. Exit with code 0 on success, non-zero on error

The report scripts SHALL switch from direct features-tool calls to `subprocess.run(["python", "-m", "deerflow.integrations.cli", ...])` when `USE_PLATFORM=true` is set.

The existing `_ins_provider.py` features-tool path SHALL remain as the default until Phase 3 cleanup.

#### Scenario: CLI entry point outputs JSON

- **WHEN** `python -m deerflow.integrations.cli --capability "monitoring.trend" --params '{"equipment_id": "123", "metric": "vibration"}'` is executed
- **THEN** the CLI calls `MonitoringService.get_trend(...)` which routes through `CapabilityRouter` → `InsAdapter`
- **THEN** outputs the `TrendSeries` as JSON to stdout
- **THEN** exits with code 0

#### Scenario: CLI entry point on error

- **WHEN** the CLI encounters an `AdapterError`
- **THEN** outputs `{"error": "connection_failed", "system_key": "ins_prod", "capability": "monitoring.trend"}` to stdout
- **THEN** exits with code 1

#### Scenario: Script with USE_PLATFORM=true

- **WHEN** `query_daily.py` is executed with `USE_PLATFORM=true` environment variable
- **THEN** the script calls `subprocess.run(["python", "-m", "deerflow.integrations.cli", "--capability", "monitoring.trend", "--params", ...])`
- **THEN** parses the JSON output from stdout
- **THEN** the output format (the script's own JSON contract) is identical to the features-tool path

#### Scenario: Script without USE_PLATFORM

- **WHEN** `query_daily.py` is executed without `USE_PLATFORM` (or `USE_PLATFORM=false`)
- **THEN** the script uses the existing `_ins_provider.py` features-tool path
- **THEN** behavior is identical to the current implementation

#### Scenario: CLI fallback when platform service unavailable

- **WHEN** `USE_PLATFORM=true` but the CLI subprocess exits with non-zero
- **THEN** the script logs a warning: `"Platform service failed, falling back to features-tool"`
- **THEN** retries using the existing `_ins_provider.py` path
- **THEN** the output JSON includes `"data_source": "ins"` (the fallback source)

### Requirement: Report template DSL supports platform provider hint

The report template DSL's `data_steps` configuration SHALL support an optional `provider` field. When set to `"platform"`, the `data_runner.py` runtime module SHALL set `USE_PLATFORM=true` in the subprocess environment before executing the query script.

The default SHALL remain `"ins"` (features-tool path) for backward compatibility.

#### Scenario: DSL data_step with platform provider

- **WHEN** a report template DSL includes:

  ```yaml
  data_steps:
    - name: "data-analyst/query_daily"
      provider: "platform"
      parameters:
        date: "2026-05-27"
  ```

- **THEN** `data_runner.py` sets `USE_PLATFORM=true` in the subprocess env
- **THEN** the query script routes through the CLI subprocess bridge

#### Scenario: DSL data_step without provider field

- **WHEN** a report template DSL omits the `provider` field
- **THEN** `data_runner.py` does not set `USE_PLATFORM`
- **THEN** the query script uses the existing features-tool path

#### Scenario: DSL validator accepts provider field

- **WHEN** the report template validator encounters `provider: "platform"` in a `data_step`
- **THEN** validation passes without errors
- **THEN** the validator accepts `"platform"`, `"ins"`, `"demo"`, and `"http"` as valid values

### Requirement: KPI Feature Map extraction to platform layer

The `_KPI_FEATURE_MAP` and `_select_points_for_kpi` logic from `_ins_provider.py` SHALL be extracted to the platform layer as `deerflow/integrations/adapters/ins/kpi_map.py`. This module SHALL be pure data + pure logic with no external dependencies.

The CLI subprocess bridge (`deerflow.integrations.cli`) SHALL use the extracted `kpi_map` module internally. The sandbox `_ins_provider.py` SHALL retain its own copy as a fallback during the transition period.

#### Scenario: Platform layer has KPI Feature Map

- **WHEN** `deerflow/integrations/adapters/ins/kpi_map.py` is imported
- **THEN** `KPI_FEATURE_MAP` dict is available with the same structure as `_ins_provider._KPI_FEATURE_MAP`
- **THEN** `select_points_for_kpi()` function is available with the same signature

#### Scenario: Sandbox _ins_provider.py retains fallback

- **WHEN** `_ins_provider.py` is loaded in the sandbox
- **THEN** its local `_KPI_FEATURE_MAP` is still available
- **THEN** the features-tool path works independently of the platform layer

### Requirement: Deprecation logging for direct features-tool path

When the existing `_ins_provider.py` makes a direct features-tool API call (bypassing the platform service layer), the system SHALL emit a deprecation warning log:

```text
[DEPRECATED] Direct features-tool call from report script. Use platform service layer instead (set USE_PLATFORM=true or provider: "platform" in DSL).
```

This warning SHALL be logged at `WARNING` level and SHALL NOT affect functionality.

#### Scenario: Deprecation warning on direct features-tool call

- **WHEN** `_ins_provider.py` calls features-tool `InsApiClient` for a daily/weekly/monthly query
- **THEN** a `WARNING` log is emitted with the deprecation message
- **THEN** the API call proceeds normally
- **THEN** the log includes the script name and query parameters

#### Scenario: No warning for platform mode

- **WHEN** the script routes through the CLI subprocess bridge
- **THEN** no deprecation warning is logged
- **THEN** the call is logged at `INFO` level with source attribution

#### Scenario: Warning can be suppressed

- **WHEN** the environment variable `SUPPRESS_INS_DEPRECATION_WARNING=true` is set
- **THEN** the deprecation warning is not logged
