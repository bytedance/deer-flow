---
name: static-equipment-corrosion-diagnosis
description: Static-equipment (管线 / 容器 / 塔器) corrosion diagnosis using 6K corrosion-monitoring trends (`corrosionRate` / `thinningRate` / `thickness` / `temperature`) plus process linkage data. Use when the user wants a one-off or repeatable diagnosis for pipelines / pressure vessels / columns, including corrosion-rate threshold judgment, remaining-life prediction by linear extrapolation, thinning-rate step-change detection, and process-temperature coupling checks.
metadata:
  emoji: "🛢️"
---

# Static Equipment Corrosion Diagnosis

Use this skill to diagnose corrosion-driven degradation on static equipment with the user's rule base, plant inspection toolchain, and process-variable correlation.

## Workflow

1. Confirm the target static-equipment tag (pipeline segment / vessel / column), time window, service medium (含硫 / 含氯 / 高温含氢 etc.), and whether the user wants a one-off diagnosis or a quick screening.
2. Determine equipment kind (`pipeline_segment` / `pressure_vessel` / `column_tower`) from naming and design data.
3. Use the plant inspection toolchain first to locate the equipment and identify key 6K corrosion-monitoring points:
   - `positionType=62` TH 探头 — `corrosionRate` / `thinningRate` / `thickness` / `temperature`
   - `positionType=63` P 腐蚀探针 — `corrosionRate` / `thinningRate` / `thickness`
   - `positionType=61` STA — process variables (`value`)
   - `positionType=64` OTHER_TH 离线检测 — offline thickness records
4. Judge operating condition before fault typing:
   - steady state at design corrosion rate
   - process upset (温度阶跃 / 含硫量异常 / 注水中断)
   - shutdown / inspection window (offline thickness only)
   - post-repair regime (after weld-overlay / lining / inhibitor injection)
5. Build an evidence chain in this order unless data is missing:
   - overall trend and alarm behavior (corrosionRate, thinningRate, thickness)
   - corrosion-rate threshold matching against industry empirical bands (0.1 / 0.25 / 0.5 mm/y → 中 / 高 / 极高)
   - remaining wall thickness vs. design minimum + remaining-life linear extrapolation
   - thinning-rate window comparison (last 30 d vs prior 30 d ratio)
   - process-temperature coupling (does thinning rate co-move with `temperature`?)
   - offline thickness corroboration (manual UT / RT records)
6. Match observed behavior against the bundled rule reference at `references/diagnosis-rules.md`.
7. Output a structured conclusion with:
   - equipment info (tag, kind, service medium, design min thickness)
   - operating condition
   - abnormal points
   - evidence
   - primary diagnosis (one of the 4 fault families below)
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
- For static equipment, **process variables (temperature / medium composition) carry equal weight to thickness evidence**; do not finalize a diagnosis without checking at least one process channel when available.

## Rule matching guidance

Read `references/diagnosis-rules.md` and match by:

- equipment kind (pipeline / vessel / column)
- fault family / subtype
- required chart types (thickness trend / corrosionRate trend / temperature overlay)
- time window context
- key features
- typical features
- recommended actions

When several fault families seem plausible, rank by how well they explain the full set of observations:

1. corrosion-rate band (中 / 高 / 极高)
2. remaining-life prediction (years)
3. thinning-rate step-change ratio (window before vs after)
4. process-temperature coupling strength
5. multi-channel consistency (multiple TH points on same line)
6. offline UT / RT corroboration

## Practical heuristics

Apply these heuristics while using the rule base:

- If `corrosionRate` baseline > 0.25 mm/y but `temperature` and medium composition look normal, prefer **corrosion_rate_anomaly** and start material-compatibility review.
- If remaining wall thickness ÷ current `thinningRate` < 2 years, escalate **thickness_remaining_life** to `high` priority regardless of absolute rate.
- If `thinningRate` window-after ÷ window-before > 1.5× and `temperature` simultaneously rises in the same window, prefer **thinning_rate_step_change** with `process_upset` linkage.
- If only `temperature` rises but `thinningRate` stays flat, do **not** conclude `thinning_rate_step_change`; record it as differential candidate instead.
- For offline-UT corroboration: if manual UT reading and InS `thickness` disagree by more than ±10%, mark as "data inconsistency, instrument verification required" rather than picking a side.

## Output template

Use a concise report structure (aligned with `pump-fault-diagnosis` skill):

### 1. Equipment and task

- equipment tag and service medium (e.g. P-203A 出口管段, 含 H₂S 原油)
- equipment kind (pipeline / vessel / column)
- diagnosis window
- design minimum thickness

### 2. Key abnormal findings

- abnormal points (which TH / P 探头)
- maximum / latest values and timestamps
- alarm status

### 3. Evidence chain

- corrosionRate trend evidence
- thickness remaining-life evidence
- thinningRate window comparison
- process-temperature coupling evidence
- offline UT / RT corroboration

### 4. Diagnosis

- primary fault family / subtype (one of the 4 codes below)
- confidence: high / medium / low
- why it matches

### 5. Differential diagnosis

- alternative candidates
- why they are weaker
- what data is still missing

### 6. Recommendations

- operation recommendations (e.g. lower process temperature, raise inhibitor dosage, switch loop)
- maintenance recommendations (e.g. schedule UT re-survey, plan weld-overlay, replace section)

## Tooling notes

If the request is specifically about browsing static-equipment trees and corrosion trends in the plant system, use the 6K inspection workflow first (`ins-device-analysis-6k`, `ins-extract-trend-features-6k`). This skill adds the diagnosis logic and reporting standard on top of that data access.

For equipment with **no continuous online monitoring** (typical for offline-UT-only segments), continuous trend evidence is not applicable; rely on the latest two manual UT campaigns and mark "online trend not available" explicitly in §3 evidence chain rather than fabricating trend findings.

## References

- Main rule base: `references/diagnosis-rules.md`
- Cross-reference: rotating-machinery diagnosis lives in `pump-fault-diagnosis/` and `vibration-fault-diagnosis/`; do not mix corrosion rules with rotating-machinery vibration rules.

## Fault family code mapping

> Source: OpenSpec change `wire-equipment-reports-real-data` §11.4.4. Keep both sides in sync when rules evolve.

| code | references 章节中文 | 说明 |
| ---- | ---- | ---- |
| `corrosion_rate_anomaly` | 腐蚀速率异常 | corrosionRate 超过行业经验阈值（中 0.1 / 高 0.25 / 极高 0.5 mm/y） |
| `thickness_remaining_life` | 剩余寿命不足 | 剩余壁厚 ÷ 当前减薄率 < 2 年 → 高优先级 |
| `thinning_rate_step_change` | 减薄率突变 | 后窗 ÷ 前窗 > 1.5× + 温度同步上升 → 推 process_upset |
| `process_temperature_coupling` | 工艺温度耦合 | 温度与减薄率显著同向变化（不构成单独诊断时作为耦合标记） |

When LLM produces a primary diagnosis, use the `code` value verbatim in any structured output (e.g. `diagnosis_features.json.rule_matches[].fault_family`); use the Chinese name in human-facing narrative.

## Status

> **占位版本（2026-05-20 · OpenSpec change `wire-equipment-reports-real-data` §11.4）**：本 skill 当前包含 3 条占位规则（腐蚀速率异常 / 剩余壁厚预测 / 减薄率突变 + `process_temperature_coupling` 作为耦合标记），用于 6K 静设备腐蚀诊断端到端联调。完整规则评审在 OpenSpec 主链路之外作为独立工作流推进，每条规则上线前需领域专家逐条评审现场样本。
