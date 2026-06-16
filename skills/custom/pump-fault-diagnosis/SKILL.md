---
name: pump-fault-diagnosis
description: Industrial pump (centrifugal / positive displacement) fault diagnosis using vibration + flow + pressure + motor current correlation. Use when the user wants a one-off or repeatable diagnosis for 离心泵 / 多级离心泵 / 容积泵, including trend review, waveform/spectrum analysis, process linkage checks (NPSH / min-flow / discharge pressure), motor-side correlation, rule matching, and structured fault reports.
metadata:
  emoji: "💧"
---

# Pump Fault Diagnosis

Use this skill to diagnose pump faults with the managed Deer Flow pump rule runtime. The Agent input contract matches rotating machinery diagnosis: select one pump device + sub-device, select one diagnosis hour, then run the rule runtime.

## Managed Runtime

Authoritative runtime entrypoints:

- `scripts/run_pump_rule_diagnosis.py`
- `scripts/build_pump_report_payload.py`
- `scripts/export_report.py` — 报告导出（md/pdf）
- `scripts/export_diagnosis_report.py` — 诊断报告 Markdown 渲染

### 2K 系列数据工具（机泵）

- `scripts/device_analysis_2k_tool.py` — 机泵设备树分析 (positionType 22..30)
- `scripts/get_trend_data_2k_tool.py` — 机泵趋势数据获取
- `scripts/extract_trend_features_2k_tool.py` — 机泵趋势特征提取

## Dependencies

- `features-tool` skill — 提供 `ins/` (InS API 客户端)、`agents/` (function_tool) 等公共模块
- `rotating-fault-diagnosis` skill — 2K 脚本依赖 8K 脚本的函数

**IMPORTANT: CLI argument rules**

When invoking `run_pump_rule_diagnosis.py`, you MUST:
- Pass `--diagnosis-time` with the user-selected diagnosis hour (e.g. `"2026-05-24T08:00:00"`)
- **Do NOT pass `--start-time` or `--end-time`**. The runtime automatically computes a 24-hour window ending at `diagnosis_time`. Passing explicit start/end overrides this logic with a narrow 1-hour window, resulting in empty trend data.

Example correct invocation:
```
python /mnt/skills/custom/pump-fault-diagnosis/scripts/run_pump_rule_diagnosis.py \
  --machine-id "241212010001718" \
  --component-id "703030976116162560" \
  --component-name "风机" \
  --diagnosis-time "2026-05-24T08:00:00" \
  --output /mnt/user-data/outputs/pump_rule_result.json
```

Runtime package:

- `/mnt/skills/custom/features-tool/pump_rule` in sandbox
- `skills/custom/features-tool/pump_rule` in the repository

Required runtime environment:

- `INS_ACCESS_TOKEN`: current user Bearer token injected by Deer Flow runtime
- `INS_BASE_URL`: optional deployment-level InS base URL

The managed runtime does not evaluate start-stop state and never skips vibration diagnosis because of startup/shutdown status.

## Workflow

**Device type policy**: Do NOT check or restrict by device type (e.g. type=50 for fans, type=4 for pumps). If the selected sub-device has vibration measurement points, execute the diagnosis flow regardless of device classification.

1. Confirm the target device, selected sub-device, and diagnosis hour.
2. Determine target context from `/ins-os-manage/organize/getComponentByMachineIds?operateType=1&machineIds={machineId}` by expanding the selected `componentId`; vibration points are `unitType=3` rows whose `type` is `23`, `24`, `26`, or `27`. Use `getPointConfigs` only as a fallback when the component tree cannot provide points.
3. Use the plant inspection toolchain first to locate the pump, inspect component hierarchy, and identify related points:
   - shaft vibration X/Y at drive end and non-drive end (or housing vibration on small pumps)
   - suction / discharge pressure
   - flow rate (and rated min-flow if known)
   - motor current / power
   - bearing temperatures if available
   - seal flush pressure / temperature if instrumented
4. Build an evidence chain in this order unless data is missing:
   - overall trend and alarm behavior (vibration, current, ΔP)
   - vibration spectrum dominant components (1X / 2X / vane-pass-frequency / broadband)
   - waveform shape (sine / clipped / impulsive / random)
   - process correlation (flow vs ΔP, NPSH margin, recirculation valve state)
   - motor-side correlation (current harmonics, torque pulsation)
   - bearing / seal temperature corroboration
5. Match observed behavior against the managed runtime output first; use `references/diagnosis-rules.md` as explanatory reference material only.
6. Output a structured conclusion with:
   - pump info (tag, kind, service)
   - selected sub-device
   - abnormal points
   - evidence
   - primary diagnosis
   - alternative diagnoses / exclusions
   - confidence
   - operation advice
   - maintenance advice

## Required diagnostic style

- Prefer evidence-based language.
- If evidence is incomplete, give a tendency diagnosis rather than pretending certainty.
- Distinguish clearly between:
  - confirmed by current evidence
  - likely / suspected
  - not supported by current data
- Do not force a diagnosis when only one feature matches weakly.
- For pumps, process variables (flow / ΔP / current) are useful supporting evidence when available, but the managed runtime can still produce a vibration-only rule result when process channels are unavailable.

## Rule matching guidance

Read `references/diagnosis-rules.md` and match by:

- equipment kind (centrifugal vs positive displacement)
- fault family / subtype
- required chart types (trend / spectrum / waveform / orbit / process)
- time window context
- key features
- typical features
- recommended actions

When several fault families seem plausible, rank by how well they explain the full set of observations:

1. operating-point fit (BEP / off-design)
2. dominant frequency features (1X / 2X / vane-pass-frequency / broadband)
3. process linkage strength (flow / NPSH / current move together?)
4. waveform morphology (impulsive vs steady)
5. multi-channel consistency (DE vs NDE)
6. temperature / seal corroboration

## Practical heuristics

Apply these heuristics while using the rule base:

- If broadband vibration rises specifically when **flow drops below min-flow** while suction pressure is normal, prefer **min_flow_violation / cavitation** over bearing damage.
- If 1X is dominant and the pump has been recently overhauled with a new impeller, prefer **unbalance** (impeller residual unbalance) over wear.
- If 1X is dominant on coupling-side channels of both connected machines (motor + pump), prefer **misalignment**.
- If broadband + impulsive (random burst) waveform appears together with **discharge pressure pulsation** and **NPSH margin shrinking**, consider **cavitation**.
- If vane-pass frequency (VPF = blade count × 1X) becomes prominent with stable flow, consider **impeller_wear** or recirculation; correlate with motor current trend.
- If motor current shows characteristic harmonics (2× line-frequency sidebands, broken-rotor-bar signature) coincident with vibration rise, escalate to `motor_coupling`.
- If bearing temperature climbs progressively while vibration is still mid-range, consider **bearing_damage** (lubrication / wear) before bearing assembly issues.
- If a fixed structural frequency near operating speed dominates and disappears when speed shifts, consider **resonance** (foundation / piping / coupling guard).
- If seal flush ΔP / temperature drift coincident with vibration rise, consider **seal_leakage**.

## Output template

Use a concise report structure (aligned with vibration-fault-diagnosis skill):

### 1. Machine and task

- pump tag and service (e.g. P-101A, raw water transfer)
- equipment kind (centrifugal / positive displacement)
- diagnosis window
- current operating regime

### 2. Key abnormal findings

- abnormal points (DE/NDE vibration, current, ΔP, etc.)
- maximum values and timestamps
- alarm status

### 3. Evidence chain

- trend evidence (vibration / current / pressure / flow)
- spectrum evidence
- waveform evidence
- process linkage evidence (flow vs ΔP, NPSH, recirculation)
- motor-side evidence
- temperature / seal evidence

### 4. Diagnosis

- primary fault family / subtype
- confidence: high / medium / low
- why it matches

### 5. Differential diagnosis

- alternative candidates
- why they are weaker
- what data is still missing

### 6. Recommendations

- operation recommendations (e.g. open recirculation valve, raise suction pressure)
- maintenance recommendations (e.g. inspect impeller / mechanical seal / coupling)

## Tooling notes

If the request is specifically about browsing pump trees, trends, waveforms, spectra, or shaft orbit in the plant system, first use the plant inspection workflow already available in the workspace (ins-* skills). This skill adds the diagnosis logic and reporting standard on top of that data access.

For pumps with **no shaft proximity probes** (typical in small / dry-running pumps), shaft orbit / centerline checks are not applicable; rely on housing vibration spectrum + process linkage instead. Mark "orbit not applicable" explicitly in §3 evidence chain rather than fabricating orbit findings.

## References

- Main rule base: `references/diagnosis-rules.md`
- Cross-reference: rotating-machinery diagnosis lives in `vibration-fault-diagnosis/references/diagnosis-rules.md`; if the equipment is upgraded to a multi-stage centrifugal pump that behaves more like a small compressor, prefer that skill.

## Fault family code mapping

> Source: `docs/plans/2026-05-18-fault-diagnosis-design.md` §4.4 `fd-pump-focus`. Keep both sides in sync when rules evolve.

| code | references 章节中文 | 说明 |
| ---- | ---- | ---- |
| `unbalance` | 不平衡 | 1X 主导 + 长期稳定；新换叶轮后残余不平衡常见 |
| `misalignment` | 不对中 | 联端突出 + 1X 主导 |
| `bearing_damage` | 轴承损伤 | subtype 在报告内细化（滚动外/内/球/保持架；滑动间隙 / 装配） |
| `cavitation` | 汽蚀 | 宽频 + 冲击波形 + NPSH / 流量联动 |
| `seal_leakage` | 密封泄漏 | 机械 / 填料密封；冲洗 ΔP / 温度漂移 |
| `impeller_wear` | 叶轮磨损 / 腐蚀 | 叶片通过频率（VPF）变化 |
| `min_flow_violation` | 流量低于最小连续流量 | 流量降至最小连续流量以下 + 宽频上升 |
| `resonance` | 共振 | 基础 / 管线 / 转速带共振 |
| `motor_coupling` | 电机端联动 | 电流谐波 / 转矩脉动 / 启停冲击 |

When LLM produces a primary diagnosis, use the `code` value verbatim in any structured output (e.g. `diagnosis_features.json.rule_matches[].fault_family`); use the Chinese name in human-facing narrative.

## Status

Managed rule runtime is the authoritative path for `fault-diagnosis--pump`. The Markdown rule reference remains for human explanation and fallback documentation; it is no longer the authoritative matcher for the Agent's formal conclusion.
