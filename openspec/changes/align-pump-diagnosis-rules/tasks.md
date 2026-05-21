## 1. 参考运行时盘点

- [x] 1.1 盘点 `/Users/gubailin/PycharmProjects/deer-flow-yh/参考-机泵规则/algorithm-verification-py` 的最小依赖闭包，覆盖 `malfunction`、`health`、`basefreq`、`util`、`proto` 和必要的 `rpc/os` 数据契约
- [x] 1.2 识别并排除服务化依赖，包括 FastAPI 启动、MQ consumer、Nacos 配置、数据库模型、反馈路由，以及所有 `stop/*` 起停机模块
- [x] 1.3 从代表性机泵场景整理 fixtures，覆盖测点列表、趋势响应、带波形测值响应、波形 payload、阈值、轴承配置和 BPF 配置

## 2. 受管机泵规则运行时

- [x] 2.1 在 sandbox 可见位置新增受管机泵规则运行时包，例如 `docker/sandbox/features-tool/pump_rule/`
- [x] 2.2 移植或封装基频推断，复现参考实现中的 EMD、最大频率和标准转速匹配行为
- [x] 2.3 移植或封装 FFT、能量占比、倍频能量、轴承特征频率能量、BPF 能量和频带能量工具，并补充确定性单测
- [x] 2.4 实现不依赖起停机状态的健康异常判定，覆盖 C/D 区门限、12 小时内进入 C 区、速度趋势、加速度趋势、温度超限和温度趋势
- [x] 2.5 实现故障候选判定，覆盖不平衡、滚动轴承外圈、滚动轴承内圈、滚动轴承滚动体、滚动轴承保持架、不对中和 BPF 频率异常
- [x] 2.6 增加运行时自检，将缺失依赖、科学计算包不可用、测点上下文无效、波形解析失败等情况返回为结构化 error 或 warning

## 3. 数据访问与上下文适配

- [x] 3.1 实现适配器，将选中的 `machineId` / `componentId` 解析为目标子设备、关联振动测点、温度测点、测点名称、阈值字段、轴承特征频率配置和 BPF 配置
- [x] 3.2 实现趋势、带波形测值和波形获取 wrapper，使用 Deer Flow 运行时 token 注入和 sandbox 环境配置，不依赖 Nacos、MQ、数据库或独立登录凭据
- [x] 3.3 从实际 InS payload 归一化参考引擎输入字段，例如 `posId`、`config`、`cValue`、`rms_b`、`rms_c`、`rms_d`、`temp_h` 和温度通道标记
- [x] 3.4 将规则阶段趋势、波形、频谱和证据元数据缓存到 `/mnt/user-data/outputs/`，确保报告渲染复用同一批采样数据

## 4. Skill 与 CLI 契约

- [x] 4.1 创建或更新 `skills/custom/pump-fault-diagnosis/SKILL.md`，说明受管规则运行时、输入、输出文件、warnings 和不考虑起停机状态的范围
- [x] 4.2 实现 `scripts/run_pump_rule_diagnosis.py`，校验 `machineId`、`componentId`、子设备名称、诊断小时窗口、可选基频和输出路径
- [x] 4.3 确保 `run_pump_rule_diagnosis.py` 写出 `pump_rule_result.json`，包含 `ok`、`machine_id`、`component_id`、`target_info`、运行时元数据、`base_freq`、`health_findings`、`malfunction_findings`、`evidence`、采样数据引用、`warnings` 和结构化错误
- [x] 4.4 实现 `scripts/build_pump_report_payload.py`，将 `pump_rule_result.json` 转换为既有诊断报告 payload 形态或兼容的机泵专用 payload
- [x] 4.5 增加 CLI 层测试，覆盖成功、无发现、基频缺失、局部测点失败、配置字段缺失和运行时依赖错误

## 5. Agent 与报告集成

- [x] 5.1 更新 `agents/builtin/fault-diagnosis--pump/SOUL.md`，将输入流程改为 `fd-pump-device` 子设备选择器和 `fd-pump-time` 诊断时间表单
- [x] 5.2 确保机泵子设备选择器使用 `typeId=4` 和 `filterDeviceType=4`，并在时间回调后调用受管机泵规则 CLI
- [x] 5.3 更新报告渲染，从机泵报告 payload 展示设备/子设备摘要、健康发现、故障发现、证据表、warnings、建议和下载链接
- [x] 5.4 确保图表渲染只使用规则阶段缓存的趋势或频谱数据；当数据不可用时输出 warning，不执行独立报告阶段采样
- [x] 5.5 确保只通过 `present_files` 暴露 `diagnosis_report.md` 和 `diagnosis_report.pdf`，`pump_rule_result.json` 和缓存保持为内部产物
- [x] 5.6 保留严重机泵发现触发闭环单的能力，并使用最终 Markdown 报告 URI 作为证据

## 6. 验证与发布

- [x] 6.1 为受管机泵运行时的健康规则和故障规则计算增加基于 fixtures 的单元测试
- [x] 6.2 增加集成或 smoke 覆盖，验证机泵 SOUL 从 `fd-pump-device -> fd-pump-time` 回调到规则 CLI 执行、报告 payload 生成和最终导出的流程
- [ ] 6.3 至少用两个 fixture 或真实设备案例对比参考 `/malfunction` 行为，确认故障类型、概率区间、证据测点和基频一致
- [x] 6.4 验证受管机泵诊断路径没有导入或执行任何起停机状态模块
- [x] 6.5 补充规则同步、回滚路径、已知数据字段假设、不考虑起停机状态限制和演示 fallback 强提示说明
