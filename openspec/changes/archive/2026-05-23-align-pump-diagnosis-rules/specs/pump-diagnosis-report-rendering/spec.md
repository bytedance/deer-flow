## ADDED Requirements

### Requirement: 机泵规则结果映射为报告 payload

系统 SHALL 将 `pump_rule_result.json` 转换为 Deer Flow 诊断报告 payload，用于 GenUI 渲染、Markdown 导出、PDF 导出和闭环单判定。

#### Scenario: 规则结果包含发现

- **WHEN** `pump_rule_result.json` 包含健康发现或故障发现
- **THEN** 报告 payload SHALL 包含设备摘要、主发现、备选发现、置信度或概率、证据行、建议、warnings 和运行时元数据

#### Scenario: 规则结果无阳性发现

- **WHEN** 规则运行时成功完成，但没有健康发现也没有故障发现
- **THEN** 报告 payload SHALL 明确说明未形成受管机泵规则发现，并仍包含可用证据摘要和 warnings

### Requirement: 机泵诊断按固定顺序渲染 GenUI block

机泵 Agent SHALL 以稳定顺序渲染最终诊断内容，支持用户先浏览结论再下载文件。

#### Scenario: 报告 payload 可用

- **WHEN** 已构建有效机泵诊断报告 payload
- **THEN** Agent SHALL 按确定性顺序渲染摘要卡片、可用趋势或频谱图、证据表、建议、warnings 和最终 Markdown 内容

#### Scenario: 图表数据不可用

- **WHEN** 无法从规则运行时证据缓存构建图表数据
- **THEN** Agent SHALL 跳过不可用图表 block，并写入 warning，不得为了展示图表再执行一轮独立采样

### Requirement: 机泵报告使用规则阶段数据绘图

系统 SHALL 使用规则执行阶段捕获或引用的数据构建机泵诊断图表，不得在报告阶段独立选择新的采样时间。

#### Scenario: 存在频谱证据

- **WHEN** 故障规则对某测点使用了波形或频谱数据
- **THEN** 对应报告图表 SHALL 使用同一测点和时间戳，或说明该图表无法渲染的原因

#### Scenario: 报告渲染需要新数据

- **WHEN** 渲染某个图表需要选择新的异常时间或重新获取无关数据
- **THEN** 渲染器 SHALL 不执行该独立采样，并输出 warning

### Requirement: 机泵报告只导出最终产物

机泵 Agent SHALL 只向用户暴露最终诊断报告文件，规则输出和图表缓存应作为内部产物保留。

#### Scenario: Markdown 和 PDF 导出成功

- **WHEN** Markdown 和 PDF 均导出成功
- **THEN** Agent SHALL 仅对 `/mnt/user-data/outputs/diagnosis_report.md` 和 `/mnt/user-data/outputs/diagnosis_report.pdf` 调用 `present_files`

#### Scenario: PDF 导出不可用

- **WHEN** PDF 渲染依赖不可用导致 PDF 导出失败
- **THEN** Agent SHALL 仍提供 Markdown 报告，且不得暴露 `pump_rule_result.json` 或中间图表缓存文件

### Requirement: 机泵报告标明数据来源

机泵诊断报告 SHALL 标明结论来自受管机泵规则运行时、局部规则执行，还是显式标注的演示 fallback。

#### Scenario: 受管运行时成功

- **WHEN** 受管机泵规则运行时基于真实数据成功完成
- **THEN** 报告 SHALL 标明数据源为受管机泵规则运行时，并在可用时包含运行时版本或适配层元数据

#### Scenario: 使用演示 fallback

- **WHEN** 使用演示 fallback 数据
- **THEN** 报告 SHALL 在诊断结论前放置醒目 warning，说明结论仅用于演示

### Requirement: 机泵报告展示所选子设备上下文

机泵诊断报告 SHALL 保留用户选择的设备与子设备上下文，并围绕该目标展示结论和证据。

#### Scenario: 选择一个子设备

- **WHEN** 用户选择一个机泵设备下的子设备并完成诊断
- **THEN** 报告 SHALL 展示设备名称、设备 ID、子设备名称、子设备 ID、目标类型和诊断时间

#### Scenario: 子设备无有效结论

- **WHEN** 所选子设备无法形成有效规则发现
- **THEN** 报告 SHALL 展示该子设备的 warning 和可用证据摘要，而不是输出多设备汇总结论

### Requirement: 机泵报告按严重发现触发闭环单

机泵 Agent SHALL 使用受管规则严重等级和置信度字段判断是否必须创建闭环单。

#### Scenario: 检出严重发现

- **WHEN** 机泵发现被判定为 critical 或 high，或满足既有闭环创建置信度阈值
- **THEN** Agent SHALL 创建或复用闭环单，并把最终 Markdown 报告 URI 作为证据

#### Scenario: 严重程度低于阈值

- **WHEN** 所有机泵发现均低于闭环单触发阈值
- **THEN** Agent SHALL 不创建闭环单
