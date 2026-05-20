## Why

当前 `fault-diagnosis--rotating` 仍以 Deer Flow 内部的两阶段 MVP 为主：`query_diagnosis.py` 聚合趋势，`diagnosis_features.py` 再用规则文档做关键词式匹配。它与现场正在运行的 `mac-diag-code/diagnosis_rule/workflow.py` 在取数路径、候选故障打分、证据竞争和置信度生成上都不一致，导致“线上真实诊断逻辑”和“Agent 输出逻辑”分叉。

现在需要把旋转机组诊断收敛到同一套规则执行链路上，同时复用该规则代码已经定义好的趋势、波形、轨迹和工艺量取数接口，把最终报告画出来，避免继续维护两套含义相近但结论可能冲突的诊断实现。

## What Changes

- 将 `fault-diagnosis--rotating` 的诊断主链路从“LLM + `diagnosis_features.py` 关键词匹配”切换为“规则引擎适配层 + `workflow.py` 真实打分结果”。
- 新增一个面向 Deer Flow 的旋转机组规则执行适配层，负责承接 Agent 输入，驱动 `run_diagnosis(device_id, sub_device_id, time)` 所需上下文、数据接口和错误处理。
- 明确这套 Python 代码与系统的交互形式：内部以可导入 Python package 暴露，Agent 侧通过独立 skill `skills/custom/rotating-fault-diagnosis/` 下的稳定 CLI 包装器调用，报告链路通过标准 JSON / artifact 文件交接。
- 删除对 `diagnosis_rule.rule_optimizer` 的运行时依赖，改为直连底层取数 / 特征提取实现，同时把原始趋势、波形、轨迹数据缓存到 Deer Flow 受管文件中，供报告绘图复用。
- 调整数据接口鉴权方式：直接透传 Deer Flow 当前用户 token 到取数层，不在这套 Python 代码里再次登录或换取 InS token。
- 将 `INS_BASE_URL` 固定为部署级配置，放在 Deer Flow `config.yaml` 的 `sandbox.environment` 中按需注入；未配置时使用工具内默认值，不把它做成用户级环境变量或 Agent 输入参数。
- 将 `device_analysis.py` 里“再起一个独立模型分析设备树”的逻辑并入 Deer Flow Agent 能力，仅保留原始子设备树获取作为底层工具。
- 复用 `mac-diag-code` 中的设备分析、趋势、波形、轨迹与特征提取接口约定，统一诊断时的数据来源和采样顺序。
- 定义从规则引擎 `DiagnosisResult` 到 Deer Flow 报告 payload / GenUI block / Markdown/PDF 导出的标准映射，确保最终报告展示主诊断、候选诊断、证据摘要、趋势/频谱/轨迹图和处置建议。
- 为外部规则代码的依赖闭包、版本同步、不可用降级和测试夹具建立明确边界，避免运行时依赖用户本机绝对路径。

## Capabilities

### New Capabilities
- `rotating-diagnosis-rule-execution`: 旋转机组诊断必须按 `mac-diag-code` 的真实规则执行顺序、取数接口和候选故障竞争逻辑运行。
- `rotating-diagnosis-report-rendering`: 旋转机组诊断必须把真实规则引擎的输出转成 Deer Flow 的结构化报告与导出产物。

### Modified Capabilities

None.

## Impact

- Agent: `agents/builtin/fault-diagnosis--rotating/`
- Diagnosis skill / adapters: `skills/custom/rotating-fault-diagnosis/`
- Possible shared runtime code under `backend/packages/harness/deerflow/` if the adapter is promoted out of the script layer
- Test suites covering rotating diagnosis smoke flow, rule execution, and report export
- Token passthrough from Deer Flow session/auth context into rotating-diagnosis data access
- Refactor of `device_analysis.py` into “raw tree fetch tool + agent-side reasoning” instead of a nested standalone model runner
- Runtime packaging work for `models.py` / `context_index.py` namespace compatibility, `rule_optimizer` dependency removal, and managed raw-data cache files for report rendering
