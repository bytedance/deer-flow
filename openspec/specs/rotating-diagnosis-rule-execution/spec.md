## ADDED Requirements

### Requirement: 旋转机组诊断必须执行真实规则引擎
系统 SHALL 通过受管适配层执行 `mac-diag-code` 的旋转机组真实规则引擎，并以 `run_diagnosis(device_id, sub_device_id, time)` 的结果作为 `fault-diagnosis--rotating` 的主诊断依据。

#### Scenario: 有效输入触发真实规则诊断
- **WHEN** 用户在 `fault-diagnosis--rotating` 中提交合法的 `device_id`、`sub_device_id` 和诊断时间
- **THEN** 系统调用真实规则引擎适配层执行诊断，并返回主故障、备选故障、置信度、分数、证据摘要和建议，而不是走关键词匹配型 MVP 诊断路径

#### Scenario: 真实规则无候选故障时保留引擎回退语义
- **WHEN** 真实规则引擎在本次输入下未得到任何候选故障
- **THEN** 系统必须保留引擎定义的回退结果和置信度语义，并在结果中明确该回退来自真实规则引擎本身

### Requirement: 旋转机组诊断必须遵循规则引擎的数据采集顺序
系统 SHALL 按真实规则引擎的执行顺序完成设备上下文解析、趋势采集、波形异常时刻选择、频谱特征提取和轨迹特征提取。

#### Scenario: 诊断按趋势先于波形轨迹执行
- **WHEN** 系统执行一次旋转机组诊断
- **THEN** 系统必须先完成设备上下文和趋势窗口采集，再根据趋势异常选择波形时刻，最后采集频谱与轨迹特征

#### Scenario: 只对规则选中的异常时刻做深采样
- **WHEN** 某个波形探头存在多个可候选时间点
- **THEN** 系统必须使用真实规则引擎选择出的代表性异常时刻进行波形与轨迹深采样，而不是由报告层或 SOUL 重新选点

### Requirement: 旋转机组规则运行时必须是受管依赖
系统 SHALL 从仓库内受管运行时或显式配置的受控镜像位置加载旋转机组规则引擎，不得把用户本机绝对路径作为默认生产依赖。

#### Scenario: 受管运行时可用时正常加载
- **WHEN** 旋转机组规则运行时包及其依赖闭包完整可用
- **THEN** 适配层从受管位置加载规则引擎并完成诊断

#### Scenario: 运行时依赖缺失时返回可操作错误
- **WHEN** 旋转机组规则运行时缺失 `diagnosis.*`、缓存层或其他关键依赖
- **THEN** 系统返回结构化错误，指出缺失依赖和修复方向，且不得静默回退到旧关键词匹配诊断链路

### Requirement: 旋转机组规则执行不得依赖 `rule_optimizer`
系统 SHALL 删除对 `diagnosis_rule.rule_optimizer` 的运行时依赖，并直接调用底层设备分析、趋势、频谱和轨迹提取实现。

#### Scenario: 删除缓存包装层后仍可完成诊断
- **WHEN** 旋转机组规则运行时不提供 `diagnosis_rule.rule_optimizer`
- **THEN** 系统仍可直接调用底层实现完成上下文构建、趋势采集、特征提取和故障打分

#### Scenario: 直连底层实现时保留原始数据
- **WHEN** 系统直接调用底层趋势、波形频谱和轨迹提取实现
- **THEN** 系统必须同时保留本次诊断使用的原始数据缓存，供后续报告绘图复用

### Requirement: 旋转机组规则执行必须暴露稳定的系统交互接口
系统 SHALL 为旋转机组真实规则执行同时提供可导入 Python 接口和稳定 CLI 包装器，并以 JSON 文件作为与报告链路的交接格式。

#### Scenario: Agent 通过 CLI 调用规则执行
- **WHEN** `fault-diagnosis--rotating` 完成表单收参并开始执行诊断
- **THEN** 系统通过稳定 CLI 包装器传入 `device_id`、`sub_device_id` 和诊断时间，并生成标准化 JSON 结果文件供后续步骤读取

#### Scenario: 测试或适配层直接导入规则接口
- **WHEN** 单元测试或内部适配层需要在 Python 进程内执行同一套规则逻辑
- **THEN** 系统可以直接导入受管规则运行时包而不依赖 shell 拼接

### Requirement: 旋转机组数据获取必须透传 Deer Flow 当前用户 token
系统 SHALL 在旋转机组诊断取数时直接透传 Deer Flow 当前用户的 Bearer token 到 InS 数据接口，不得在程序内再次登录换取 token。

#### Scenario: 有 Deer Flow token 时直接取数
- **WHEN** 旋转机组诊断运行时拿到了当前用户的 Deer Flow Bearer token
- **THEN** 系统使用该 token 调用设备分析、趋势、频谱和轨迹相关数据接口，而不依赖 `INS_USERNAME` / `INS_PASSWORD`

#### Scenario: 运行时不得重复登录
- **WHEN** 旋转机组诊断运行时已经持有可用的 Deer Flow Bearer token
- **THEN** 系统不得再调用登录接口申请新的 InS token

### Requirement: 设备树语义推理必须并入 Deer Flow Agent 能力
系统 SHALL 将设备树的语义推理、结构补全和测点归位能力并入 Deer Flow 诊断 Agent，本地脚本只保留原始子设备树获取与数据变换职责。

#### Scenario: Agent 使用同一模型上下文完成设备树推理
- **WHEN** 旋转机组诊断需要根据原始子设备树推断设备类型、轴承方向、测点归属或结构补位
- **THEN** 系统由 Deer Flow 当前诊断 Agent 在同一会话模型上下文内完成该推理，而不是在 `device_analysis.py` 中再启动一个独立 Agent

#### Scenario: 底层脚本不再自建独立模型运行时
- **WHEN** 旋转机组诊断运行时调用设备树分析相关底层能力
- **THEN** 底层脚本不得自行构造独立的 `Agent`、`Runner` 或模型客户端来完成语义推理
