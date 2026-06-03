---
name: monitoring-analysis
description: Monitoring analysis scripts for equipment trend analysis, anomaly detection, KPI health assessment, cross-parameter correlation analysis, and spectrum/waveform analysis. Provides query_trend, trend_analysis, data_quality, export_report, and Pro/Ultra tier analysis scripts.
---

# Monitoring Analysis Skill Scripts

This skill provides executable scripts for equipment monitoring analysis. The agent uses these scripts via the `bash` tool to query trend data, perform trend analysis, detect anomalies, assess KPI health, compute cross-parameter correlations, and analyze waveform/spectrum data.

## When to Use This Skill

Use these scripts when:

- The user requests equipment trend analysis, anomaly detection, or KPI health assessment
- The monitoring-analysis agent needs to fetch time-series trend data
- Cross-parameter correlation analysis is requested
- Waveform/spectrum analysis for rotating machinery is needed

## Preconditions

- The `bash` tool must be available (sandbox tool group enabled)
- Environment variables:
  - `DEER_FLOW_DATA_PROVIDER` — Set to `ins` for InS platform data, `demo` for demo fallback (default: `ins`)
  - `MONITORING_OUTPUT_DIR` — Output directory (default `/mnt/user-data/outputs`)

## Scripts

### query_trend.py — Query time-series trend data

```bash
python /mnt/skills/custom/monitoring-analysis/scripts/query_trend.py \
  --metric-keys "runtime_rate,vibration_level" \
  --date-range "2026-01-01..2026-05-18" \
  --aggregation daily \
  --forecast-horizon 14 \
  --equipment "P-001,P-002" \
  --output-dir /mnt/user-data/outputs/
```

Optional flags: `--include-alarms`, `--include-events`. Writes `/mnt/user-data/outputs/data/trend_data.json`.

### trend_analysis.py — Interpretive trend analysis (§13.2)

```bash
python /mnt/skills/custom/monitoring-analysis/scripts/trend_analysis.py \
  --input /mnt/user-data/outputs/data/trend_data.json \
  --output-dir /mnt/user-data/outputs/
```

Produces findings, evidence, confidence, trend_chart (ECharts option), forecast, and recommendations.

### data_quality.py — Data quality assessment

```bash
python /mnt/skills/custom/monitoring-analysis/scripts/data_quality.py \
  --input /mnt/user-data/outputs/data/trend_data.json \
  --tier pro|ultra \
  --output-dir /mnt/user-data/outputs/
```

Pro: missing value detection, ±5σ outlier marking, completeness rate. Ultra: 3D quality score + linear interpolation.

### export_report.py — Export monitoring report

```bash
python /mnt/skills/custom/monitoring-analysis/scripts/export_report.py \
  --input /mnt/user-data/outputs/monitoring_features.json \
  --report-type monitoring \
  --format md
```

Generates Markdown (required) and PDF (optional, needs weasyprint) monitoring reports.

### Pro Tier Scripts

| Script | Description |
|--------|-------------|
| `pro_trend.py` | Multi-model regression, STL decomposition, PELT changepoint detection |
| `pro_anomaly.py` | Isolation Forest, DBSCAN clustering, adaptive rolling thresholds |
| `pro_kpi.py` | Health score trends, peer percentile comparison, weighted scoring |
| `pro_correlation.py` | Spearman/Kendall coefficients, lagged cross-correlation, partial correlation |
| `pro_spectrum.py` | Hilbert envelope, cepstrum, bearing fault frequency matching, sideband detection |

### Ultra Tier Scripts

| Script | Description |
|--------|-------------|
| `ultra_trend.py` | ONNX LSTM prediction, 80%/95% confidence intervals, co-trending groups |
| `ultra_anomaly.py` | Autoencoder scoring, multi-sensor cross-validation, root cause ranking |
| `ultra_kpi.py` | Predictive health scoring, risk ranking, risk matrix |
| `ultra_correlation.py` | Granger causality, transfer entropy, Graphical Lasso |
| `ultra_spectrum.py` | CNN classification, CNN+rule combined verdict, fault evolution tracking |

## Output Convention

- All scripts output JSON to stdout
- Errors emit `{"error": "<code>: <message>"}` and exit 0
- Authentication is via environment variables, never hardcoded

## Integration with Monitoring Analysis Agent

The monitoring-analysis agent SOUL.md references these scripts for all analysis pipelines. For KPI dashboard functionality, the agent also uses `query_daily.py` from the `daily-report` skill.
