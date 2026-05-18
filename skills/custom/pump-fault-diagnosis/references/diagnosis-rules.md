# Pump Diagnosis Rules Reference

> **占位规则版本：v0.1 · 2026-05-18 · Story S1-3 placeholder**
> Source: 占位规则，依据通用机泵故障诊断手册（API 610 / ISO 10816 / 设备 OEM 故障树）拼装而成，**不替代 OEM 标准**。S1 阶段仅用于打通 `fault-diagnosis--pump` 端到端链路；S2 之后由领域专家逐条评审现场样本。

Use this file as the detailed rule base after `pump-fault-diagnosis` skill is triggered. Match observations against the corresponding equipment kind and fault family, then inherit the associated key features, typical features, and recommended actions.

## Equipment kind coverage

- 离心泵（含单级 / 多级）— `centrifugal_pump`
- 容积泵（往复 / 螺杆 / 齿轮）— `positive_displacement_pump`

## Supported fault families

- 不平衡 — `unbalance`
- 不对中 — `misalignment`
- 轴承损伤 — `bearing_damage`
- 汽蚀 — `cavitation`
- 密封泄漏 — `seal_leakage`
- 叶轮磨损 / 腐蚀 — `impeller_wear`
- 流量低于最小连续流量 — `min_flow_violation`
- 共振 — `resonance`
- 电机端联动 — `motor_coupling`

## Cross-equipment quick index

### 1) 1X dominant, sinusoidal, speed-synchronous

Check among:

- 不平衡（叶轮残余不平衡 / 积垢）
- 不对中（联端突出）
- 共振（若同时与某固有频率重合）

### 2) Broadband + impulsive waveform + process linkage

Check among:

- 汽蚀（NPSH 余量缩小 / 流量异常）
- 流量低于最小连续流量（再循环阀失效）

### 3) Vane-pass-frequency (VPF) prominent

Check among:

- 叶轮磨损 / 腐蚀
- 内部再循环

### 4) Rolling-element-bearing characteristic frequencies

Check among:

- 滚动轴承损伤（外环 BPFO / 内环 BPFI / 滚珠 BSF / 保持架 FTF）

### 5) Seal flush anomaly + vibration rise

Check among:

- 机械密封泄漏 / 填料密封磨损

---

## Rule summaries by equipment kind

## 离心泵

### 不平衡（rule id: `pump-unbalance-r1`）

- Context: long-period steady operation, or after impeller replacement / cleaning.
- Core signs:
  - DE & NDE both moderately high (typically pp > 5.6 mm/s for ISO 10816 class II pumps, threshold 由现场标定)
  - mainly 1X, phase relatively stable over time
  - waveform near sine, amplitude consistent across cycles
  - process channels (流量 / ΔP / current) stable
- Strong discriminator:
  - high-speed balancing reduces value substantially
- Actions:
  - check impeller for accumulated deposits / corrosion
  - perform high-speed balancing on next outage
  - if recently overhauled, suspect impeller residual unbalance

### 汽蚀（rule id: `pump-cavitation-r1`）

- Context: throttled / low-suction-pressure / high-temperature service near vapor pressure.
- Core signs:
  - broadband vibration rise (10 kHz +)
  - waveform shows random impulsive bursts
  - **NPSH 余量** 缩小到设计裕度以下
  - 出口压力 / 流量 出现脉动
  - 噪声升高 / 流体闷响
- Strong discriminator:
  - 提高吸入压力或降低液体温度后振动立即下降
- Actions:
  - 检查吸入管路阻力（过滤器是否堵塞）
  - 提高液位 / 降低液温
  - 评估操作工况是否长期低于最低连续流量
  - 长期未解决需检查叶轮汽蚀损伤情况

### 流量低于最小连续流量（rule id: `pump-min-flow-r1`）

- Context: 泵长时间运行在 BEP 流量的 30% 以下。
- Core signs:
  - 宽频振动随流量下降而升高
  - 出口压力 / 流量 脉动加剧
  - 电机电流低于额定值但伴随振动上升（与负荷上升导致的电流上升不同）
  - 再循环阀（最小连续流量阀）状态异常或未开启
- Strong discriminator:
  - 强制开启再循环阀后振动 / 压力脉动恢复正常
- Actions:
  - 检查再循环阀控制逻辑与开启信号
  - 检查工艺需求是否长期偏离设计点
  - 长期未解决需评估泵选型与多级串并联方案

### 不对中

> 占位 — 待 S2 后领域专家补现场样本规则。Context: 联端通道 1X 主导、长期稳定，启动后不变。

### 轴承损伤

> 占位 — 待 S2。subtype: 滚动 BPFO / BPFI / BSF / FTF；滑动 间隙过大 / 软脚。

### 密封泄漏

> 占位 — 待 S2。Core signs: 冲洗 ΔP / 温度漂移 + 振动小幅上升。

### 叶轮磨损 / 腐蚀

> 占位 — 待 S2。Core signs: VPF 谱线变化；输送性能下降。

### 共振

> 占位 — 待 S2。Core signs: 某固有频率附近振级峰值，转速漂移时峰值随之移动。

### 电机端联动

> 占位 — 待 S2。Core signs: 电流谐波（2× 工频边带，断条特征）+ 振动相关上升。

---

## 容积泵

### 通用规则

> 占位 — 容积泵规则在 S2 之后由领域专家补充。
> Note: 容积泵以脉动振动为主，规则需独立于离心泵；不要套用离心泵 1X / VPF 判据。

---

## Process linkage evidence rules

When process variables are available, use them to corroborate or rule out fault families:

| 工艺通道 | 上升 | 下降 | 关联故障家族 |
| ---- | ---- | ---- | ---- |
| 出口压力 | 振动同步上升且伴随脉动 | — | `cavitation` / `min_flow_violation` |
| 入口压力 | — | 振动上升 + NPSH 缩小 | `cavitation` |
| 流量 | — | 振动上升 + 脉动 | `min_flow_violation` |
| 电机电流 | 振动同步上升（高频谐波） | — | `motor_coupling` |
| 密封冲洗 ΔP / 温度 | 异常漂移 | — | `seal_leakage` |

---

## Reporting rules

- 若 trend + spectrum 支持判定但工艺联动证据缺失，用「倾向于 / 疑似」。
- 若 spectrum + 工艺联动 + 操作工况一致，可给主诊断结论。
- 若关键判别证据缺失，明确写出"缺什么数据 / 待补什么测点"。
- 在 §5 差异诊断中至少写 1 条"为什么不是 X"。
- 占位规则被命中时，报告须显式说明"基于占位规则 v0.1，待领域专家评审"。
