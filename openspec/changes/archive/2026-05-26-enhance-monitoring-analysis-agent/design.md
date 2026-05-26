## Context

The `monitoring-analysis` agent currently exists as a minimal stub: a `config.yaml` with basic metadata and a `SOUL.md` that implements a generic 3-step "data source discovery → form → fetch" flow. It lacks equipment-aware workflows, real INS data integration, structured analysis modes, and report export — all patterns already proven by the `fault-diagnosis--*` and `ai-report--*` agent families.

The system already provides all necessary building blocks:
- **GenUI components**: `device-selector-multi`, `sub-device-selector`, `form`, `echart`, `table`, `card`, `markdown`
- **Data scripts**: `_ins_provider.py` (real INS data), `query_trend.py` (trend data), `_report_common.py` (KPI definitions)
- **Export pipeline**: `export_report.py` with `write_report()` supporting `md`/`pdf` formats
- **Closure integration**: `create_closure_ticket` builtin tool
- **Agent patterns**: Callback-driven state machine (fd-pump-device → fd-pump-time → execute → export), input validation, error propagation

Constraints:
- No frontend changes — all UI through existing GenUI components
- No new backend routes or services — agent operates within the existing sandbox + tool framework
- No new Python dependencies — reuse `data-analyst` skill scripts
- Agent files are markdown + YAML only (`SOUL.md` + `config.yaml`)

## Goals / Non-Goals

**Goals:**
- Design a multi-step monitoring workflow GenUI state machine matching the fault-diagnosis pattern quality
- Support 4 analysis modes: trend detection, anomaly detection, KPI dashboard, correlation analysis
- Wire real INS data through existing `data-analyst` skill infrastructure
- Produce EChart-rich structured reports with MD/PDF export
- Integrate closure ticket creation for critical anomalies
- Proper input validation at every callback boundary

**Non-Goals:**
- Real-time streaming monitoring (this is on-demand analysis, not continuous)
- New data provider implementations — reuse `InsTrendProvider` and related infrastructure
- Custom chart types beyond existing ECharts capabilities
- Report template DSL integration (Phase 1 is SOUL-driven; DSL migration is follow-on)
- Alerting/notification pipeline (out of scope for agent; belongs in platform layer)

## Decisions

### D1: SOUL-driven workflow over DSL template (Phase 1)

**Choice**: Implement Phase 1 entirely within `SOUL.md` (like `fault-diagnosis--pump`), not as a report template DSL.

**Rationale**: The monitoring analysis flow requires dynamic branching (4 analysis types lead to different data fetches and visualizations). The current DSL template system is designed for linear report generation pipelines. A SOUL.md agent can conditionally branch, call different scripts per analysis type, and adapt visualizations dynamically. DSL support can be added later once the SOUL path stabilizes.

**Alternatives considered**: Report template DSL — rejected because the DSL's `data_steps` + `transforms` model doesn't cleanly support the conditional branching needed for 4 distinct analysis modes within a single template.

### D2: Analysis type selection via form enum (not separate agents)

**Choice**: Single agent with a form-based analysis type selector, rather than 4 separate sub-agents.

**Rationale**: Monitoring analysis types share 80% of their workflow (equipment selection, time range, data fetch). Separate agents would duplicate this boilerplate. The `fault-diagnosis` group pattern (parent + sub-agents) is appropriate when workflows diverge significantly (pump vs rotating vs reciprocating have different rule engines). Monitoring modes share the same data sources and scripts.

**Alternatives considered**: Group + sub-agent pattern like `fault-diagnosis` — rejected because the analysis types are more homogeneous and splitting would increase maintenance burden without improving UX.

### D3: Reuse query_trend.py + trend_analysis.py for trend monitoring

**Choice**: Use existing `query_trend.py` (time-series fetch) and `trend_analysis.py` (decomposition + anomaly detection + forecast) as the data backbone.

**Rationale**: These scripts are already registered in `report_scripts.yaml` and follow the same contract as daily/weekly/monthly scripts. They support aggregation levels (hourly/daily/weekly), forecast horizons, and the `_ins_provider.py` data path. No new scripts needed for Phase 1.

### D4: KPI dashboard uses query_daily.py with aggregate mode

**Choice**: Build the KPI dashboard mode on `query_daily.py --aggregate` with `--kpis` covering runtime_rate, alarm_count, vibration_level, temperature, pressure, corrosion_rate.

**Rationale**: `query_daily.py` already supports the aggregate flag and KPI filtering. The multi-KPI response can be directly transformed into radar chart and gauge card GenUI blocks without a new script.

### D5: Correlation analysis via Python inline in sandbox

**Choice**: For correlation analysis, fetch multi-parameter data via `query_trend.py` with multiple `--metric-keys`, then run a lightweight inline Python script to compute Pearson correlation matrix and render as ECharts heatmap.

**Rationale**: Correlation computation is simple enough (numpy-free, pure Python) to run inline. Creating a dedicated script would add maintenance overhead for ~20 lines of math. The data fetch is already covered by `query_trend.py`.

### D6: Export via existing export_report.py with new monitoring report type

**Choice**: Register a `"monitoring"` report type in `export_report.py` (alongside existing `"daily"`, `"weekly"`, `"monthly"`, `"diagnosis"`), called via in-process import from SOUL.md.

**Rationale**: Follows the exact pattern used by `fault-diagnosis--pump` (Step 5). The export pipeline (Markdown render + optional PDF via weasyprint) is identical. Adding a report type is a minimal change to `export_report.py`.

## Risks / Trade-offs

- **[Risk] query_trend.py currently has demo-only data** → The `report_scripts.yaml` marks these as "demo stubs delivering deterministic synthetic data". For Phase 1, the agent works with INS data when available through `_ins_provider.py`'s `HttpTrendProvider`. If INS trend endpoints are not yet deployed, the agent surfaces a clear error per the data-provider contract — no silent demo fallback.
- **[Risk] Correlation analysis inline Python may hit sandbox limits** → Mitigation: limit to 10 parameters × 30 data points; output size capped at 10MB per `report_scripts.yaml` limits.
- **[Risk] Four analysis modes increase SOUL.md complexity** → Mitigation: structure SOUL.md with clearly separated callback sections per analysis type, matching the fault-diagnosis SOUL.md organization pattern (each callback_id has its own clearly delimited section).
