## Context

当前 Deer Flow 的旋转机组诊断链路由 `fault-diagnosis--rotating/SOUL.md` 驱动，核心依赖 `query_diagnosis.py` 和 `diagnosis_features.py`。这套链路的优势是能在 Deer Flow 内闭环完成 GenUI、报告导出和 smoke test，但它本质上仍是“趋势聚合 + 规则文档关键词匹配”的 MVP。

用户已经在 `/Users/gubailin/PycharmProjects/deer-flow-yh/mac-diag-code` 放置了现场正在运行的真实规则实现。该实现的主入口是 `diagnosis_rule/workflow.py:run_diagnosis(device_id, sub_device_id, time)`，其内部已经固化了：

- 设备上下文解析
- 1d / 3d / 30d 趋势采集
- 异常波形时刻选择
- 波形频谱与轨迹特征提取
- 候选故障打分、竞争、封顶和置信度计算
- 主故障、备选故障、运行建议和检修建议输出

但这份代码当前不是 Deer Flow 可直接复用的稳定依赖，有两个明显约束：

- 你补进来的依赖已经把 `models.py`、`context_index.py` 等核心文件放回了 `mac-diag-code`，但当前目录结构仍然不是 `diagnosis/context_index.py`、`diagnosis/models.py` 这种 import 形态，说明还需要 namespace 兼容层或包重组。
- `diagnosis_rule.rule_optimizer` 目录仍未出现在当前快照里；结合调用点分析，它更像缓存 / 包装层而不是规则算法本体，因此本次设计应直接删除这层依赖，而不是继续追它的实现。
- 当前 `ins` 客户端和若干 `tools/*.py` 默认从 `INS_USERNAME` / `INS_PASSWORD` 出发自行登录换 token，这与 Deer Flow 已有会话认证重复，且用户已确认 Deer Flow token 与 InS token 通用。
- 当前 `tools/device_analysis.py` 会自行构造 `Agent`、`Runner`、`OpenAIChatCompletionsModel` 和 tracing 配置来分析设备树，这与 Deer Flow 已有 Agent 编排重复，且会形成“主 Agent 内再套一个独立模型运行时”。
- Deer Flow 当前的报告渲染契约并不认识 `DiagnosisResult`，而是基于 `diagnosis_features.json` 一类结构化 payload。

因此，这次设计不是简单“从外部目录 import workflow.py”，而是要定义一条可测试、可部署、可回滚的规则运行时接入方案。

## Goals / Non-Goals

**Goals:**

- 让 `fault-diagnosis--rotating` 的主诊断结论严格来自 `mac-diag-code` 的真实规则执行链路，而不是 Deer Flow 当前的关键词匹配 MVP。
- 把真实规则引擎输出稳定映射为 Deer Flow 可消费的 JSON payload、GenUI blocks 和 Markdown/PDF 报告。
- 保留 Deer Flow 现有的线程、表单、导出和 `present_files` 交付方式，只替换旋转机组诊断的决策核心。
- 建立受管的规则运行时边界，使实现不依赖用户机器上的绝对路径，且缺失依赖时能给出可操作的错误。

**Non-Goals:**

- 不在本次设计中重构机泵或往复机的诊断主链路。
- 不重写 `mac-diag-code` 的规则算法本身，不改动其打分逻辑。
- 不在本次设计中接入真实历史案例库；历史案例仍可先保持占位或后续单独接入。
- 不新增前端组件或新的后端路由。

## Decisions

### 1. 采用“受管规则运行时”而不是直接依赖用户本机路径

决策：

- 将 `mac-diag-code` 中旋转机组诊断所需的代码及其依赖闭包整理为 Deer Flow 仓库内可控的运行时包。
- Agent 入口脚本单独落在 `skills/custom/rotating-fault-diagnosis/`，不复用也不改造现有 `skills/custom/data-analyst/`。
- Deer Flow 运行时只通过受管入口加载该包；开发环境可以允许显式配置外部镜像路径用于对比，但默认路径必须是仓库内可用资产。

原因：

- 当前外部目录并不自包含，直接 import 用户本机目录会造成部署不可复现。
- 规则和取数逻辑一旦成为核心生产路径，就必须有明确版本边界、测试夹具和回滚手段。

备选方案：

- 直接在 SOUL 里用绝对路径执行 `workflow.py`。拒绝，原因是不可部署、不可测试、且依赖缺失时错误不可控。
- 在 Deer Flow 里重写一份等价规则。拒绝，原因是会再次形成双实现漂移。

### 2. 新增确定性适配脚本，统一 Agent 与规则运行时的契约

决策：

- 在 `skills/custom/rotating-fault-diagnosis/scripts/` 下新增旋转机组专用适配入口，例如 `run_rotating_rule_diagnosis.py`，输入为 `device_id`、`sub_device_id`、`diagnosis_time`，输出为稳定 JSON，例如 `rotating_rule_result.json`。
- 适配层负责：
  - 初始化规则运行时依赖路径
  - 调用 `run_diagnosis(...)`
  - 将 dataclass / model 输出转为纯 JSON
  - 收集异常、warnings、运行耗时和运行时版本信息
  - 在退出前执行 client cleanup

原因：

- SOUL 更适合调用稳定脚本，不适合直接理解复杂 Python 结构。
- 适配层可以把异步资源管理、依赖检查和日志采集收敛到一个地方。

备选方案：

- 让 SOUL 通过内联 Python 直接 import 规则运行时。拒绝，原因是 prompt 侧可维护性差，且错误边界分散。

### 3. 删除 `rule_optimizer` 依赖，但保留受管原始数据缓存

决策：

- 不再为接入 Deer Flow 而恢复 `diagnosis_rule.rule_optimizer.cache`。
- 将 `cached_analyze_device`、`cached_get_trend_data`、`cached_extract_trend_features`、`cached_extract_segmented_trend_features`、`cached_extract_waveform`、`cached_extract_orbit` 全部替换为对现有底层实现的直接调用。
- 与此同时，在 Deer Flow 侧补一层受管原始数据缓存，把诊断过程中拿到的原始趋势、波形频谱、轨迹数据落盘到线程/运行作用域目录，供报告绘图直接复用。

原因：

- 现有 `rule_optimizer` 看起来只负责缓存和包装，不承载故障判定语义。
- 去掉它可以显著降低外部依赖闭包的复杂度。
- 原始数据不能丢，因为报告阶段还要画趋势图、频谱图、轨迹图，且必须与本次诊断结论使用的是同一批数据。

备选方案：

- 把 `rule_optimizer` 一并补回。拒绝，原因是会引入一层额外、不可见且当前缺失的缓存依赖，收益低于维护成本。
- 完全不缓存原始数据。拒绝，原因是报告阶段将被迫重新取数，造成图与结论不一致。

### 4. Python 代码与系统采用“三层交互契约”

决策：

- 规则代码对 Deer Flow 暴露三种交互面，但只允许其中一种进入用户对话主链路：
  - Python package 接口：供单元测试、适配层和后续复用直接 import
  - CLI 接口：供 `fault-diagnosis--rotating` 的 SOUL / shell 调用，输入输出稳定
  - 文件契约：供报告链路消费 `rotating_rule_result.json`、图表缓存和最终 report artifacts
- 当前阶段不把这套规则代码做成新的 HTTP 服务、MCP server 或独立常驻 worker。

原因：

- package 接口便于测试和内部复用。
- CLI 接口最适合当前 Agent 通过 bash 调用的系统形态；但它应当收敛在独立 skill `skills/custom/rotating-fault-diagnosis/` 中，而不是继续堆进 `data-analyst`。
- 文件契约能把“诊断执行”和“报告渲染”解耦，便于复跑、调试和人工比对。

备选方案：

- 直接把规则代码接成 FastAPI/HTTP 服务。拒绝，原因是本次只需要线程内诊断，不值得新增运维面。
- 直接做成 builtin tool。暂不采用，原因是 builtin tool 仍需要稳定的 Python 入口，而 CLI + file contract 更容易先落地和对比。

### 5. `device_analysis.py` 的模型推理并入 Deer Flow Agent 能力

决策：

- 不保留 `device_analysis.py` 当前“脚本内部再起一个独立 Agent/Runner/Model”的形态。
- 将它拆成两层：
  - 原始子设备树获取：保留为底层数据工具
  - 设备树推理与结构补全：并入 Deer Flow 当前诊断 Agent 的能力，使用同一条会话中的模型、prompt、tracing 和配置
- 若后续多个诊断 Agent 都需要这一步，可把“设备树解释 schema + 提示约束”提炼为共享 helper / skill，而不是独立模型脚本。

原因：

- 嵌套模型运行时会重复配置模型、tracing、认证和错误处理。
- 设备树解释本身属于诊断推理的一部分，放回主 Agent 内更便于统一上下文和后续审计。
- Deer Flow 已经有 Agent 框架，不值得在脚本里再维护一套小型单独 Agent。

备选方案：

- 继续保留 `device_analysis.py` 的独立 Agent 形态。拒绝，原因是运行路径不透明，且会造成双重模型编排。
- 彻底改成纯规则/纯函数。暂不采用，原因是设备树补位与结构归并仍带有较强语义判断，短期内仍需要模型参与。

### 6. 数据接口鉴权采用 Deer Flow token 透传

决策：

- 旋转机组诊断运行时调用 InS 数据接口时，直接透传 Deer Flow 当前用户的 Bearer token。
- 禁止这套 Python 代码在运行期再次使用 `INS_USERNAME` / `INS_PASSWORD` 调登录接口换 token。
- CLI 适配脚本和底层 `ins` client 需要接受显式传入 token，优先级高于任何环境变量登录配置。

原因：

- 用户已确认 Deer Flow token 与 InS token 通用，再登录一次是重复且不必要的。
- 透传用户 token 能保持最小权限原则，取数审计也与当前用户一致。
- 避免在诊断运行时额外依赖账号密码配置，减少部署和安全面。

备选方案：

- 继续保留用户名密码登录。拒绝，原因是会重复鉴权，并增加凭据管理负担。
- 由后端统一代取 token 再注入。当前不采用，原因是现有 token 已可直接复用，没有必要再加一层交换逻辑。

### 6.1 `INS_BASE_URL` 放在 `config.yaml` 的 `sandbox.environment`

决策：

- `INS_BASE_URL` 保留为可选部署配置，放在 Deer Flow 根 `config.yaml` 的 `sandbox.environment` 下。
- CLI 适配脚本和 sandbox 内 Python 工具从环境读取该值；未配置时回落到 `mac-diag-code/ins/config.py` 的默认地址。
- `INS_BASE_URL` 不进入线程上下文、GenUI 表单、Agent prompt，也不作为每次诊断的用户输入参数。

原因：

- 当前旋转机组规则链路是通过 sandbox 内 Python 运行时执行的，`sandbox.environment` 是现成且边界清晰的部署级注入点。
- 仓库里现有 `rpc.services` 配置用于 Deer Flow 自己维护的 Java RPC 客户端，例如 `ins-bus-rpc`、`ins-base-rpc`，不适合承载这批外部 Python 工具的基础地址。
- `INS_BASE_URL` 属于环境级目标系统地址，而不是用户态数据；把它放进请求上下文会把部署配置错误建模成会话输入。

备选方案：

- 放进线程上下文或表单参数。拒绝，原因是会把部署配置和用户输入混在一起。
- 新增 Deer Flow 专用 typed config，如 `ins_data.base_url`。当前不采用，原因是短期内这条链路仍以 sandbox 工具为主，先复用 `sandbox.environment` 更低成本；若后续把取数完全内收进 `backend/packages/harness/deerflow/`，再升级为 typed config 更合理。

### 6.2 Agent 入口脚本使用独立旋转诊断 skill

决策：

- 不修改 `skills/custom/data-analyst/`，也不把旋转机组规则适配脚本塞进其 `scripts/`。
- 新建独立 skill 目录 `skills/custom/rotating-fault-diagnosis/`，至少包含：
  - `SKILL.md`
  - `scripts/run_rotating_rule_diagnosis.py`
  - `scripts/build_rotating_report_payload.py`
  - 需要时补 `scripts/run.sh` 作为统一 shell 入口

原因：

- `data-analyst` 已承载通用报表和查询脚本，继续叠加真实规则运行时会让边界变得混乱。
- 旋转机组故障诊断是垂直能力，单独 skill 更符合现有 `pump-fault-diagnosis`、`reciprocating-fault-diagnosis` 的组织方式。
- 单独 skill 更利于后续权限、依赖、smoke test 和版本同步单独管理。

备选方案：

- 继续复用 `skills/custom/data-analyst/scripts/`。拒绝，原因是会把通用分析脚本层和真实规则运行时耦合到一起。

### 7. 旋转机组报告改为“两段式数据面”：规则结果文件 + Deer Flow 报告 payload

决策：

- 保留 Deer Flow 现有报告出口，但在旋转机组链路中引入两个中间层：
  - `rotating_rule_result.json`: 规则运行时原生结果的 JSON 化版本
  - `diagnosis_features.json` 或等价 payload：面向 GenUI / Markdown / PDF 的规范化报告数据
- 报告 payload 必须显式承载：
  - 主诊断 / 备选诊断 / 置信度 / 得分
  - 证据摘要与规则命中原因
  - 趋势、频谱、轨迹图数据或图表配置
  - 运行建议、检修建议、warnings
  - 运行时元信息（规则版本、数据源、执行时间）

原因：

- `DiagnosisResult` 适合规则计算，不适合直接做 UI 契约。
- 规范化 payload 可以复用现有导出逻辑，也便于写稳定单测。

备选方案：

- 让 `export_diagnosis_report.py` 直接读取 `DiagnosisResult`。拒绝，原因是会把导出层和规则层强耦合，降低可测试性。

### 8. 图表数据优先复用规则运行时已获取的原始数据，避免重复采样

决策：

- 报告需要的趋势、频谱、轨迹图，必须优先读取诊断阶段已落盘的原始数据缓存。
- 若当前 `DiagnosisResult` 未携带足够的作图原始数据，则适配层必须在规则执行过程中显式写出这些缓存文件，而不是在报告阶段重新发起一轮独立采样。

原因：

- 重新采样会导致“结论依据的数据”和“图上显示的数据”不一致。
- 规则运行时已经定义了波形时间点选择逻辑，报告层不应自作主张再选一次。

备选方案：

- 保留现有 `diagnosis_features.py` 的深采样流程继续补图。部分拒绝，原因是会再次形成两套时间点选择逻辑；仅可作为过渡阶段的兜底实现。

### 9. 对旋转机组禁用“静默 demo fallback”，改为显式失败或受控降级

决策：

- 当真实规则运行时不可用、依赖不完整或关键取数失败时，旋转机组链路不得静默回退到当前关键词匹配 MVP 并继续输出“看似正式”的诊断结论。
- 允许的行为只有两种：
  - 显式失败，并给出可操作的错误
  - 在用户明确接受的前提下进入“演示模式/占位模式”，且报告顶部必须强提示

原因：

- 用户这次的目标是“按照现在在跑的规则来”，静默回退会破坏这个前提。

备选方案：

- 保留现在的 demo fallback 作为默认。拒绝，原因是会掩盖真实运行时问题。

## Risks / Trade-offs

- [外部规则代码依赖闭包不完整] → 先做依赖收敛清单和最小可运行包抽取；对 `rule_optimizer` 直接删依赖，对 namespace 缺口加兼容层；未通过导入自检时禁止切换生产链路。
- [规则运行时与 Deer Flow 仓库双向漂移] → 通过受管镜像目录、版本标识和同步流程控制，必要时记录来源 commit / snapshot 日期。
- [图表渲染需要的原始数据未在 `DiagnosisResult` 中暴露] → 适配层在规则执行期缓存 trend / waveform / orbit 原始结果，报告层只读这些缓存文件。
- [数据层仍尝试自行登录换 token] → 统一改造 `ins` client 和相关 tool 入口，优先使用透传 token；测试覆盖“无用户名密码但有 Bearer token”路径。
- [设备树分析仍走脚本内独立模型] → 将模型推理并回 Deer Flow Agent 能力，底层脚本只保留取数与数据变换。
- [接入真实规则后诊断耗时上升] → 对趋势、波形、轨迹接口使用现有 cache / timeout；先做单机基准测试，再决定是否需要线程级缓存。
- [切换后 Agent prompt 与脚本契约不一致] → 用新的 smoke test 覆盖“表单 → 规则执行 → payload → 导出”整条链路，并删除旋转机组对旧 `query_diagnosis.py + diagnosis_features.py` 契约的硬编码依赖。

## Migration Plan

1. 先抽取并落地受管规则运行时，补齐 `diagnosis.*` namespace 兼容层，并删除 `rule_optimizer` 依赖。
2. 改造 `ins` client / tool 入口，使其支持 Deer Flow Bearer token 透传并禁用内部重复登录。
3. 拆分 `device_analysis.py`：保留原始子设备树获取，把设备树语义推理并回 Deer Flow Agent 能力。
4. 在 `skills/custom/rotating-fault-diagnosis/scripts/` 实现 `run_rotating_rule_diagnosis.py` 与结果 JSON 契约，在离线样例上验证输出完整性。
5. 在适配层落盘原始趋势、波形频谱、轨迹缓存文件，定义统一命名和作用域目录。
6. 实现规则结果到 Deer Flow 报告 payload 的映射，并复用现有 `export_diagnosis_report.py` 做导出。
7. 更新 `fault-diagnosis--rotating/SOUL.md`，改为“GenUI 收参 → Agent 内设备树推理 → CLI 适配脚本 → 文件契约 → 报告渲染”的交互方式。
8. 用真实案例或录制夹具做对比验证，确认主诊断、候选诊断、置信度、建议和图表数据与 `mac-diag-code` 单独运行时一致。
9. 如线上发现问题，回滚方式为：恢复旋转机组 SOUL 到旧 MVP 脚本链路，同时保留新运行时代码但不启用。

## Open Questions

- `run_diagnosis(...)` 当前返回的 `DiagnosisResult` 是否已经包含足够的作图原始数据；如果没有，应该扩展返回值还是在适配层旁路缓存？
- 真实历史故障案例接口是否已经可用；如果没有，本次报告中的“同类故障历史”区块是否先隐藏或继续保留演示占位？
- 原始趋势、波形频谱、轨迹缓存的文件组织方式最终放在线程输出目录还是运行时专用缓存目录，哪种更利于报告复用与清理？
- Deer Flow 当前线程/运行上下文里，哪一层最适合把 Bearer token 注入到 CLI 适配脚本和 `ins` client，是环境变量还是显式命令参数？
- 设备树推理最终放在 `fault-diagnosis--rotating` 自身 prompt 中，还是提炼成共享 skill / helper，以便未来给机泵和往复机复用？
