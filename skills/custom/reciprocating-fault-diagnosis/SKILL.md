---
name: reciprocating-fault-diagnosis
description: Reciprocating compressor / pump fault diagnosis using crank-angle aligned vibration + cylinder pressure + valve event correlation. Use when the user wants a one-off or repeatable diagnosis for 往复式压缩机 / 往复式泵, including trend review, valve event analysis, cylinder pressure waveform, crank-angle aligned impulse checks, motor-side correlation, rule matching, and structured fault reports.
metadata:
  emoji: "🔧"
---

# Reciprocating Fault Diagnosis

Use this skill to diagnose reciprocating-machinery faults with the user's rule base, plant inspection toolchain, and crank-angle aligned analysis.

## Workflow

1. Confirm the target reciprocating machine, time window, operating regime (steady / startup / shutdown / load step), and whether the user wants a one-off diagnosis or a quick screening.
2. Determine equipment kind (`reciprocating_compressor` / `reciprocating_pump`) from naming and available measurements.
3. Use the plant inspection toolchain first to locate the machine, inspect cylinders and stages, and identify key channels:
   - crank-angle reference (encoder or marker)
   - cylinder pressure (per cylinder, per stage)
   - cylinder head vibration (per cylinder)
   - crankcase / frame vibration
   - piston rod droop (per cylinder)
   - valve cover surface temperatures (per valve, if instrumented)
   - unloader valve state (if instrumented)
   - motor current / power
4. Judge operating condition before fault typing:
   - steady at rated load
   - load step (capacity control via unloader)
   - startup ramp / coastdown
   - blowdown / emergency stop
5. Build an evidence chain in this order unless data is missing:
   - overall trend and alarm behavior (vibration, current, valve cover temperature)
   - **crank-angle aligned vibration** (impulse window per cycle)
   - cylinder pressure curve (PV diagram, peak / minimum / discharge angle)
   - valve event timing (opening / closing crank angles vs nominal)
   - motor current harmonic / pulsation
   - bearing / valve cover temperature corroboration
6. Match observed behavior against the bundled rule reference at `references/diagnosis-rules.md`.
7. Output a structured conclusion with:
   - machine info (tag, kind, stages)
   - operating condition
   - abnormal points (which cylinder / which valve / which crank angle window)
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
- For reciprocating machines, **crank-angle aligned features carry equal weight to vibration trend / spectrum**; ignore conclusions that rely only on time-domain RMS without crank-angle context.

## Rule matching guidance

Read `references/diagnosis-rules.md` and match by:

- equipment kind (compressor vs pump)
- fault family / subtype (suction valve vs discharge valve, head end vs crank end, etc.)
- required chart types (trend / crank-angle waveform / cylinder pressure / valve event)
- time window context
- key features
- typical features
- recommended actions

When several fault families seem plausible, rank by how well they explain the full set of observations:

1. operating-load fit (rated / unloaded / throttled)
2. crank-angle window where impulses appear (suction TDC / BDC / mid-stroke)
3. cylinder pressure curve deviation from healthy baseline
4. valve event timing offset
5. multi-cylinder / multi-stage consistency
6. motor / temperature corroboration

## Practical heuristics

Apply these heuristics while using the rule base:

- If crank-angle aligned vibration shows **impulse near suction valve closing angle** with cylinder pressure showing premature closure, prefer **valve_failure (suction)**.
- If discharge pressure drops simultaneously with vibration rise on cylinder head, prefer **valve_failure (discharge)**.
- If cylinder pressure peak drops over time while suction / discharge pressures are normal, consider **piston_ring_wear** (blow-by).
- If a sharp impulse appears mid-stroke (away from valve angles) with periodic timing locked to crank angle, consider **crosshead_knock**.
- If piston rod droop measurement increases monotonically while load is constant, consider **piston_rod_droop** (rider band wear).
- If unloader valve opens / closes at angles different from configured profile, consider **unloader_anomaly**.
- If 1X / 2X spectral content rises with stable cylinder pressure, consider **misalignment** or **resonance** before assuming cylinder-side issue.
- If motor current harmonics rise coincident with vibration, escalate to `motor_coupling`.

## Output template

Use a concise report structure (aligned with vibration-fault-diagnosis skill):

### 1. Machine and task

- machine tag (e.g. K-301, multi-stage CO₂ compressor)
- equipment kind (reciprocating compressor / pump)
- diagnosis window
- current operating regime

### 2. Key abnormal findings

- abnormal cylinders / valves / crank-angle windows
- maximum values and timestamps
- alarm status

### 3. Evidence chain

- trend evidence (vibration / current / valve cover temperature)
- crank-angle aligned vibration evidence
- cylinder pressure evidence (PV diagram deviation)
- valve event evidence (opening / closing angle offsets)
- motor-side evidence
- temperature evidence

### 4. Diagnosis

- primary fault family / subtype (which cylinder / which valve)
- confidence: high / medium / low
- why it matches

### 5. Differential diagnosis

- alternative candidates
- why they are weaker
- what data is still missing (e.g. PV diagram absent → cannot finalize valve_failure subtype)

### 6. Recommendations

- operation recommendations (e.g. unload affected cylinder, reduce load)
- maintenance recommendations (e.g. inspect specific valve, measure rod droop, replace piston ring)

## Tooling notes

If the request is specifically about browsing reciprocating-machine trees, trends, waveforms, spectra, or cylinder pressure in the plant system, first use the plant inspection workflow already available in the workspace (ins-* skills). This skill adds the diagnosis logic and reporting standard on top of that data access.

For reciprocating machines, **shaft orbit / centerline analysis is not the primary path** (radial probes are atypical on small-bore reciprocating units; high-speed integrals are dominated by crosshead inertia rather than shaft orbit). Mark "orbit not applicable" explicitly in §3 evidence chain rather than fabricating orbit findings.

When the data source lacks a crank-angle reference (no encoder, no marker), state this in §3 explicitly and degrade conclusions to "tendency only".

## References

- Main rule base: `references/diagnosis-rules.md`
- Cross-reference: rotating-machinery diagnosis lives in `vibration-fault-diagnosis/references/diagnosis-rules.md`; pump diagnosis in `pump-fault-diagnosis/references/diagnosis-rules.md`.

## Fault family code mapping

> Source: `docs/plans/2026-05-18-fault-diagnosis-design.md` §4.4 `fd-reciprocating-focus`. Keep both sides in sync when rules evolve.

| code | references 章节中文 | 说明 |
| ---- | ---- | ---- |
| `valve_failure` | 阀门故障 | subtype 在报告内细化（吸气 / 排气；卡阀 / 片碎 / 密封不严） |
| `piston_ring_wear` | 活塞环磨损 | 缸压峰值衰减 + 漏气率上升 |
| `crosshead_knock` | 十字头敲缸 | 曲轴角中段冲击 |
| `connecting_rod_clearance` | 连杆轴承间隙 | 大端 / 小端；曲轴角窗口冲击 |
| `piston_rod_droop` | 活塞杆下沉 | 下沉量随时间增长，工况不变 |
| `cylinder_pressure_anomaly` | 缸压异常 | PV 图偏离健康基线 |
| `unloader_anomaly` | 卸荷阀异常 | 开合时序错位 |
| `bearing_damage` | 轴承损伤 | subtype 在报告内细化 |
| `misalignment` | 不对中 | 1X / 2X 谱线 + 缸压正常 |
| `resonance` | 共振 | 机座 / 管线 / 缓冲罐 |
| `motor_coupling` | 电机端联动 | 电流谐波 / 启停冲击 |

When LLM produces a primary diagnosis, use the `code` value verbatim in any structured output (e.g. `diagnosis_features.json.rule_matches[].fault_family`); use the Chinese name in human-facing narrative.

## Status

> **占位版本（2026-05-18 Story S2-1）**：本 skill 当前包含 3 条占位规则（吸气阀故障 / 活塞环磨损 / 十字头敲缸），用于 `fault-diagnosis--reciprocating` 端到端联调。完整规则评审在双 Sprint 之外作为独立工作流推进，每条规则上线前需领域专家逐条评审现场样本。
