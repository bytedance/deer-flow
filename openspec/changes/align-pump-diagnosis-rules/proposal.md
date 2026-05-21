## Why

当前 `fault-diagnosis--pump` 已具备 GenUI 收参、设备选择、趋势聚合、报告导出的 MVP 链路，但输入流程是机泵专用的多轮多设备筛选，核心诊断也仍依赖通用 `query_diagnosis.py` / `diagnosis_features.py` 和 `pump-fault-diagnosis` 规则文档做二阶段匹配。用户已提供现场机泵规则参考工程 `/Users/gubailin/PycharmProjects/deer-flow-yh/参考-机泵规则/algorithm-verification-py`，其中包含基频推断、波形采样、FFT 能量比、不平衡、滚动轴承和频率类故障判定逻辑，需要把机泵 Agent 收敛到与旋转机组 Agent 一致的“选择子设备与诊断时间 → 真实规则运行时 → 稳定文件契约 → 报告渲染”模式。

本次只开发机泵故障诊断主链路，不考虑起停机状态；参考工程中的 `stop/*` 与健康检查里的开停机跳过逻辑不进入本次规则执行范围。

## What Changes

- 将 `fault-diagnosis--pump` 的输入流程调整为与旋转机组一致：先用 `sub-device-selector` 选择机泵设备与子设备，再选择一个诊断日期和小时，然后执行诊断。
- 将机泵主诊断链路从“通用趋势聚合 + 文档规则匹配”切换为“机泵规则运行时适配层 + 真实故障判定结果”。
- 新增受管机泵规则运行时，参照旋转机组 Agent 的接入方式，把参考工程中的核心算法整理为 Deer Flow 可部署、可测试、可回滚的仓库内资产。
- 新建独立 skill `skills/custom/pump-fault-diagnosis/` 的稳定脚本入口，承接 Agent 入参并输出标准 `pump_rule_result.json`，避免运行时依赖用户本机绝对路径。
- 规则执行入口接收 `machineId`、`componentId` 和诊断小时窗口；规则运行时基于所选子设备定位相关测点与配置，不再要求用户额外选择多台设备、关键测点或故障家族焦点。
- 规则执行范围覆盖参考工程中的基频推断、波形选择、FFT / 能量比特征、不平衡、滚动轴承外圈/内圈/滚动体/保持架、不对中、BPF 频率异常。
- 明确排除起停机状态：不接入 `stop/CheckStop.py`、`stop/StopValue.py`，也不因“启停机 12 小时内”跳过振动诊断。
- 将规则结果映射为 Deer Flow 报告 payload、GenUI block、Markdown/PDF 导出和闭环单触发所需字段。
- 对真实规则运行时不可用、依赖缺失、InS 取数失败等情况采用显式失败或强提示降级，不静默生成正式诊断结论。

## Capabilities

### New Capabilities

- `pump-diagnosis-rule-execution`: 机泵诊断必须按“选择子设备与诊断时间”输入契约执行受管机泵规则运行时，完成基频推断、波形/频谱取数、特征计算和故障候选判定，且不处理起停机状态。
- `pump-diagnosis-report-rendering`: 机泵诊断必须把真实规则结果转换为 Deer Flow 的结构化报告、GenUI 展示、Markdown/PDF 导出和闭环单输入。

### Modified Capabilities

None.

## Impact

- Agent：`agents/builtin/fault-diagnosis--pump/`
- 诊断 skill / 适配层：`skills/custom/pump-fault-diagnosis/`
- 受管运行时代码：`docker/sandbox/features-tool/` 或等价 sandbox 可见包路径
- 现有机泵 SOUL 的 GenUI 流程：从多设备/多测点/故障焦点表单改为子设备选择器 + 诊断时间表单
- 当前机泵 SOUL 引用的既有诊断脚本：`query_diagnosis.py`、`diagnosis_features.py`、报告导出 helper
- InS / 2K 数据访问链路：设备树、子设备/测点列表、趋势值、带波形测值、波形 payload
- 测试范围：机泵规则执行、SOUL smoke 流程、报告 payload 映射、导出
- 明确非目标：不新增前端组件，不新增后端路由，不在本变更中实现起停机状态分支
