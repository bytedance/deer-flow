## 1. SMS 查询脚本

- [x] 1.1 创建 `skills/custom/daily-report/scripts/query_sms_abnormal.py`，实现 SMS `/api/abnormal/list` 查询
- [x] 1.2 实现 CLI 参数解析：`--date`（必填）、`--equipment`（设备 ID 列表）、`--equipment-names`（设备名称列表）、`--type`（设备类型，默认 `rotating_machinery`）、`--output`（输出路径，默认 `/mnt/user-data/outputs/sms_abnormal.json`）
- [x] 1.3 实现 SMS API 直连请求：读取 `INS_BASE_URL` 和 `INS_ACCESS_TOKEN` 环境变量，用 `urllib.request` 发起 GET 请求，超时 30s
- [x] 1.4 实现客户端设备 ID 过滤：将 SMS 返回的 `rows[]` 按 `mac_id` 过滤（去连字符 + 小写标准化后匹配 `--equipment` 列表）
- [x] 1.5 实现严重等级映射：`latest_level >= 60` → `critical`，`41-59` → `high`，`21-40` → `medium`，`<= 20` → `low`
- [x] 1.6 实现输出合约：按 spec 定义的 JSON schema 输出 `sms_abnormal.json`，包含 `total_count`、`by_severity`、`by_status`、`by_type`、`top_events`
- [x] 1.7 实现错误处理：SMS API 不可用时输出 `{"sms_abnormal": {"error": "..."}}`，exit code 0（非致命）

## 2. 日报公共模块更新

- [x] 2.1 在 `_report_common.py` 的 `KPI_UNITS`、`KPI_DISPLAY_NAMES` 中注册 `sms_abnormal_count`（"SMS异常数"，单位"条"）和 `sms_abnormal_pending`（"待处理异常"，单位"条"）
- [x] 2.2 在 `_report_common.py` 中新增 `SMS_SEVERITY_MAP` 常量（level → label 映射）
- [x] 2.3 更新 `daily_kpi.py` 的 `compute()` 函数：当 `sms_abnormal.json` 存在时，将 `sms_abnormal_count` 和 `sms_abnormal_pending` 合并到 `kpi_summary`
- [x] 2.4 更新 `daily_kpi.py` 的 `_overall_status()` 函数：SMS 有 `latest_level >= 60` 的异常时，整体状态至少为 `warning`；结合 InS 高级告警时升级为 `danger`
- [x] 2.5 在 `daily_kpi.py` 中新增 `_build_sms_anomaly_table()` 函数，将 SMS `top_events` 转换为 DSL section 可消费的表格数据格式

## 3. DSL 模板更新

- [x] 3.1 在 `daily-equipment/default.yaml` 的 `data_steps` 中新增 `sms_abnormal` step，调用 `daily-report/query_sms_abnormal`
- [x] 3.2 在 `daily-equipment/default.yaml` 的 `transforms` 中新增 `sms_kpi_merge` step，将 SMS 数据合并到 KPI payload（实际在 `daily_kpi.py` 内部实现，无需独立 transform）
- [x] 3.3 在 `daily-equipment/default.yaml` 的 `sections` 中新增 `sms_abnormal_table` section（`component: table`，`source: $.steps.daily_kpi.daily_kpi.sms_abnormal_table`），标题 "SMS 异常事件"

## 4. 技能注册

- [x] 4.1 在 `skills/custom/daily-report/report_scripts.yaml` 中注册 `query_sms_abnormal` 脚本，声明 args 和 outputs
- [x] 4.2 在 `skills/custom/daily-report/report_scripts.yaml` 中注册 `sms_kpi_merge` transform（确认在 `daily_kpi.py` 内实现，无需独立脚本）

## 5. 测试

- [x] 5.1 编写 `query_sms_abnormal.py` 的单元测试：覆盖参数解析、设备 ID 标准化、严重等级映射、空结果、错误输出格式
- [x] 5.2 编写 `daily_kpi.py` SMS 合并逻辑的单元测试：覆盖 SMS KPI 注入、整体状态升级、空 SMS 数据降级
- [ ] 5.3 端到端验证：使用 DSL 模板生成旋转机组日报，确认 SMS 异常表格和 KPI 卡片正确渲染
- [ ] 5.4 边界验证：静设备类型日报不展示 SMS 章节；SMS API 不可用时日报仍正常生成
