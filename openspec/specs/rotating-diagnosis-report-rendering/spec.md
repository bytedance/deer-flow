## ADDED Requirements

### Requirement: 真实规则结果必须映射为 Deer Flow 报告 payload
系统 SHALL 将旋转机组真实规则引擎输出规范化为 Deer Flow 报告 payload，并用于 GenUI 渲染与 Markdown/PDF 导出。

#### Scenario: 规则结果被规范化为报告数据
- **WHEN** 一次旋转机组真实规则诊断成功完成
- **THEN** 系统写出规范化 payload，至少包含报告元信息、主诊断、备选诊断、证据摘要、运行建议、检修建议和 warnings

#### Scenario: 规则结果保留主诊断与候选诊断排序
- **WHEN** 真实规则引擎输出多个候选故障
- **THEN** 规范化 payload 必须保留主诊断和候选诊断的顺序、分数和置信度，供报告正文和 UI 卡片引用

### Requirement: 报告图表必须来源于真实规则链路的数据
系统 SHALL 使用真实规则链路中已采集的趋势、频谱和轨迹数据构建报告图表，不得用独立于本次规则执行的重新采样结果替代。

#### Scenario: 原始数据齐备时生成趋势频谱轨迹图
- **WHEN** 本次真实规则诊断过程中已拿到趋势、频谱和轨迹原始数据
- **THEN** 系统从本次诊断落盘的原始数据缓存中生成对应的趋势图、频谱图和轨迹图配置，并在旋转机组报告中展示

#### Scenario: 局部图表数据缺失时保留部分报告
- **WHEN** 某个测点或轴承的频谱或轨迹数据在本次规则执行中缺失
- **THEN** 系统仍然生成可交付的报告，跳过缺失图表并把缺失信息写入 warnings

#### Scenario: 报告阶段不得重新取数
- **WHEN** 诊断阶段已经完成且报告开始渲染
- **THEN** 报告阶段不得再次调用外部数据接口重新抓取原始趋势、频谱或轨迹数据，而是只读取本次诊断留下的缓存文件

### Requirement: 旋转机组报告只交付最终导出物
系统 SHALL 将旋转机组真实规则诊断的最终交付物限制为诊断报告文件，不向用户暴露规则运行时中间文件。

#### Scenario: Markdown 和 PDF 可用时交付双文件
- **WHEN** 诊断报告 Markdown 成功生成且 PDF 导出依赖可用
- **THEN** 系统仅向用户交付 `diagnosis_report.md` 和 `diagnosis_report.pdf`

#### Scenario: PDF 不可用时只交付 Markdown
- **WHEN** 诊断报告 Markdown 生成成功但 PDF 导出依赖不可用
- **THEN** 系统仍然交付 `diagnosis_report.md`，并在报告或回复中明确说明 PDF 不可用

#### Scenario: 中间文件不对外暴露
- **WHEN** 系统生成了规则结果文件、缓存数据文件或图表中间文件
- **THEN** 系统不得通过最终交付接口向用户暴露这些中间文件
