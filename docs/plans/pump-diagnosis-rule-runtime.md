# 机泵诊断规则运行时说明

## 范围

`fault-diagnosis--pump` 现在走受管规则运行时：

1. 选择机泵设备与子设备。
2. 选择诊断日期和小时。
3. 调用 `skills/custom/pump-fault-diagnosis/scripts/run_pump_rule_diagnosis.py`。
4. 写出 `/mnt/user-data/outputs/pump_rule_result.json`。
5. 调用 `build_pump_report_payload.py` 生成 `diagnosis_features.json`。
6. 只向用户暴露 `diagnosis_report.md` / `diagnosis_report.pdf`。

本链路不考虑起停机状态，不导入或执行参考工程的 `stop/*` 逻辑。

## 环境变量

- `INS_ACCESS_TOKEN`：必需。Deer Flow 当前用户 Bearer token，由运行上下文注入 sandbox。
- `INS_BASE_URL`：可选。InS 基础地址，建议放在根 `config.yaml` 的 `sandbox.environment`。
- `DIAGNOSIS_OUTPUT_DIR`：可选。默认 `/mnt/user-data/outputs`。
- `FEATURES_TOOL_ROOT`：可选。默认 `/opt/features-tool`。
- `PUMP_RULE_FIXTURE`：仅测试/本地调试使用，指向 JSON fixture。

不要为该链路配置 `INS_USERNAME` / `INS_PASSWORD`、Nacos、MQ 或数据库连接作为生产依赖。

## 代码边界

- 受管 runtime：`docker/sandbox/features-tool/pump_rule/`
- Skill CLI：`skills/custom/pump-fault-diagnosis/scripts/`
- Agent SOUL：`agents/builtin/fault-diagnosis--pump/SOUL.md`
- 单测和 fixtures：`backend/tests/test_pump_rule_runtime.py`、`backend/tests/fixtures/pump_rule/`

## 测点获取

- 机泵运行时通过 `/ins-os-manage/organize/getPointConfigs?nodeId={machineId}&nodeType=4` 获取测点配置。
- 振动测点来自返回值 `data.vibPointConfig`，仅纳入 `type` 为 `23`、`24`、`26`、`27` 的测点。
- 温度测点来自 `data.staPointConfig`，用于温度健康规则。
- 子设备筛选使用 `componentId` 匹配；如果输入本身是 `posId`，则使用该测点所属 `componentId` 下的同组测点。
- `config` 字段按 JSON 字符串解析，提取 `bValue`、`cValue`、`dValue`、`vRmsBValue`、`vRmsCValue`、`vRmsDValue`、`tempH`、`tempHH` 等门限。

## 回滚

若需要回滚到旧 MVP 链路：

1. 回滚 `agents/builtin/fault-diagnosis--pump/SOUL.md` 到旧的多轮表单和 `query_diagnosis.py` / `diagnosis_features.py` 执行方式。
2. 可保留 `pump_rule` 运行时代码但不由 SOUL 调用。
3. 若回滚 config，同步恢复旧的 ins/orbit skill 列表。

## 已知限制

- 当前真实 InS 取数依赖 `getPointConfigs`、趋势和波形工具返回字段，字段缺失时 runtime 会返回 warning 或结构化错误。
- 当所选 `componentId` 或测点 `posId` 无法定位关联测点时，不会生成无依据结论。
- 报告图表只允许使用规则阶段缓存数据，不在报告阶段重新采样。
- 现场参考 `/malfunction` 对比需要真实样例或录制数据；没有样例时不能标记对比完成。
