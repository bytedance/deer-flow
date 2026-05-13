# Diagnosis Rules Reference

Source: user-provided “故障诊断规则 第六版”.

Use this file as the detailed rule base after the skill is triggered. Match observations against the corresponding equipment type and fault subtype, then inherit the associated key features, typical features, and recommended actions.

## Equipment coverage
- 汽轮机
- 离心式&轴流式压缩机
- 多轴式（齿轮式）压缩机
- 螺杆式压缩机
- 齿轮箱

## Supported fault families
- 不平衡类
- 不对中
- 临界响应大
- 转子热弯曲
- 转子永久性弯曲
- 动静摩擦 / 密封摩擦
- 支撑轴承装配、软脚/刚度差异
- 旋转失速 / 喘振
- 晃度
- 轴位移零点调校异常
- 支撑轴承温度异常 / 装配异常
- 推力轴承温度异常 / 装配或设计异常

## Cross-equipment quick index

### 1) 1X dominant, sinusoidal, speed-synchronous
Check among:
- 不平衡
- 临界响应大
- 转子热弯曲
- 转子永久性弯曲
- 不对中（若联端更突出）
- 支撑刚度差异（若同一轴承 XY 差异明显）

### 2) Fractional harmonics / clipping / burrs / distorted orbit
Check among:
- 密封摩擦
- 晃度（低速、每周期跳变且 XY 相差约90°）

### 3) Low-frequency instability / non-repeatable waveform-orbit / process linkage
Check among:
- 旋转失速 / 喘振

### 4) High but flat temperatures from startup
Check among:
- 支撑轴承装配异常
- 推力轴承装配或设计异常

### 5) High axial displacement after maintenance but stable temperature
Check among:
- 轴位移零点调校异常

---

## Rule summaries by equipment

## 汽轮机

### 转子热弯曲
- Context: low-speed warm-up steady speed or speed-up process.
- Core signs:
  - four channels rise quickly
  - mainly 1X increase
  - waveform close to standard sine
  - coastdown does not retrace startup centerline / vibration reduction path
- Strong discriminator:
  - BODE / same-speed comparison on coastdown does not overlap startup behavior
- Actions:
  - verify steam parameters, oil temperature, pipeline temperature
  - strengthen turning gear observation for rub/sticking
  - extend warm-up if needed
  - if repeated, check thermal expansion and rotor bend

### 转子永久性弯曲
- Context: already high in low-speed startup stage, then rises with speed.
- Core signs:
  - four channels relatively similar and high at low speed
  - mainly 1X, phase change small
  - waveform equal-amplitude sine
  - orbit is ellipse with similar long/short axes, forward precession
  - may accompany larger axial vibration
- Actions:
  - short monitored running if below trip
  - lower speed if process permits
  - rotor straightening before balancing

### 密封摩擦
- Context: steady speed or startup process with rapid increase / large fluctuation.
- Core signs:
  - waveform may show clipping or burrs
  - spectrum mainly 1X, may also show 0.5X / 1.5X / 2.5X / 2X / 3X
  - orbit may show line-like, concave-convex, or alternating precession
  - severe cases stay high even during speed reduction until near stop
- Actions:
  - check seal clearance, sliding pins, steam parameters, thermal alignment

### 晃度
- Context: turning gear or low-speed warm-up.
- Core signs:
  - one bearing pair both high at low speed
  - one obvious downward spike each cycle
  - X/Y spikes separated by ~90°
  - many harmonics may appear
- Actions:
  - treat as measurement effect first; inspect probe track area during outage

### 支撑轴承装配异常（温度）
- Core signs:
  - one end bearing temperatures generally high, often >90°C
  - high but flat from startup, no clear trend change

### 推力轴承装配或设计异常（温度）
- Core signs:
  - both thrust temperature channels high, often >90°C
  - compared with initial operation, same-load temperature does not keep rising

---

## 离心式 & 轴流式压缩机

### 初始不平衡
- Context: long-period operation and startup.
- Core signs:
  - four channels generally high (>35 μm), or one channel on each end high
  - often same-side channels high (e.g. both X)
  - startup vibration rises strongly with speed
  - long-period trend relatively stable at high level
  - mainly 1X, phase relatively stable over time
  - waveform sine-like, orbit elliptical and repeatable
- Actions:
  - monitor if below trip
  - later perform high-speed balancing

### 不对中
- Core signs:
  - coupling-side channels on connected machines both high (>25 μm)
  - startup changes obvious at coupling side, non-coupling side smaller
  - mainly 1X, waveform near sine, orbit repeatable ellipse
- Actions:
  - check coupling assembly / marks / bolts / spacers
  - consider field balancing if assembly correction not enough

### 临界响应大
- Context: startup or shutdown passing critical speed range.
- Core signs:
  - four channels rise rapidly in a speed band
  - may exceed alarm/trip
  - mainly 1X
  - waveform standard sine
  - orbit ellipse or circle with strong repeatability
- Actions:
  - confirm startup conditions
  - pass critical region faster
  - review trip logic carefully if safe
  - later optimize bearing clearance / balancing / damping

### 转子热弯曲
- Context: nitrogen test / special operating condition at steady working speed.
- Core signs:
  - four channels quickly rise at steady speed
  - mainly 1X
  - waveform standard sine
  - orbit large ellipse
- Actions:
  - watch outlet temperature and test conditions
  - if needed inspect for rub and rotor bend

### 转子永久性弯曲
- Context: low-speed stage already high, then rises with speed.
- Core signs similar to turbine permanent bend:
  - four channels relatively similar and high at low speed
  - mainly 1X, small phase variation
  - equal-amplitude sine waveform
  - repeatable ellipse orbit, forward precession
  - may have large axial vibration too

### 支撑轴承装配、软脚/刚度差异
- Core signs:
  - one bearing pair both high (>35 μm) or XY difference >20 μm
  - mainly 1X
  - waveform repeatability slightly worse than pure unbalance
  - centerline rise difference between ends large during startup
  - orbit may be slender ellipse if directional stiffness differs
- Actions:
  - monitor vibration and GAP
  - adjust oil temperature / pressure if helpful
  - outage inspection of bearing fit / clearance / support stiffness

### 旋转失速 / 喘振
- Context: startup, normal operation, or shutdown with process adjustment.
- Core signs:
  - unstable frequent vibration fluctuation on multiple channels
  - low-frequency content prominent; surge may show 1–30 Hz ultra-low-frequency
  - waveform unstable, not clearly periodic; may enlarge for a few cycles then recover
  - orbit disorderly / honeycomb-like / non-repeatable
  - axial displacement and speed may fluctuate simultaneously
  - often tied to large inlet-flow reduction or anti-surge action
- Strong note:
  - if this unstable feature appears right at shutdown moment, prioritize rotating stall / surge
- Actions:
  - increase anti-surge valve opening / venting
  - reduce speed if needed
  - inspect process cause and check seals / thrust bearing after event

### 晃度
- Same low-speed measurement-effect logic as turbine.

### 轴位移零点调校异常
- Core signs:
  - after maintenance, axial displacement immediately high at startup
  - much larger than historical normal value
  - thrust temperatures reasonable (<90°C) and similar to past
  - long-period trend stable without continuous change

### 支撑轴承装配异常（温度）
- One-end bearing temperature high and flat from startup.

### 推力轴承装配或设计异常（温度）
- Both thrust temperature channels high and flat from startup.

---

## 多轴式（齿轮式）压缩机

### 不平衡
- Similar to centrifugal compressor unbalance, but assess by the specific stage rotor.
- Core signs:
  - one stage four channels generally high (>35 μm)
  - mainly 1X
  - startup rises strongly with speed
  - long-period trend relatively stable
  - waveform repeatable, orbit repeatable ellipse

### 临界响应大
- Same logic as centrifugal compressor critical response:
  - occurs while passing critical speed band during startup/shutdown
  - rapid rise on four channels
  - mainly 1X, standard sine, repeatable large ellipse/circle orbit

### 旋转失速 / 喘振
- Same instability logic, with extra caution that it may show up at shutdown moment.

### 晃度 / 轴位移零点异常 / 支撑轴承温度异常 / 推力轴承温度异常
- Use the same diagnostic logic as centrifugal compressor when measurement type and context match.

---

## 螺杆式压缩机

### 晃度
- Same low-speed waveform jump / 90° phase-separation rule.

### 轴位移零点调校异常
- Same high-but-flat post-maintenance axial reading rule.

### 支撑轴承装配异常（温度）
- One-end high and flat bearing temperature from startup.

### 推力轴承装配或设计异常（温度）
- Both thrust temperatures high and flat from startup.

---

## 齿轮箱

### 不对中
- Core signs:
  - coupling-end channels of connected equipment both high or change together
  - mainly 1X
  - long-period trend relatively stable
  - startup changes mainly at coupling side
  - waveform near sine, orbit repeatable ellipse
- Actions:
  - inspect coupling assembly, markings, bolts, spacers
  - consider balancing at coupling if needed

### 支撑轴承装配、软脚/刚度差异
- Use the same one-bearing-high / XY-difference / slender-orbit logic as compressor support stiffness faults when applicable.

---

## Evidence ranking rules

When data is incomplete, rank evidence importance as:
1. operation context and time window
2. multi-channel consistency
3. dominant frequency structure (1X / 2X / fractional / low frequency)
4. waveform morphology
5. orbit repeatability and shape
6. process correlation
7. temperature / axial corroboration

## Reporting rules

- If only trend + spectrum support a fault but orbit/process evidence is missing, use “倾向于/疑似”.
- If waveform/spectrum/orbit and operation context all align, give a direct primary diagnosis.
- If a key discriminator is absent, state explicitly what is missing.
- Always mention at least one differential diagnosis when more than one rule partially matches.
