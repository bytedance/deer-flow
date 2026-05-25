# 旋转机组诊断规则运行时说明

## 范围

`fault-diagnosis--rotating` 现在走受管规则运行时：

1. 选择旋转机组设备与子设备（`fd-rotating-device` callback）。
2. 选择诊断时间（`fd-rotating-time` callback）。
3. Agent 内完成设备树推理，写出 `device_context.json`。
4. 调用 `skills/custom/rotating-fault-diagnosis/scripts/run_rotating_rule_diagnosis.py`。
5. 写出 `/mnt/user-data/outputs/rotating_rule_result.json` 和 `rotating_rule_cache/`。
6. 调用 `build_rotating_report_payload.py` 生成 `diagnosis_features.json`。
7. 只向用户暴露 `diagnosis_report.md` / `diagnosis_report.pdf`。

本链路禁止静默回退到旧 MVP 关键词匹配诊断。

## 环境变量

- `INS_ACCESS_TOKEN`：必需。Deer Flow 当前用户 Bearer token，由运行上下文注入 sandbox。
- `INS_BASE_URL`：可选。InS 基础地址，建议放在根 `config.yaml` 的 `sandbox.environment`。未配置时回落到 `diagnosis_rule/config.py` 默认地址。
- `DIAGNOSIS_OUTPUT_DIR`：可选。默认 `/mnt/user-data/outputs`。
- `FEATURES_TOOL_ROOT`：可选。默认 `/opt/features-tool`。

不要为该链路配置 `INS_USERNAME` / `INS_PASSWORD`、Nacos、MQ 或数据库连接作为生产依赖。

## 代码边界

- 受管 runtime：`docker/sandbox/features-tool/diagnosis_rule/`、`diagnosis/`、`ins/`、`tools/`、`proto/`、`models.py`、`context_index.py`
- Skill CLI：`skills/custom/rotating-fault-diagnosis/scripts/`
- Agent SOUL：`agents/builtin/fault-diagnosis--rotating/SOUL.md`
- 单测：`backend/tests/test_rotating_rule_runtime.py`、`backend/tests/test_fault_diagnosis_smoke.py`

## 规则镜像同步

`docker/sandbox/features-tool/` 下的 `diagnosis_rule/`、`diagnosis/`、`tools/`、`ins/`、`proto/`、`models.py`、`context_index.py` 构成旋转机组规则的受管运行时闭包，来源于现场 `mac-diag-code` 参考工程。

### 同步流程

1. 从 `mac-diag-code` 参考目录导出最新规则代码。
2. 将以下目录/文件覆盖到 `docker/sandbox/features-tool/`：
   - `diagnosis_rule/`（含 `workflow.py`、`context.py`、`config.py`、`config.json`）
   - `diagnosis/`（含 `models.py`、`context_index.py` 等）
   - `tools/`（含 `device_analysis.py`、`get_trend_data_tool.py`、`get_waveform_data_tool.py`、`get_orbit_data_tool.py`、`extract_*_tool.py` 等）
   - `ins/`（含 `client.py`、`config.py`）
   - `proto/`
   - `models.py`、`context_index.py`
3. 确认 `diagnosis_rule/rule_optimizer/` 已删除（Deer Flow 使用直连底层实现 + 受管缓存）。
4. 确认 `tools/device_analysis.py` 已拆分：仅保留原始子设备树获取，设备树语义推理已移入 Deer Flow Agent。
5. 运行现有单测验证兼容性：
   ```bash
   cd backend && python -m pytest tests/test_rotating_rule_runtime.py -v
   ```
6. 如有新增/变更故障类型，同步更新 `vibration-fault-diagnosis/SKILL.md` 规则书和 `config.json` 的 `fault_mapping`。

### 同步注意事项

- `config.json` 中的 `device_type_aliases`、`fault_mapping`、`thresholds` 直接影响打分行为，同步时需逐项对比。
- 若 `config.json` 新增阈值字段，需确认 `build_rotating_report_payload.py` 中的特征提取逻辑与之一致。
- 若 `workflow.py` 的 `DiagnosisResult` 字段有变化，需同步更新 `build_rotating_report_payload.py` 的 payload 映射。
- 波形/轨迹链路比趋势链路更依赖 `device_context.json` 中的探头挂载关系和精确 `timepoint`，同步后需验证 `context.py` 中的 `build_rule_device_context` 与新版兼容。

## 回滚

若需要回滚到旧 MVP 链路：

1. 回滚 `agents/builtin/fault-diagnosis--rotating/SOUL.md` 到旧的多轮表单和 `query_diagnosis.py` / `diagnosis_features.py` 执行方式。
2. 可保留 `diagnosis_rule` 运行时代码但不由 SOUL 调用。
3. 若回滚 config，同步恢复旧的 ins/orbit skill 列表和 `data-analyst` 脚本依赖。

## 已知限制

### 数据获取

- 真实 InS 取数依赖趋势、波形和轨迹工具返回字段，字段缺失时 runtime 会返回 warning 或结构化错误。
- `INS_ACCESS_TOKEN` 必须由 Deer Flow 运行上下文注入；未注入时取数失败，不会尝试用户名密码登录。
- `INS_BASE_URL` 为可选配置，未配置时使用 `diagnosis_rule/config.py` 默认地址。

### 波形/轨迹精确时刻匹配

- 波形和轨迹的异常时刻由规则引擎从趋势异常区间中选取（`_resolve_waveform_times`），报告阶段不再独立选点。
- 若趋势数据无异常区间，回退到输入时间前后各 1 天的全局峰值点。
- 轨迹取数优先复用规则上下文解析的探头挂载关系（`bearing_probe_map`），避免依赖 InS 原始树挂载。

### 缓存作用域

- 缓存文件仅在单次诊断的报告阶段复用，不做跨线程或跨次诊断共享。
- 缓存目录为 `{DIAGNOSIS_OUTPUT_DIR}/rotating_rule_cache/`，包含 `trend_*.json`、`trend_features_*.json`、`waveform_*.json`、`waveform_features_*.json`、`orbit_*.json`、`orbit_features_*.json`。
- 报告图表只允许使用规则阶段缓存数据，不在报告阶段重新采样。

### 设备树推理

- 设备树语义推理（设备类型、轴承方向、测点归属、结构补位）由 Deer Flow 诊断 Agent 完成，结果写入 `device_context.json`。
- `diagnosis_rule/context.py` 的 `build_rule_device_context` 依赖 Agent 已写出的 `device_context.json`，文件不存在时直接报错。
- `tools/device_analysis.py` 仅保留原始子设备树获取能力，不再自建独立模型运行时。

### 现场对比验证

- 现场参考 `/malfunction` 对比需要真实样例或录制数据；没有样例时不能标记对比完成。
- 参考目录 `/Users/gubailin/PycharmProjects/deer-flow-yh/mac-diag-code` 仅保留为临时对照来源，不作为运行依赖。
