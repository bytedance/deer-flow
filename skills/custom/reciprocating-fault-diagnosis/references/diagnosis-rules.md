# Reciprocating Diagnosis Rules Reference

> **占位规则版本：v0.1 · 2026-05-18 · Story S2-1 placeholder**
> Source: 占位规则，依据通用往复机故障诊断手册（API 618 / ISO 13373 / 设备 OEM 故障树）拼装而成，**不替代 OEM 标准**。S1 阶段仅用于打通 `fault-diagnosis--reciprocating` 端到端链路；S2 之后由领域专家逐条评审现场样本。

Use this file as the detailed rule base after `reciprocating-fault-diagnosis` skill is triggered. Match observations against the corresponding equipment kind and fault family, then inherit the associated key features, typical features, and recommended actions.

## Equipment kind coverage

- 往复式压缩机（含多缸 / 多级 / 单作用 / 双作用）— `reciprocating_compressor`
- 往复式泵 — `reciprocating_pump`

## Supported fault families

- 阀门故障 — `valve_failure`（subtype: suction / discharge）
- 活塞环磨损 — `piston_ring_wear`
- 十字头敲缸 — `crosshead_knock`
- 连杆轴承间隙过大 — `connecting_rod_clearance`
- 活塞杆下沉 — `piston_rod_droop`
- 缸压异常 — `cylinder_pressure_anomaly`
- 卸荷阀异常 — `unloader_anomaly`
- 轴承损伤 — `bearing_damage`
- 不对中 — `misalignment`
- 共振 — `resonance`
- 电机端联动 — `motor_coupling`

## Crank-angle aligned feature index

> 往复机故障判据强依赖曲轴角窗口；如下索引按"冲击出现的曲轴角位置"快速定位候选故障家族。

### 1) Impulse near suction valve closing angle

Check among:

- 阀门故障（吸气阀卡 / 片碎 / 密封不严）
- 缸压异常（吸气过程压力曲线偏移）

### 2) Impulse near discharge valve opening angle

Check among:

- 阀门故障（排气阀卡 / 密封不严）
- 缸压异常（排气过程压力曲线偏移）

### 3) Sharp impulse mid-stroke (远离 TDC / BDC)

Check among:

- 十字头敲缸（连杆 / 十字头销间隙）
- 连杆轴承间隙过大（大端 / 小端）

### 4) Cylinder pressure peak attenuation, suction/discharge OK

Check among:

- 活塞环磨损（缸内漏气率上升）
- 阀门故障（关闭不严但未明显错位）

### 5) Persistent rod droop trend

Check among:

- 活塞杆下沉（rider band 磨损）
- 缸压异常（叠加磨损）

### 6) 1X / 2X dominant on frame, cylinder pressure normal

Check among:

- 不对中（联端突出）
- 共振（机座 / 管线 / 缓冲罐）

---

## Rule summaries by equipment kind

## 往复式压缩机

### 阀门故障 - 吸气阀（rule id: `recip-suction-valve-r1`）

- Context: steady load operation, suction pressure normal, single-cylinder anomaly.
- Core signs:
  - 缸盖振动在**吸气阀关闭角附近**（曲轴角 ~150°-180°，按曲轴方向标定）出现冲击
  - 缸内压力曲线在吸气过程末段偏离健康基线（提前关闭 → 压力骤降；密封不严 → 压力波动）
  - 阀盖表面温度（如配仪）异常上升
  - 排气压力 / 出口流量 持续小幅下降
  - 单缸异常，未传播到其他缸
- Strong discriminator:
  - PV 图在吸气阀关闭角附近的"压差跃变"形状改变最明显
- Actions:
  - 计划停机检查吸气阀（卡片 / 片碎 / 弹簧 / 阀座密封）
  - 短期：监控其他缸是否扩散，必要时降负荷运行
  - 长期：检查阀片材质 / 弹簧寿命 / 工况是否长期超出阀门设计窗口

### 活塞环磨损（rule id: `recip-piston-ring-r1`）

- Context: long-period operation; symptoms show up gradually.
- Core signs:
  - 缸内压力**峰值**逐周期 / 逐月衰减
  - 吸气压力 / 排气压力 设定值正常但实际输出能力下降
  - 阀盖温度可能小幅上升（漏气）
  - 漏气率 / blow-by 测量值（如配仪）持续上升
  - 单缸或多缸缓慢同步劣化
- Strong discriminator:
  - 同时排除阀门故障后，**缸压峰值**仍显著低于历史基线
- Actions:
  - 计划停机检查活塞环（磨损量 / 端部间隙 / 凹槽磨损）
  - 检查气缸内壁拉伤 / 腐蚀
  - 评估润滑油牌号 / 加油量是否合适

### 十字头敲缸（rule id: `recip-crosshead-knock-r1`）

- Context: steady load; impulses appear repeatably each cycle.
- Core signs:
  - 曲轴箱 / 机座振动出现**周期性冲击**，曲轴角窗口固定在中段（远离 TDC / BDC）
  - 冲击幅值 > 周围背景值至少 3 倍
  - 缸内压力曲线**正常**（与磨损 / 阀门故障的关键区分）
  - 噪声升高 / 听感金属敲击
  - 同一组连杆 / 十字头的冲击通道一致；其他缸正常
- Strong discriminator:
  - 降负荷后冲击仍在；停车后冲击消失，**重启后立即重现**（与轴承故障的渐变特征不同）
- Actions:
  - **立即降负荷或停车**，避免连杆螺栓 / 轴瓦剧烈损坏
  - 停机检查十字头销 / 连杆瓦 / 螺栓预紧力
  - 检查润滑油牌号 / 油压

### 阀门故障 - 排气阀

> 占位 — 待 S2 后领域专家补现场样本规则。Context: 单缸排气阀关闭不严 → 排气压力 / 出口流量下降 + 排气阀附近曲轴角出现冲击。

### 连杆轴承间隙过大

> 占位 — 待 S2。subtype: 大端 / 小端；曲轴角窗口冲击 + 油压 / 油温联动。

### 活塞杆下沉

> 占位 — 待 S2。Core signs: rod droop 测量值持续上升，工况不变；rider band 磨损。

### 缸压异常

> 占位 — 待 S2。Core signs: PV 图偏离健康基线但未明确归因到阀门 / 活塞环。

### 卸荷阀异常

> 占位 — 待 S2。Core signs: 卸荷阀开合时序与配置 profile 错位；负荷阶跃响应异常。

### 轴承损伤

> 占位 — 待 S2。Core signs: 主轴瓦温度 / 油压 异常；曲轴箱振动滚动轴承特征频率（少见，主要是滑动轴承）。

### 不对中

> 占位 — 待 S2。Core signs: 联端 1X 主导 + 缸压正常；启动后变化稳定。

### 共振

> 占位 — 待 S2。Core signs: 某固有频率附近振级峰值；改变转速 / 缓冲罐参数后峰值移动。

### 电机端联动

> 占位 — 待 S2。Core signs: 电流谐波（2× 工频边带）+ 启停冲击；与机械端关联但根因在电机。

---

## 往复式泵

### 通用规则

> 占位 — 容积式往复泵规则在 S2 之后由领域专家补充。
> Note: 往复泵以**吸入特性 + 排出特性 + 阀门事件**为主；规则体系与往复压缩机相似但各项阈值不同，不要套用压缩机判据。

---

## Cross-cylinder / cross-stage evidence rules

When data spans multiple cylinders or stages, use these to localize root cause:

| 现象 | 单缸 / 单级 | 多缸 / 多级同步 | 多缸 / 多级不同步 |
| ---- | ---- | ---- | ---- |
| 阀门故障 | 是（典型） | 罕见（须排除安装批次问题） | 否 |
| 活塞环磨损 | 是 | 多缸同步缓慢劣化（润滑 / 介质问题） | 否 |
| 十字头敲缸 | 是（特定连杆 / 十字头） | 否 | 否 |
| 不对中 | 否 | 联端 / 联端组同步 | 否 |
| 卸荷阀异常 | 是 | 共用控制气源 | 是（独立气源失灵） |
| 电机端联动 | 否 | 全机一致 | 否 |

---

## Reporting rules

- 必须明确报告"哪一缸 / 哪一级 / 哪一个阀"，不要只写"压缩机异常"。
- 若 PV 图缺失，主诊断只能给到"倾向于 / 疑似"，不能给确定结论。
- 若曲轴角参考缺失（无编码器 / 无标记），整个报告退化为"基于时域趋势的初判"，不能给阀门 / 缸压相关结论。
- 在 §5 差异诊断中至少写 1 条"为什么不是 X"；阀门故障 vs 活塞环磨损是最常见的差异点。
- 占位规则被命中时，报告须显式说明"基于占位规则 v0.1，待领域专家评审"。
