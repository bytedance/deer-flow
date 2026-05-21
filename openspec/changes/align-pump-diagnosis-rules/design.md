## Context

`fault-diagnosis--pump` 当前 SOUL 采用机泵专用多轮输入：先收集时间窗、设备类型、诊断模式和对比方式，再用 `device-selector-multi` 选择多台机泵设备，随后动态提取测点、选择关键测点和故障家族焦点，最后调用 `query_diagnosis.py`、深度采样脚本和 `diagnosis_features.py` 输出报告。用户现在明确要求输入方式与旋转机组一致：只选择一个设备下的子设备和一个诊断时间，然后执行。

用户提供的参考工程位于 `/Users/gubailin/PycharmProjects/deer-flow-yh/参考-机泵规则/algorithm-verification-py`。其关键入口和算法边界为：

- `api/routes.py:/malfunction`：通过 `get_point_list_by_mac_id(mac_id, 4)` 获取机泵振动测点，使用 10 天窗口，基频缺失时调用 `basefreq.BaseFreq.calc`，最后进入 `malfunction.MalFunctionCheck.process_check`。
- `malfunction/MalFunctionCheck.py`：对测点调用 `get_value_with_wave`、`get_wave`，每点最多取最近 5 组波形，计算倍频能量、轴承特征频率能量和 BPF 能量。
- `malfunction/Unbalance.py`：以 1X 能量占比和 C 区门限过滤判断不平衡，概率封顶。
- `malfunction/Bearing.py`：判断滚动轴承外圈、内圈、滚动体、保持架故障，使用主频、二倍频和边带能量。
- `malfunction/FrequencyFault.py`：判断不对中和 BPF 频率异常。
- `basefreq/BaseFreq.py`：基于 10 天内波形、EMD 和最大幅值频率，在标准转速 12.5 / 25 / 50 Hz 附近推断基频。
- `health/*`：包含 C/D 区门限、速度/加速度/温度趋势和短期异常逻辑。
- `stop/*`：起停机状态判断。本次明确排除，不进入 Deer Flow 机泵 Agent。

旋转机组 Agent 已经采用“两步输入 + Agent 内设备上下文推理 + 独立 skill CLI + 规则运行时 JSON + 报告 payload + 最终文件导出”的形态。机泵应采用同样交互与运行边界，而不是保留多设备筛查式输入，也不是把参考工程作为一个 FastAPI 服务直接挂进来。

## Goals / Non-Goals

**目标：**

- 让 `fault-diagnosis--pump` 的输入方式与旋转机组一致：先选择机泵设备与子设备，再选择诊断日期和小时。
- 让 `fault-diagnosis--pump` 的正式诊断结论来自受管机泵规则运行时，而不是 `diagnosis_features.py` 对规则文档的二次匹配。
- 将参考工程中的基频推断、波形采样、FFT 能量比、不平衡、滚动轴承、不对中、BPF 频率异常和健康异常判定整理为 Deer Flow 可运行资产。
- 输出稳定 JSON 文件契约，供 SOUL、报告渲染、测试和后续规则同步共同依赖。
- 明确排除起停机状态，任何诊断请求都不因“启停机 12 小时内”跳过振动诊断。

**非目标：**

- 不保留本次机泵诊断的多设备批量筛查、关键测点手工多选、故障家族焦点选择输入。
- 不把参考工程作为常驻 FastAPI 服务、MQ 消费服务或 Nacos 托管服务接入。
- 不新增前端组件或后端路由。
- 不重写参考算法的阈值和概率公式，除非是为了修复 Deer Flow 运行时输入/输出适配问题。
- 不接入 `stop/` 起停机判断，也不实现停机值自动学习。
- 不在本次接入真实历史案例库；历史案例可保留空数组或后续单独接入。

## Decisions

### 1. 机泵 Agent 输入对齐旋转机组的两步交互

决策：

- 首次进入时渲染 `sub-device-selector`，`queryParams` 使用 `typeId=4`，并设置 `filterDeviceType=4`，让用户选择机泵设备与子设备。
- 子设备回调后只渲染诊断时间表单，字段为 `diagnosis_date` 和 `diagnosis_hour`，默认小时可沿用旋转机组的 `8`。
- 时间表单回调后拼装 1 小时诊断窗口：`start_iso = diagnosis_date + diagnosis_hour:00:00`，`end_iso = diagnosis_date + diagnosis_hour:59:59`。
- 规则入口只接收当前轮最近一次 `fd-pump-device` 和 `fd-pump-time` 回调参数，不复用更早轮次。

原因：

- 用户明确要求“输入也是跟机组一样，选个子设备和时间，然后执行”。
- 该方式与旋转机组 SOUL 的参数回溯、校验和执行节奏一致，能减少 Agent 行为差异。

备选方案：

- 保留现有 Round 1 / Round 1.5 / Round 2 多设备流程。拒绝，原因是与用户最新输入要求不一致。

### 2. 采用受管机泵规则运行时，而不是直接运行外部目录或服务

决策：

- 将参考工程中诊断所需的最小依赖闭包整理进 Deer Flow 仓库受管位置，例如 `docker/sandbox/features-tool/pump_rule/`。
- 不依赖 `/Users/gubailin/.../参考-机泵规则` 作为运行路径；该目录只作为实现对照来源。
- 不启动参考工程的 `main.py` / FastAPI / MQ consumer。

原因：

- 外部目录和 Nacos/MQ/数据库配置不可部署、不可复现。
- Deer Flow Agent 只需要线程内诊断，不需要引入一个新的常驻服务面。

备选方案：

- 直接在 SOUL 中调用外部工程。拒绝，原因是路径不可控且生产环境不可用。
- 按参考工程 Dockerfile 启动服务。拒绝，原因是新增运维面，并且接口只暴露 `/malfunction`，不足以支撑报告缓存和 Deer Flow 文件契约。

### 3. 新建独立 pump 规则 skill 和 CLI 文件契约

决策：

- 在 `skills/custom/pump-fault-diagnosis/` 下提供稳定入口，例如：
  - `scripts/run_pump_rule_diagnosis.py`
  - `scripts/build_pump_report_payload.py`
  - `SKILL.md`
- SOUL 调用 CLI，输入 `machineId`、`componentId`、子设备名称、1 小时诊断窗口和输出路径。
- CLI 输出 `/mnt/user-data/outputs/pump_rule_result.json`，报告映射脚本输出 `/mnt/user-data/outputs/diagnosis_features.json` 或等价 payload。

原因：

- 旋转机组 Agent 已采用独立垂直 skill，机泵跟随这一模式可降低 SOUL 复杂度。
- CLI + 文件契约便于单测、人工复跑和失败诊断。

备选方案：

- 继续把规则逻辑塞入 `skills/custom/data-analyst/scripts/diagnosis_features.py`。拒绝，原因是会把通用报表脚本和真实机泵规则运行时耦合。

### 4. 规则输入以设备与子设备为中心，测点从 InS/2K 设备树映射

决策：

- 机泵规则运行时以 `machineId` 和 `componentId` 为主输入；运行时解析该设备树，并确定所选子设备关联的振动测点、温度测点和测点配置。
- 对齐参考工程 `get_point_list_by_mac_id(mac_id, 4)` 的语义，但在 Deer Flow 内通过已有 InS/2K 工具或受管客户端实现，不依赖参考工程 RPC/Nacos。
- 当所选 `componentId` 是轴承、转子、测点或其他子设备时，适配层必须能将其归一化为诊断目标，并收敛到相关测点集合。

原因：

- 参考算法依赖测点配置中的 `cValue`、轴承特征频率、BPF 配置等字段，单纯的用户测点枚举不足以执行真实判定。
- 子设备输入可以把诊断范围收敛在用户关注的部件，同时保留规则运行时自动解析测点的能力。

备选方案：

- 只把现有 `query_diagnosis.json` 作为规则输入。拒绝，原因是它未必携带波形、频谱和配置字段，也不以子设备为目标。

### 5. 诊断时间采用单小时窗口，基频推断默认回看 10 天

决策：

- 故障判定使用用户选择小时形成的 1 小时窗口作为主诊断窗口。
- 当用户未提供基频时，基频推断沿用参考工程策略：从诊断结束时间向前回看 10 天，基于波形和标准转速集合推断。
- 每个测点最多选择 5 组候选波形；优先复用参考工程“按时间倒序取最近波形”的行为，必要时在报告中标注实际采样时间。

原因：

- 旋转机组 Agent 的诊断时间输入是单日期 + 小时，脚本内部用 1 小时窗口执行。
- 参考工程 `/malfunction` 入口固定用 10 天窗口；本设计以用户小时窗口为本轮诊断目标，以 10 天回看仅服务基频推断。

备选方案：

- 保留用户可选起止时间窗。拒绝，原因是用户要求与旋转机组一致。

### 6. 明确删除起停机门控，但保留健康异常规则

决策：

- 不迁移 `stop/CheckStop.py`、`stop/StopValue.py`，不执行 `health.process.health_check` 中的 `check_stop` 分支。
- 将健康异常拆为无停机门控的规则集合：温度超限、C/D 区、12h 内进入 C 区、速度 1/3/7 天趋势、加速度短期/3/7 天趋势、温度短期/3/7 天趋势。
- 健康异常进入 `health_findings`，故障候选进入 `malfunction_findings`，最终报告分别展示。

原因：

- 用户明确“不考虑起停机状态”。
- 健康异常规则不等同于起停机状态，仍有诊断价值。

备选方案：

- 整体放弃 `health/*`。不采用，原因是会丢失参考工程里门限和趋势类告警能力。

### 7. 输出模型分为原始规则结果和报告 payload

决策：

- `pump_rule_result.json` 包含：
  - `ok`
  - `machine_id`
  - `component_id`
  - `target_info`
  - `base_freq`
  - `health_findings[]`
  - `malfunction_findings[]`
  - `evidence[]`
  - `sampled_waveforms[]`
  - `warnings[]`
  - `runtime`
- 报告 payload 包含：
  - 设备 / 子设备摘要卡片
  - 主诊断 / 备选诊断 / 置信度 / 严重等级
  - 证据链表格
  - 趋势、频谱图表数据
  - 处置建议和执行告警
  - 闭环单触发字段

原因：

- 规则结果适合算法验证，报告 payload 适合 UI 和导出。分层可以避免报告格式反向污染算法结构。

备选方案：

- 让 SOUL 直接解释算法内部对象。拒绝，原因是不可测试且容易漂移。

### 8. 鉴权与取数沿用 Deer Flow 运行上下文

决策：

- 取数层使用 Deer Flow 注入的当前用户 token，例如 `INS_ACCESS_TOKEN`。
- 不在机泵规则运行时中使用参考工程的 Nacos、MQ、数据库或独立登录配置。
- `INS_BASE_URL` 等部署级地址沿用 sandbox 环境配置，未配置时使用受管工具默认值。

原因：

- 与旋转机组真实规则链路保持一致，避免重复鉴权和凭据扩散。

备选方案：

- 迁移参考工程完整配置体系。拒绝，原因是增加安全和运维复杂度。

### 9. 失败模式显式化

决策：

- 真实规则运行时依赖缺失、取数失败、关联测点为空、波形解析失败时，返回结构化错误或 warnings。
- 若无法得到任何有效证据，报告必须说明“未形成有效规则结论”，不得静默回退为正式诊断。
- 允许保留 demo fallback 作为开发测试路径，但最终报告顶部必须强提示，且不得标记为真实规则结论。

原因：

- 诊断结果属于高风险工程判断，静默 fallback 会让用户误以为结论来自现场规则。

## Risks / Trade-offs

- [参考工程依赖闭包不完整] -> 先做最小可导入闭包盘点，剔除服务化依赖，针对 `rpc/os`、proto、FFT/EMD 和 InS 客户端写自检。
- [测点配置字段与 Deer Flow 当前 InS 返回不一致] -> 增加适配层字段归一化和 fixtures；字段缺失时给出 warning 并跳过依赖该字段的规则。
- [子设备与规则测点集合映射不准] -> 参考旋转机组设备上下文推理方式，基于设备树、部件名称、测点类型和归属关系生成 `target_info`，并在无法定位时显式失败。
- [基频推断取数成本高] -> 缓存基频和波形摘要到本次线程输出目录；后续可按设备/日期增加受控缓存。
- [健康异常无停机门控可能带来误报] -> 报告中明确“不考虑起停机状态”，并把健康异常与故障候选分开展示。
- [报告图表与规则证据不一致] -> 图表必须优先来自规则执行阶段已采样/缓存的数据，不在报告阶段重新选择异常时刻。

## Migration Plan

1. 先落地受管机泵规则运行时和 CLI 自检，不切换 SOUL 主链路。
2. 用 fixtures 和少量真实设备样例验证 `pump_rule_result.json` 与参考工程 `/malfunction` 输出一致。
3. 实现报告 payload 映射和导出测试。
4. 更新 `fault-diagnosis--pump/SOUL.md`，把输入流程切换为 `fd-pump-device -> fd-pump-time -> run_pump_rule_diagnosis.py`。
5. 保留旧 `query_diagnosis.py` 路径作为开发对照，但正式报告不静默回退。
6. 若发布后需要回滚，仅回滚 SOUL 到旧脚本链路，受管规则运行时代码可保留不启用。

## Open Questions

- Deer Flow 当前 2K 设备树是否稳定返回参考工程所需的全部配置字段：`cValue`、`rms_b`、`rms_c`、`rms_d`、轴承特征频率、BPF 配置。
- 温度测点的 `dcChannelId == "T"` 语义在 Deer Flow 现有 InS 工具中对应哪个字段。
- 当用户选中的 `componentId` 是单个测点时，是只诊断该测点，还是自动扩展到同一轴承/子设备下的关联测点；建议实现为优先扩展到同一子设备关联测点，并在 `target_info` 记录扩展原因。
