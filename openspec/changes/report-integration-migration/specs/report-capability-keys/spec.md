# CLI Action Mode

## ADDED Requirements

### Requirement: CLI `--action` parameter for system-specific computation

The system SHALL add an `--action` parameter to `deerflow/integrations/cli.py` that exposes adapter-internal computation functions. `--action` and `--capability` SHALL be mutually exclusive — exactly one must be provided.

Supported actions:

- `aggregate_kpi` — aggregate raw trend data into KPI scalar values
- `select_points` — select measurement points from component tree for a given KPI

Action mode SHALL NOT go through `CapabilityRouter`. It directly instantiates the specified adapter (via `--adapter <key>`) and calls the adapter's internal computation functions.

```bash
# capability mode: cross-system routing, returns raw data
python -m deerflow.integrations.cli \
    --capability monitoring.trend \
    --params '{"equipment_ids": ["E1"], "start_time": "...", "end_time": "..."}'

# action mode: adapter-internal computation, returns aggregated results
python -m deerflow.integrations.cli \
    --action aggregate_kpi \
    --adapter ins_prod \
    --params '{"trend_data": {...}, "kpi_keys": ["runtime_rate"], "eq_type": "rotating_machinery"}'
```

#### Scenario: Action mode with aggregate_kpi

- **WHEN** CLI is invoked with `--action aggregate_kpi --adapter ins_prod --params '{...}'`
- **THEN** the CLI loads adapter `ins_prod` from the registry
- **THEN** calls `adapter.get_aggregator().aggregate_equipment_kpis(...)` with the provided params
- **THEN** outputs JSON in the standard format: `{"ok": true, "data": {...}}`

#### Scenario: Action mode with select_points

- **WHEN** CLI is invoked with `--action select_points --adapter ins_prod --params '{"components": [...], "kpi_key": "vibration_velocity_rms", "eq_type": "pump"}'`
- **THEN** calls `adapter.get_aggregator().select_points_for_kpi(...)`
- **THEN** outputs JSON with the matching point list

#### Scenario: Mutual exclusion of --action and --capability

- **WHEN** CLI is invoked with both `--action aggregate_kpi --capability monitoring.trend`
- **THEN** the CLI exits with error code 1 and a clear error message: "Cannot use both --action and --capability"

#### Scenario: Action without --adapter

- **WHEN** CLI is invoked with `--action aggregate_kpi` but no `--adapter` parameter
- **THEN** the CLI exits with error code 1 and a clear error message: "--action requires --adapter"

#### Scenario: Unknown action name

- **WHEN** CLI is invoked with `--action unknown_action --adapter ins_prod`
- **THEN** the CLI exits with error code 1 and lists available actions: "Unknown action: unknown_action. Available: aggregate_kpi, select_points"

### Requirement: Action output format consistency

All action outputs SHALL follow the same JSON envelope as capability mode:

```json
{
    "ok": true,
    "data": { ... },
    "adapter": "ins_prod",
    "action": "aggregate_kpi"
}
```

On failure:

```json
{
    "ok": false,
    "error": "description of what went wrong",
    "adapter": "ins_prod",
    "action": "aggregate_kpi"
}
```

#### Scenario: Successful action output

- **WHEN** an action completes successfully
- **THEN** the output JSON contains `"ok": true` and the result in `"data"`
- **THEN** the output includes `"adapter"` and `"action"` fields for traceability

#### Scenario: Failed action output

- **WHEN** an action raises an exception
- **THEN** the output JSON contains `"ok": false` and the error message in `"error"`
- **THEN** the CLI exits with code 1
