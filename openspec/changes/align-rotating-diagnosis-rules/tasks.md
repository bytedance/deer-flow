## 1. 规则运行时收敛

- [x] 1.1 盘点 `mac-diag-code` 旋转机组规则链路的完整 Python 依赖闭包，确认 `diagnosis.*`、`rule_optimizer`、`ins`、`tools` 和 `proto` 的真实来源
- [x] 1.2 为 `models.py` / `context_index.py` 补齐 `diagnosis.*` namespace 兼容层，并把 `rule_optimizer` 引用替换为直连底层实现
- [x] 1.3 在 Deer Flow 仓库内落地受管的旋转机组规则运行时包，并新建独立 skill `skills/custom/rotating-fault-diagnosis/` 作为 Agent 调用入口，避免默认依赖用户本机绝对路径
- [x] 1.4 改造 `ins` client 和相关 tool 入口，支持 Deer Flow Bearer token 透传并移除运行时重复登录依赖
- [x] 1.4.1 在 Deer Flow `config.yaml` 的 `sandbox.environment` 中为 `INS_BASE_URL` 预留可选注入位，并约定未配置时回落到工具默认值
- [x] 1.5 拆分 `device_analysis.py`，保留原始子设备树获取，移除其脚本内独立 Agent/Runner/Model 运行时
- [x] 1.6 为受管运行时增加自检与配置入口，确保缺失依赖时返回结构化错误而不是静默回退

## 2. 交互契约与真实规则执行接入

- [x] 2.1 设计并落地三层交互契约：可导入 Python package、稳定 CLI 包装器、标准 JSON / artifact 文件
- [x] 2.1.1 在 `skills/custom/rotating-fault-diagnosis/` 下补齐 `SKILL.md` 和 `scripts/` 入口，不改 `skills/custom/data-analyst/`
- [x] 2.2 实现 Bearer token 从 Deer Flow 线程/运行上下文注入 CLI 适配脚本和底层 `ins` client 的路径
- [x] 2.3 实现旋转机组规则执行适配脚本，封装 `run_diagnosis(device_id, sub_device_id, time)` 并输出稳定 JSON 结果文件
- [x] 2.4 在适配层中补充 client cleanup、运行时版本信息、warnings 收集和异常序列化
- [x] 2.5 在规则执行过程中缓存或导出趋势、频谱、轨迹作图所需的原始数据，定义统一文件命名和目录作用域
- [x] 2.6 确保报告阶段只读取这些缓存文件绘图，不再重新调用外部取数接口

## 3. Agent 与报告集成

- [x] 3.1 把设备树语义推理并入 `fault-diagnosis--rotating` Agent 能力或共享 helper，复用同一模型上下文
- [x] 3.2 更新 `fault-diagnosis--rotating/SOUL.md`，把旋转机组主链路切换为“GenUI 收参 → Agent 内设备树推理 → CLI 适配脚本 → 文件契约 → 报告渲染”
- [x] 3.3 实现从真实规则结果到 Deer Flow 报告 payload 的映射，保留主诊断、候选诊断、得分、置信度、证据摘要与建议
- [x] 3.4 更新诊断报告渲染与导出链路，使趋势图、频谱图、轨迹图和 warnings 来自真实规则执行数据
- [x] 3.5 确保旋转机组链路最终只交付 `diagnosis_report.md` / `diagnosis_report.pdf`，不暴露规则结果和图表中间文件

## 4. 验证与运维

- [x] 4.1 为真实规则执行适配层增加单元测试，覆盖成功、无候选故障回退和依赖缺失错误三类场景
- [ ] 4.2 为旋转机组全链路增加 smoke / integration 测试，覆盖“表单收参 → 规则执行 → payload → 导出”流程
  - 进展：已于 2026-05-20 收敛 `backend/tests/test_fault_diagnosis_smoke.py`，将旋转机组 smoke 断言切换为匹配当前“两步表单 + 真实规则脚本 + 缓存报告”契约，并保持机泵/往复机旧链路断言不变。
  - 未完成：仍缺少真正执行 `fd-rotating-device -> fd-rotating-time -> run_rotating_rule_diagnosis.py -> build_rotating_report_payload.py -> diagnosis_report.*` 的集成测试，因此本项暂不勾选。
- [ ] 4.3 用录制案例或现场样例对比 Deer Flow 输出与 `mac-diag-code` 原始输出，确认主诊断、候选诊断和建议一致
  - 进展：当前 `/Users/gubailin/PycharmProjects/deer-flow-yh/mac-diag-code` 仅保留为临时对照来源，不再作为运行依赖。
  - 未完成：在完成 2~3 组录制 case 对比并确认 Deer Flow 输出一致前，暂不删除该目录，也不勾选本项。
- [ ] 4.4 补充规则镜像同步、回滚方式和已知限制文档，明确后续如何跟随现场规则更新
  - 未完成：需补充 `docker/sandbox/features-tool/` 同步流程、旋转 SOUL 回滚路径，以及 `INS_ACCESS_TOKEN` / `INS_BASE_URL` / 缓存仅报告期复用等限制说明。
