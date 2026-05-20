# Static Equipment Corrosion Diagnosis Rules Reference

> **占位规则版本：v0.1 · 2026-05-20 · OpenSpec change `wire-equipment-reports-real-data` §11.4 placeholder**
> Source: 占位规则，依据通用静设备腐蚀监测手册（API 570 / ASME B31G / 行业经验值）拼装而成，**不替代 OEM 标准或法规**。本阶段仅用于打通 6K 静设备腐蚀诊断端到端链路；落地前由领域专家逐条评审现场样本。

Use this file as the detailed rule base after `static-equipment-corrosion-diagnosis` skill is triggered. Match observations against the corresponding equipment kind and fault family, then inherit the associated key features, typical features, and recommended actions.

## Equipment kind coverage

- 管线段 — `pipeline_segment`
- 压力容器 — `pressure_vessel`
- 塔器 — `column_tower`

## Supported fault families

- 腐蚀速率异常 — `corrosion_rate_anomaly`
- 剩余寿命不足 — `thickness_remaining_life`
- 减薄率突变 — `thinning_rate_step_change`
- 工艺温度耦合 — `process_temperature_coupling`（耦合标记；通常作为其它族的关联证据，亦可独立提示）

## Cross-equipment quick index

### 1) corrosionRate baseline elevated, thickness drifting

Check among:

- 腐蚀速率异常（材料 / 介质腐蚀环境恶化）
- 减薄率突变（窗口比对显示加速期）

### 2) Remaining wall thickness approaching design min

Check among:

- 剩余寿命不足（线性外推 < 2 年）

### 3) Thinning rate jumps with temperature swing

Check among:

- 减薄率突变（耦合 process_upset）
- 工艺温度耦合（无突变时单独标记）

### 4) Offline-only inspection points

Check among:

- 通过历史 UT / RT 趋势比对，不适用 6K 在线规则

---

## Rule summaries by equipment kind

## 管线段

### 腐蚀速率异常（rule id: `static-corrosion-rate-r1`）

- Context: long-running pipeline segment carrying 含硫 / 含氯 / 高温含氢 介质，or after process feed change.
- Thresholds (行业经验，需现场标定)：
  - `corrosionRate ≤ 0.1 mm/y` → 低，无需告警
  - `0.1 < corrosionRate ≤ 0.25 mm/y` → 中，挂"观察"标签
  - `0.25 < corrosionRate ≤ 0.5 mm/y` → 高，触发 `corrosion_rate_anomaly`
  - `corrosionRate > 0.5 mm/y` → 极高，升级为 `corrosion_rate_anomaly` + `high` 优先级
- Strong discriminator:
  - 同管段多个 TH 探头读数一致 + 介质组分变化（硫 / 氯 / 水含量上升）
- Actions:
  - 复核工艺介质组分（含硫 / 含氯 / 含水）
  - 评估缓蚀剂注入策略
  - 安排离线 UT 复测点位
  - 若长期未缓解，进入材料升级评估

### 剩余寿命不足（rule id: `static-thickness-life-r1`）

- Context: any pipeline segment with an established `thinningRate` and known design minimum thickness.
- Core formula:
  - `remaining_life_years = max(0, (current_thickness - design_min_thickness)) / max(current_thinning_rate, 1e-6)`
- Threshold:
  - `remaining_life_years < 2` → 触发 `thickness_remaining_life` + `high` 优先级
  - `2 ≤ remaining_life_years < 5` → 触发 `thickness_remaining_life` + `medium` 优先级
  - `remaining_life_years ≥ 5` → 不触发
- Strong discriminator:
  - 多个 TH 点剩余寿命相近 + thinningRate 曲线无突变 → 稳态磨损，预测可信
  - 若 thinningRate 在最近窗口才上升，剩余寿命估算需配合 `thinning_rate_step_change` 解读
- Actions:
  - 列入下一次大修壁厚复测优先级
  - 准备焊补 / 衬里 / 换管方案
  - 复核设计最小壁厚是否仍适用（介质 / 温度变化后可能需要降级）

### 减薄率突变（rule id: `static-thinning-step-r1`）

- Context: pipeline segment where `thinningRate` time series shows a window-after / window-before ratio above the threshold.
- Window comparison:
  - 默认窗口长度：30 天
  - 比值：`mean(thinningRate, last 30 d) / mean(thinningRate, prior 30 d)`
  - `ratio > 1.5` → 触发 `thinning_rate_step_change`
  - `ratio > 3.0` → 升级为 `high` 优先级
- Strong discriminator:
  - 同时刻 `temperature` 同向上升 → 推 `process_upset` linkage
  - 同时刻 `temperature` 平稳 → 推 `material_change` / `instrument_drift`，需先排查传感器
- Actions:
  - 拉取同期工艺数据（温度 / 压力 / 流量 / 介质组分）
  - 排查仪表（探头漂移 / 接地异常）
  - 若证实是工艺扰动，联动操作组调整温度 / 注水 / 注剂

### 工艺温度耦合（rule id: `static-temperature-coupling-r1`）

- Context: 6K 测点同时包含 `temperature` 与 `thinningRate` 时序，且二者在观察窗口表现同向变化。
- Criteria：
  - 同观察窗口（默认 7 d）`temperature` 与 `thinningRate` 的相关系数 > 0.6 → 触发 `process_temperature_coupling`
  - 不作为独立优先级；通常作为 `corrosion_rate_anomaly` 或 `thinning_rate_step_change` 的关联证据
- Strong discriminator:
  - 工艺工况切换记录可对应温度阶跃
- Actions:
  - 与生产 / 工艺组确认工况切换原因
  - 若可控，建议设置温度上限并联动告警

## 压力容器

> 上述 4 条占位规则同样适用，但需要补充：
>
> - 容器顶 / 中 / 底位置点的腐蚀差异（多相介质常见）
> - 内附件（折流板 / 喷淋）冲蚀作为差异化诊断
> - 不连续在线监测时，依赖每年至少一次的全面 UT 网格

## 塔器

> 上述 4 条占位规则同样适用，但需要补充：
>
> - 塔顶 / 塔底 / 进料段腐蚀机理差异（露点腐蚀 / 高温硫腐蚀 / 多胺中和腐蚀）
> - 多层托盘 / 填料段对应的 TH 探头通常按塔段编号
> - 联动 process_temperature_coupling 时优先考虑塔顶冷凝段
