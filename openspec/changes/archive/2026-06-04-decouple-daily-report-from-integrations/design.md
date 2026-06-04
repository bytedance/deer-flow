## Context

The daily report skill (`skills/custom/daily-report/`) currently fetches InS monitoring data through a subprocess call chain:

```
query_daily.py
  → _data_providers.py: PlatformDailyProvider.fetch()
    → _platform_bridge.py: call_capability("monitoring.trend") + call_action("aggregate_kpi")
      → subprocess: python -m deerflow.integrations.cli --capability/--action
        → integrations/cli.py: CapabilityRouter → InsAdapter → InsClientBridge
          → features-tool InsApiClient + kpi_aggregator
```

The subprocess bridge (`_platform_bridge.py`) exists because the daily-report scripts run in a sandbox without the full `deerflow` harness importable. However, `features-tool` (the actual InS HTTP client) is available at `/opt/features-tool` in the same sandbox. The daily report scripts can import it directly, just as `InsClientBridge` does.

The `kpi_aggregator.py` in integrations contains pure functions with no I/O dependencies — they can be copied into the daily-report scripts directory as a standalone module.

The `list_equipment.py` script is already independent — it calls the Gateway Organize API directly via `urllib.request`.

## Goals / Non-Goals

**Goals:**
- Eliminate the subprocess bridge (`_platform_bridge.py`) — daily report scripts import `features-tool` directly
- Extract KPI aggregation pure functions into a standalone `_kpi_aggregator.py` within the daily-report scripts directory
- Maintain identical CLI contract for `query_daily.py`, `daily_kpi.py`, `export_report.py`, `list_equipment.py`
- Maintain identical output JSON schema (`daily_data.json` structure unchanged)
- Preserve error semantics: InS failures → `{"error": "HttpProviderError: ..."}` on stdout, exit 0
- Keep the `integrations` module completely unaffected

**Non-Goals:**
- Changing the DSL report template platform's relationship with integrations
- Modifying `list_equipment.py` (already independent)
- Modifying `daily_kpi.py` or `export_report.py` (pure computation/formatting)
- Changing how weekly/monthly reports work (same pattern, separate change)
- Removing `integrations/cli.py` or `integrations/adapters/ins/kpi_aggregator.py` (they remain for other consumers)
- Adding new KPI types or changing aggregation logic

## Decisions

### Decision 1: Direct import of features-tool instead of inlining HTTP calls

**Chosen**: Create `_ins_client.py` as a thin wrapper around `features-tool`'s `InsApiClient`.

**Rationale**: `InsApiClient` encapsulates InS authentication, connection pooling, retry logic, and the 2k/6k/8k/9k endpoint series protocol. Rewriting this from scratch would be error-prone and high-maintenance. The `InsClientBridge` in integrations already does the same thing — we're just moving the import boundary.

**Alternatives considered**:
- *Inline all HTTP calls with `urllib`*: Would duplicate ~500 lines of auth, retry, and endpoint routing. Rejected.
- *Keep `_platform_bridge.py` but optimize*: Still has subprocess overhead and the unwanted dependency on integrations. Rejected.

### Decision 2: Copy kpi_aggregator subset vs. import from integrations

**Chosen**: Create `_kpi_aggregator.py` as a standalone copy of the relevant pure functions from `integrations/adapters/ins/kpi_aggregator.py`.

**Rationale**: These are pure functions (~260 lines) with zero I/O dependencies. They only import from `kpi_map.py` for `KPI_FEATURE_MAP` and `select_points_for_kpi`. Copying them into the daily-report directory makes the skill self-contained. The original in integrations stays for CLI action mode consumers.

**Alternatives considered**:
- *Import from integrations at runtime*: Would require the full `deerflow` harness to be importable in the sandbox. Not guaranteed and against the goal of decoupling. Rejected.
- *Rewrite aggregation differently*: Unnecessary risk of behavioral divergence. Rejected.

### Decision 3: Keep _data_providers.py provider pattern

**Chosen**: Keep the `DailyDataProvider` protocol and `PlatformDailyProvider` class; rewrite `PlatformDailyProvider.fetch()` to use `_ins_client` + `_kpi_aggregator` directly instead of calling `_platform_bridge`.

**Rationale**: The provider pattern is clean and allows testing with alternate providers. The `query_daily.py` script only needs `_data_providers.py` updated — its own logic stays identical.

### Decision 4: Handle sandbox vs. host environment

**Chosen**: `_ins_client.py` detects environment at import time — if `/opt/features-tool` exists, import directly; otherwise raise a clear error. No docker exec fallback.

**Rationale**: The current bridge has complex docker exec routing logic for when scripts run on the host. With this change, daily report scripts are expected to run in the sandbox where `features-tool` is available. If they must run on the host, the caller is responsible for ensuring `features-tool` is on `sys.path`.

## Risks / Trade-offs

- **[Risk] `features-tool` API changes break daily reports**: The `InsApiClient` interface could change independently of the daily-report code. → **Mitigation**: `_ins_client.py` is a thin wrapper that maps `InsApiClient` responses to the stable internal format expected by `PlatformDailyProvider`. Only the wrapper needs updating.

- **[Risk] KPI aggregation divergence**: The standalone `_kpi_aggregator.py` could drift from `integrations/adapters/ins/kpi_aggregator.py` over time. → **Mitigation**: Both modules are tested independently. The daily-report version only needs the subset of functions used by daily reports. If the original adds new derivation methods, the daily-report copy is not forced to adopt them.

- **[Risk] Duplicated kpi_map constants**: `_kpi_aggregator.py` needs `KPI_FEATURE_MAP` from `kpi_map.py`. → **Mitigation**: Copy the relevant subset of `kpi_map.py` constants into `_kpi_aggregator.py` directly (a single dictionary). These are stable configuration, not logic.

## Migration Plan

1. Create `_ins_client.py` and `_kpi_aggregator.py` in the daily-report scripts directory
2. Update `_data_providers.py` → `PlatformDailyProvider.fetch()` to use the new modules
3. Run the existing test suite to verify output parity
4. Verify a full daily report generation end-to-end
5. Remove `_platform_bridge.py`
6. Deploy — no config changes needed; no downtime

**Rollback**: Revert `_data_providers.py` to import `_platform_bridge` and restore the file. The CLI contract is unchanged.
