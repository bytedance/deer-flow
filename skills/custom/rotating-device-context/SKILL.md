---
name: rotating-device-context
description: 当旋转机组诊断流程需要当前 Agent 基于 InS 原始设备树推理标准 `device_context.json` 时使用本 skill。推理必须复用当前 Agent 的模型上下文，不允许再调用独立的 Python 侧 LLM。
metadata:
  emoji: "🧭"
---

# 旋转设备上下文推理

当旋转机组诊断的步骤 2 需要生成 `/mnt/user-data/outputs/device_context.json` 时，使用本 skill。

## 目标

把下面两类输入：

- `machine_service.get_machine_info_by_ids` 返回的设备详情
- `python /opt/features-tool/tools/device_analysis.py "{macId}" --output /mnt/user-data/outputs/device_tree_raw.json` 生成的原始设备树

推理成一个标准 JSON 产物：

- `/mnt/user-data/outputs/device_context.json`

这一步必须由当前 Agent 自己完成推理，不允许再调用独立的 Python 侧 LLM。

## 输出要求

最终必须写出且只写出一个合法 JSON 对象，顶层字段固定为：

- `device_id`
- `child_device_summary`
- `device_type`
- `process_type`
- `device_structure`
- `child_device_list`
- `target_info`

其中 `device_type`、`process_type`、`device_structure` 都必须包含：

- `value`
- `confidence`
- `reason`

## 推理规则

### 1. 总体原则

- 不允许静默丢弃有效测点。凡是有业务含义的测点，都必须保留在 `child_device_list` 中。
- `child_device_list` 应保留机组根节点；不要把 `unit_type=1/type_num=1` 的机组根节点整个删掉。
- 原始树里已经正确挂载的节点，优先保留原层级；只对明显未挂载或挂错层级的测点做回挂。
- 生成结果时，字段名必须完全遵循模板，不要额外增删字段。

### 2. 未挂载测点回挂规则

- 对未挂在正确 `80/70` 节点下的 `type_num=82` 和部分 `type_num=83` 测点，优先按 `belongShaftId` 找到对应轴系。
- 在同一 `belongShaftId` 下，优先结合名称中的设备词和方向词回挂：
  - 设备词示例：`电机`、`齿轮箱`、`压缩机`
  - 方向词示例：`联端`、`非联端`、`驱动端`、`非驱动端`
- 方向词映射要求：
  - `驱动端` 通常按 `联端` 处理
  - `非驱动端` 通常按 `非联端` 处理
  - 如果名称已明确包含 `联端/非联端`，直接用该信息
- 如果同一轴系存在多个 `70` 轴承节点，优先把测点挂到方向最匹配的那个轴承下。
- 如果名称含 `主止推`、`副止推`、`推力轴承`、`轴瓦温度` 等推力语义，优先挂到对应轴系的 `联端/驱动端` 轴承；若无明确推力轴承节点，也要挂到最接近的联端支撑轴承下，不能丢在转子节点外面。
- 如果测点只能确定属于某个 `80` 设备、但无法确定具体 `70` 轴承，才允许挂在该 `80` 设备节点下。
- 只有在既无法定位 `70`，也无法可靠定位 `80` 时，才允许保留在机组根节点下。

### 3. 点型推断规则

- `type_num=83`：
  - 名称包含 `波形` 时，通常判为 `轴位移波形`
  - 其余径向 X/Y 振动类，判为 `轴振`
- `type_num=82`：
  - 名称包含 `轴承温度`、`轴瓦温度`、`支撑轴承温度`、`止推轴瓦温度`，判为 `轴承温度`
  - 名称包含 `轴位移`、`位移`，判为 `轴位移`
  - 名称包含 `入口流量`，判为 `入口流量`
  - 名称包含 `入口压力`、`入口温度`、`进气参数`，判为 `压缩机进气参数`
  - 名称包含 `出口温度`、`排气温度`，判为 `出口温度`
  - 名称包含 `油温`、`润滑油温度`、`回油温度`、`进油温度`，判为 `润滑油温度`
  - 其余仍有工艺意义的压力、温度、流量、阀位、密封气、泄漏气类，判为 `其他工艺参数`
- 不要把 `type_num=82` 的振动/位移类点全部忽略。只有明显重复、明显无效、或确实不该进入该 JSON 的噪声点，才可省略，并应在外围说明原因。

### 4. 本次样例暴露出的典型错误，必须避免

- 不能遗漏未挂载的轴承温度点，例如：
  - `电机驱动端支撑轴承温度`
  - `电机非驱动端支撑轴承温度`
  - `压缩机驱动端支撑轴承温度`
  - `压缩机非驱动端支撑轴承温度`
  - `齿轮箱驱动端/非驱动端高速轴或低速轴支撑轴承温度`
- 不能遗漏未挂载的轴位移点，例如：
  - `压缩机轴位移A`
  - `压缩机轴位移B`
- 不能把整批未挂载测点从 `child_device_list` 中删除，哪怕这些点没有进入 `target_info`，也必须保留在树中。
- 不要把 `电机` 识别成 `发电机`，除非树中存在明显发电机证据。

### 5. 目标节点解析

- `target_info` 的目标解析要和修正后的 `child_device_list` 保持一致。
- 如果用户选中的是测点，则：
  - `target_kind=probe`
  - `probe_ids` 应包含同轴承下相关测点，至少包含该测点本身；若存在 X/Y 配对，应一起纳入
  - `waveform_probe_ids` 应优先只放可用于波形/频谱分析的轴振测点
  - `bearing_ids` 应指向该测点所属轴承
- 如果用户选中的是轴承，则：
  - `target_kind=bearing`
  - `probe_ids` 应包含该轴承下全部相关测点
  - `waveform_probe_ids` 应优先选择该轴承下的 X/Y 轴振测点
- 如果用户选中的是 `80` 级转子设备，则：
  - `target_kind=rotor_device`
  - `bearing_ids` 应包含该设备下所有相关轴承
  - `waveform_probe_ids` 应优先包含可用于波形分析的轴振测点，不要只放轴位移波形点

### 6. 冲突与失败处理

- 如果所选 `componentId` 无法在修正后的树中解析，允许把 `target_info.target_kind` 设为 `"unknown"`，并在外围响应说明原因。
- 如果原始树为空、所选节点不在树中、或 `componentId == macId` 导致无法形成有效子设备目标，应立即终止后续诊断。

## `target_info` 必填字段

`target_info` 至少要包含：

- `target_kind`
- `probe_ids`
- `waveform_probe_ids`
- `bearing_ids`
- `owner_device_id`
- `target_device_type`

`target_kind` 只允许以下值：

- `probe`
- `bearing`
- `rotor_device`
- `unknown`

## 模板

写文件前，先阅读 [references/device_context_template.json](references/device_context_template.json)，并严格按照该结构输出。
