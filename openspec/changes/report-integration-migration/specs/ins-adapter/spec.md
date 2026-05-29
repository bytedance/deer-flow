# InsAdapter - KPI Aggregator Exposure

## MODIFIED Requirements

### Requirement: InsAdapter exposes KPI aggregator

The system SHALL add a `get_aggregator()` method to `InsAdapter` that returns the `kpi_aggregator` module's functions. This method is used by CLI action mode to access adapter-internal computation functions.

```python
class InsAdapter:
    def get_aggregator(self):
        """Return the KPI aggregator module for CLI action mode."""
        from . import kpi_aggregator
        return kpi_aggregator
```

The method SHALL return the module itself (not an instance), since all aggregator functions are pure functions with no state.

The existing 6 capability handlers (`asset.catalog`, `asset.context`, `monitoring.trend`, `monitoring.waveform`, `monitoring.orbit`, `monitoring.alarm_history`) SHALL remain unchanged. No new capability keys are added to the handler dispatch dict.

#### Scenario: CLI action mode accesses aggregator

- **WHEN** CLI `--action aggregate_kpi --adapter ins_prod` is invoked
- **THEN** the CLI calls `adapter.get_aggregator()` on the `ins_prod` adapter instance
- **THEN** receives the `kpi_aggregator` module
- **THEN** calls `kpi_aggregator.aggregate_equipment_kpis(...)` with the provided params

#### Scenario: Aggregator module is stateless

- **WHEN** `get_aggregator()` is called multiple times
- **THEN** it returns the same module reference each time
- **THEN** no new instances are created

#### Scenario: Existing capability handlers unaffected

- **WHEN** `InsAdapter.call("monitoring.trend", query, ctx)` is called
- **THEN** behavior is identical to before this change
- **THEN** the handler dispatch dict still contains exactly 6 entries

### Requirement: InsAdapter supports batch queries in existing handlers

The system SHALL update `_handle_monitoring_trend()` and `_handle_monitoring_alarm_history()` to support the new batch parameters (`equipment_ids`, `eq_type`) added to `TrendQuery` and `AlarmHistoryQuery`.

When `equipment_ids` is non-empty, the handler SHALL fetch data for all specified equipment and return a combined result. The handler SHALL use `kpi_aggregator.select_points_for_kpi()` to resolve measurement points for batch queries.

#### Scenario: Batch trend query handled

- **WHEN** `_handle_monitoring_trend(TrendQuery(equipment_ids=("E1", "E2", "E3"), eq_type="rotating_machinery", ...), ctx)` is called
- **THEN** the handler fetches trend data for all three equipment
- **THEN** returns a combined `TrendSeries` with data from all equipment
- **THEN** `source_metadata` includes the list of equipment IDs

#### Scenario: Single equipment query unchanged

- **WHEN** `_handle_monitoring_trend(TrendQuery(asset_id="E1", ...), ctx)` is called
- **THEN** behavior is identical to the current implementation
- **THEN** `equipment_ids` defaults to `()` and is ignored
