## ADDED Requirements

### Requirement: 机泵诊断执行受管规则运行时

系统 SHALL 通过 Deer Flow 受管机泵规则运行时执行机泵故障诊断，不再把外部参考目录或通用文档规则匹配器作为权威诊断引擎。

#### Scenario: 机泵诊断调用规则运行时

- **WHEN** `fault-diagnosis--pump` 已收集有效机泵设备 ID、子设备 ID 和诊断时间
- **THEN** 诊断执行 SHALL 调用受管机泵规则运行时入口，并写出结构化 `pump_rule_result.json`

#### Scenario: 运行时不依赖外部参考路径

- **WHEN** 运行环境中不存在 `/Users/gubailin/PycharmProjects/deer-flow-yh/参考-机泵规则`
- **THEN** 机泵诊断 SHALL 仍可从 Deer Flow 受管代码运行，或返回受管依赖错误，且不得引用该绝对路径作为运行依赖

### Requirement: 机泵诊断输入对齐旋转机组

机泵 Agent SHALL 使用与旋转机组一致的输入流程：先选择设备与子设备，再选择诊断日期和小时，然后执行诊断。

#### Scenario: 首次进入选择子设备

- **WHEN** 用户发起机泵故障诊断且当前消息不是有效 `ui_interaction`
- **THEN** Agent SHALL 渲染 `sub-device-selector`，并使用 `typeId=4` 与 `filterDeviceType=4` 限定机泵设备

#### Scenario: 子设备选择后选择时间

- **WHEN** Agent 收到有效 `fd-pump-device` 回调
- **THEN** Agent SHALL 渲染诊断时间表单，仅要求 `diagnosis_date` 和 `diagnosis_hour`

#### Scenario: 时间提交后执行

- **WHEN** Agent 收到有效 `fd-pump-time` 回调
- **THEN** Agent SHALL 使用最近一次设备/子设备回调和当前时间回调拼装 1 小时诊断窗口并执行规则运行时

### Requirement: 机泵规则运行时排除起停机状态

机泵规则运行时 MUST NOT 执行起停机状态判断，也不得因为启动或停机状态跳过振动诊断。

#### Scenario: 排除起停机模块

- **WHEN** 任意诊断小时内运行机泵诊断
- **THEN** 运行时 SHALL NOT 调用等价于 `stop/CheckStop.py` 或 `stop/StopValue.py` 的逻辑

#### Scenario: 振动诊断不被启动状态跳过

- **WHEN** 振动数据和波形数据可用
- **THEN** 运行时 SHALL 始终评估振动健康规则和故障规则，不受设备可能近期启停的影响

### Requirement: 机泵运行时解析子设备测点上下文

系统 SHALL 将选中的机泵设备与子设备解析为参考规则所需的测点与配置上下文，包括振动测点、温度测点、阈值、轴承特征频率配置和 BPF 配置。

#### Scenario: 子设备测点上下文可用

- **WHEN** 选中的机泵设备与子设备存在可解析的 InS/2K 子测点和配置
- **THEN** 运行时 SHALL 构建目标上下文，包含 `machineId`、`componentId`、目标类型、关联测点 ID、测点名称、测点类型、阈值和规则配置

#### Scenario: 必要测点上下文缺失

- **WHEN** 选中的子设备无法关联到可用振动测点或可用带波形测点
- **THEN** 运行时 SHALL 返回结构化 warning 或 error，而不是生成无依据的故障结论

### Requirement: 机泵运行时推断基频

机泵规则运行时 SHALL 在未提供基频时，使用受管实现复现参考 `basefreq.BaseFreq.calc` 的基频推断行为。

#### Scenario: 未提供基频

- **WHEN** 机泵诊断启动时没有显式基频
- **THEN** 运行时 SHALL 从近期波形数据和标准转速附近推断基频，并在 `pump_rule_result.json` 中记录选定值

#### Scenario: 基频无法推断

- **WHEN** 波形数据不足或无效，导致无法推断基频
- **THEN** 运行时 SHALL 记录结构化 warning，并跳过当前目标上依赖基频的故障规则

### Requirement: 机泵运行时评估健康异常

机泵规则运行时 SHALL 评估参考健康逻辑中不依赖起停机状态的异常，包括振动 C/D 区、12 小时内进入 C 区、速度趋势、加速度趋势、温度超限和温度趋势。

#### Scenario: 检出阈值或趋势异常

- **WHEN** 趋势数据满足某项受管健康规则阈值
- **THEN** 运行时 SHALL 输出 `health_findings` 条目，包含测点 ID、测点名称、状态编码或名称、证据参数和证据时间

#### Scenario: 未检出健康异常

- **WHEN** 可用趋势数据不满足任何健康规则阈值
- **THEN** 运行时 SHALL 为当前目标返回空 `health_findings` 列表，且不得把无异常视为执行失败

### Requirement: 机泵运行时评估故障候选

机泵规则运行时 SHALL 使用受管实现复现参考 FFT 与概率逻辑，评估不平衡、滚动轴承外圈、滚动轴承内圈、滚动轴承滚动体、滚动轴承保持架、不对中和 BPF 频率异常。

#### Scenario: 检出故障候选

- **WHEN** 波形和频谱证据满足某项受管故障规则
- **THEN** 运行时 SHALL 输出 `malfunction_findings` 条目，包含故障类型、故障名称、概率、证据测点 ID 和证据时间

#### Scenario: 概率低于判定阈值

- **WHEN** 某项规则计算出的概率低于参考判定阈值
- **THEN** 运行时 SHALL NOT 将该故障作为阳性发现输出

### Requirement: 机泵运行时保留证据与采样元数据

机泵规则运行时 SHALL 保留报告渲染和验证所需的证据元数据，包括采样波形时间、频谱能量比、使用的阈值、跳过的测点和 warnings。

#### Scenario: 产生诊断证据

- **WHEN** 健康规则或故障规则产生发现
- **THEN** `pump_rule_result.json` SHALL 包含可追溯到设备、测点、特征、数值、阈值或能量比、规则判定的证据行

#### Scenario: 局部采样失败

- **WHEN** 部分波形、趋势或测点配置获取失败，但仍存在其他可用测点
- **THEN** 运行时 SHALL 继续诊断可用测点，并将失败项写入 `warnings`

### Requirement: 机泵权威规则不可用时显式失败

当受管机泵规则运行时不可用时，系统 MUST NOT 静默把通用 fallback 结果展示为权威机泵规则诊断。

#### Scenario: 运行时依赖缺失

- **WHEN** 必要受管规则依赖无法导入或初始化
- **THEN** 机泵诊断 SHALL 返回结构化错误，并在报告生成前停止，除非用户显式选择带强提示的演示模式

#### Scenario: 使用演示 fallback

- **WHEN** 开发调试或 InS 数据不可用时使用演示 fallback
- **THEN** 返回结果和最终报告 SHALL 清晰标注该结论不是由权威机泵规则运行时生成
