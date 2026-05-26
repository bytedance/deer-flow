## 1. SOUL.md — Scope Form Update

- [x] 1.1 Update `analysis_type` enum validation in "核心原则" to include `spectrum`
- [x] 1.2 Add `{"label": "图谱分析 — 波形频谱特征提取与可视化", "value": "spectrum"}` option to scope form `analysis_type` select field
- [x] 1.3 Update scope callback dispatch table to include `spectrum` → 图谱分析流水线

## 2. SOUL.md — Spectrum Analysis Pipeline (timestep selection)

- [x] 2.1 Add "图谱分析流水线 (analysis_type = spectrum)" section with overview description
- [x] 2.2 Implement Step S1a (trend pre-query): invoke `query_trend.py --aggregation daily` to get candidate timestamps, write to `/mnt/user-data/outputs/trend_data.json`
- [x] 2.3 Implement Step S1b (point type validation): read equipment component tree, extract all `type=83` points whose name does NOT contain "波形"
- [x] 2.4 Implement Step S1c (render timestep form): render `form` with `callback_id="monitor-spectrum-timestep"`, `multi-select` for points, `select` for timestamps (from trend data), with 600s timeout
- [x] 2.5 Implement Step S1 error cases: no trend data → markdown error; no type=83 points → markdown error with 8k hint

## 3. SOUL.md — Spectrum Analysis Pipeline (data fetch & visualization)

- [x] 3.1 Add "图谱时间点回调" section (`callback_id="monitor-spectrum-timestep"`): validate selected points and timestamp
- [x] 3.2 Implement Step S2a (waveform fetch): invoke `bash /mnt/skills/custom/ins-get-waveform-data/scripts/run.sh <point_id> <time_ms>` for each selected point, combine results to `/mnt/user-data/outputs/waveform_data.json`, verify output exists
- [x] 3.3 Implement Step S2b (feature extraction): invoke `bash /mnt/skills/custom/ins-extract-spectral-waveform-features/scripts/run.sh '<payload_json>'` with waveform payload, write to `/mnt/user-data/outputs/spectrum_features.json`, verify output contains required fields
- [x] 3.4 Implement Step S2c (waveform line chart): render `echart` line chart with `wave_x` × `wave_y`, downsample to ≤2000 points, include component name + timestamp in title
- [x] 3.5 Implement Step S2d (spectrum bar chart): render `echart` bar chart with `spec_x` × `spec_y`, add markLine at 1X/2X when speed available
- [x] 3.6 Implement Step S2e (feature table): render `table` with RMS, peak-to-peak, crest factor, 1X amp, 2X amp, dominant freq, clipping, drift
- [x] 3.7 Implement Step S2f (findings markdown): render `markdown` with `summary`, `spectral_findings`, `waveform_findings`, `suspected_faults` as bulleted lists
- [x] 3.8 Implement Step S3 (orbit optional): render `markdown` offering orbit analysis for equipment with type=70 bearings; on user confirmation, invoke `ins-get-orbit-data` + `ins-extract-orbit-centerline-features`, render `echart` scatter chart
- [x] 3.9 Implement INS error propagation: all `HttpProviderError` surfaced as `markdown` errors, no silent demo fallback
- [x] 3.10 Implement data insufficiency checks: <8 wave_y points → markdown warning, skip chart; empty spectrum → markdown warning

## 4. SOUL.md — Anomaly Pipeline Spectrum Entry Point

- [x] 4.1 After anomaly summary table (Step A4 area), add conditional block: when ≥1 anomaly found, render `markdown` listing top 3 anomaly timestamps and suggesting spectrum analysis re-run

## 5. SOUL.md — Report Export (spectrum data in monitoring_features.json)

- [x] 5.1 In report export section, add `spectrum_data` field assembly: include chart_options, feature_details, findings in `monitoring_features.json`
- [x] 5.2 Verify existing `export_report.write_report` handles `spectrum_data` field without errors (existing render_monitoring_markdown should gracefully handle unknown fields)

## 6. Config Update

- [x] 6.1 Add spectrum-related starter to `config.yaml` starters list: `{"label": "波形频谱分析", "prompt": "分析设备波形频谱特征", "auto_start": false}`

## 7. Testing

- [x] 7.1 Update `test_soul_has_enum_validation` to include `spectrum` in expected analysis_type values
- [x] 7.2 Write test: `test_soul_has_spectrum_pipeline_section` — verify "图谱分析流水线" section exists and mentions `ins-get-waveform-data` and `ins-extract-spectral-waveform-features`
- [x] 7.3 Write test: `test_soul_has_spectrum_timestep_callback` — verify `monitor-spectrum-timestep` callback_id in SOUL.md
- [x] 7.4 Write test: `test_soul_has_spectrum_echart_rendering` — verify waveform line chart + spectrum bar chart rendering instructions in SOUL.md
- [x] 7.5 Write test: `test_soul_has_orbit_optional` — verify optional orbit analysis flow present
- [x] 7.6 Write test: `test_soul_has_anomaly_spectrum_entry` — verify anomaly pipeline includes spectrum drill-down suggestion
- [x] 7.7 Write test: `test_soul_has_8k_validation` — verify SOUL.md enforces type=83 check and 8k-only limitation
- [x] 7.8 Write test: `test_config_has_spectrum_starter` — verify config includes spectrum starter
- [x] 7.9 Verify existing 31 monitoring tests still pass after all changes
