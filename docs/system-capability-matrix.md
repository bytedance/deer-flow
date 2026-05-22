# DeerFlow 能力矩阵与 Owner 建议

最后更新：2026-05-21

## 1. 说明

本文档是 [system-capability-map.md](./system-capability-map.md) 的配套材料，目标是把“能力地图”进一步落成可管理的矩阵。

本文档回答四类问题：

- 哪些模块已经是核心能力，哪些仍在孵化
- 每个模块面向谁，主要入口在哪里
- 每个模块建议由什么角色负责业务和技术 owner
- 每个模块下一阶段最值得盯住的指标和里程碑是什么

重要说明：

- 下文的 owner 是“建议角色”，不是实际人名
- 未知的组织分工不会被伪造
- 成熟度与状态用于管理讨论，不等同于代码完成度

## 2. 成熟度与状态口径

### 2.1 成熟度

- `L4`：主链路闭环，用户入口稳定，生命周期清晰
- `L3.5`：能力较完整，已可规模使用，但治理或体验仍需补强
- `L3`：已有明确产品域，但尚未成为第一主流程
- `L2.5`：能力可用，但产品边界和组织配套未稳定

### 2.2 状态

- `Core`：当前平台核心，必须优先保证稳定性与一致性
- `Scale-Up`：已可用，下一阶段重点是规模化和治理完善
- `Stabilize`：能力存在，但需要收敛边界、补生命周期或统一体验
- `Incubate`：方向成立，但仍处于方案孵化或产品边界探索期

## 3. 能力矩阵

| 模块 | 能力域 | 目标用户 | 主要入口 | 建议业务 Owner | 建议技术 Owner | 成熟度 | 当前状态 | 关键依赖 | 近期管理重点 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 对话线程与运行 | Agent Workspace | 普通用户、分析用户 | Workspace Chat | 工作台产品负责人 | Agent Runtime 负责人 | L4 | Core | LangGraph、模型、流式事件 | 保持主链稳定，统一 thread/run 生命周期 |
| 文件上传与产物 | Agent Workspace | 普通用户、分析用户 | Chat Upload、Artifacts | 工作台产品负责人 | Gateway 文件链路负责人 | L4 | Core | 上传限制、artifact 路由、sandbox 路径映射 | 控制复杂度，保证上传到消费链路稳定 |
| 动态 UI 交互 | Agent Workspace | 高阶分析用户 | Chat UI Blocks | 工作台产品负责人 | 前端交互框架负责人 | L3.5 | Scale-Up | SSE、GenUI、中间件 | 降低状态复杂度，强化恢复与可观测性 |
| 模型管理 | Agent Capability Platform | 平台配置者 | Models API / 配置面 | 平台产品负责人 | 模型接入负责人 | L3.5 | Scale-Up | config、provider factory | 统一模型治理口径，减少配置分叉 |
| Skills 管理 | Agent Capability Platform | 平台配置者、构建者 | Skills 页面 / API | 平台产品负责人 | Skills 平台负责人 | L3.5 | Scale-Up | skills loader、版本回滚 | 建立发布和审计规则，避免能力漂移 |
| MCP 与 Connector | Agent Capability Platform | 平台配置者、租户管理员 | MCP / Connector 页面与 API | 平台产品负责人 | 集成平台负责人 | L3.5 | Scale-Up | extensions_config、tenant 配置 | 统一“外部能力接入”的产品模型 |
| 自定义 Agent / Tenant Agent | Agent Capability Platform | 构建者、租户管理员 | Agents 页面 / API | 平台产品负责人 | Agent 平台负责人 | L3.5 | Scale-Up | prompt/config、权限、租户 | 明确 agent 生命周期和发布面 |
| 知识库与索引 | Knowledge & Retrieval | 知识管理员、分析用户 | Knowledge Bases 页面 | 知识产品负责人 | RAG / Indexing 负责人 | L3.5 | Scale-Up | 上传、embedding、vector store、权限 | 继续打磨索引恢复、重建和权限一致性 |
| 检索与跨 KB 召回 | Knowledge & Retrieval | 分析用户、报告用户 | KB Search / RAG API | 知识产品负责人 | Retrieval 负责人 | L3.5 | Scale-Up | KB、embedding 策略、检索排序 | 建立效果指标，不只看接口可用性 |
| 报告模板 | Report & Outcome | 模板设计者、分析用户 | Report Templates 页面 | 报告产品负责人 | 模板引擎负责人 | L3 | Stabilize | DSL、权限、版本管理 | 强化模板治理和复用策略 |
| 报告运行与产物 | Report & Outcome | 报告使用者、管理层 | Report Runs 页面 | 报告产品负责人 | 报告运行链路负责人 | L3 | Stabilize | Agent、KB、模板、artifact | 建立“从执行到结果”的统一可追踪链路 |
| 闭环工单 | Closed Loop & Governance | 运维、管理者 | Closed Loop 页面 | 闭环产品负责人 | 工单/状态机负责人 | L2.5-L3 | Stabilize | 报告、诊断、权限 | 明确与报告、诊断的主流程关系 |
| 成本 / 预算 / 审计 | Closed Loop & Governance | 租户管理员、平台管理员 | Admin / Cost 页面 | 平台治理负责人 | 平台治理后端负责人 | L2.5-L3 | Stabilize | 认证、租户、运行数据 | 建立治理指标，不仅有接口也要有运营动作 |
| 认证与租户 | Enterprise Control Plane | 全部登录用户、管理员 | Login / Admin | 平台治理负责人 | 认证与租户负责人 | L3 | Core | JWT、ins-base、tenant store、权限 | 保证语义一致，避免认证失败被业务误判 |
| 管理后台 | Enterprise Control Plane | 平台管理员、租户管理员 | Admin 页面 | 平台治理负责人 | 前后端管理台负责人 | L2.5-L3 | Stabilize | 统计、日志、租户、权限 | 从“能看”走向“可操作、可追责” |
| 渠道集成 | Enterprise / Industry Integration | 企业客户、运营人员 | Channels API | 企业集成产品负责人 | 渠道集成负责人 | L2.5 | Incubate | IM 平台、认证、消息链路 | 定义清楚适用场景和 SLA 口径 |
| InS 认证与组织 | Enterprise / Industry Integration | 企业客户、行业方案团队 | ins-base / organize / machine | 行业解决方案负责人 | 行业集成负责人 | L2.5 | Incubate | 外部服务、网关认证、组织模型 | 先明确边界，再继续扩功能 |
| 设备诊断与行业报表链路 | Enterprise / Industry Integration | 行业分析用户 | Workspace + 行业专用链路 | 行业解决方案负责人 | 行业应用负责人 | L2.5 | Incubate | InS、报告、KB、闭环 | 从“能力拼装”走向“方案打包” |

## 4. 建议的 Owner 结构

如果后续要按能力域管理，而不是按目录管理，建议至少形成如下角色分层：

- 工作台产品负责人：负责聊天、上传、产物、GenUI 等主入口一致性
- 平台产品负责人：负责模型、Skills、MCP、Connector、Agent 配置层
- 知识产品负责人：负责知识库、检索、索引体验与效果指标
- 报告产品负责人：负责模板、运行、结果消费链路
- 平台治理负责人：负责认证、租户、预算、审计、管理后台
- 行业解决方案负责人：负责 InS、组织、设备、行业模板与行业流程

对应的技术 owner 建议也按能力域划分，而不是由单一网关负责人承接全部模块。

## 5. 建议的管理指标

### 5.1 Agent Workspace

- 会话创建成功率
- 流式运行成功率
- 上传成功率
- artifact 访问成功率
- 对话主链平均完成时长

### 5.2 Agent Capability Platform

- Skills / MCP / Connector 配置成功率
- 自定义 Agent 发布成功率
- 租户级能力启用成功率
- 配置变更后的回归问题数

### 5.3 Knowledge & Retrieval

- 索引成功率
- 重建索引完成率
- 检索平均时延
- 检索命中质量指标

### 5.4 Report & Outcome

- 模板发布成功率
- 报告运行成功率
- 报告被消费/查看比例
- 从运行到产物可追踪率

### 5.5 Governance

- 登录成功率
- 租户管理操作成功率
- 预算告警命中率
- 闭环单超期率
- 审计日志覆盖率

### 5.6 Industry Integration

- 外部集成调用成功率
- 行业链路端到端成功率
- 外部依赖故障误判率

## 6. 下一个管理动作

如果要把这份矩阵投入实际项目管理，建议继续补三件事：

1. 将“建议 owner”替换为真实团队或真实岗位
2. 为每个模块补 `目标指标 / 当前值 / 目标值`
3. 为每个模块补 `Q3 是否继续投资` 的明确结论

在这三步完成之前，这份矩阵适合用作评审和排期输入，不适合作为正式 KPI 台账。
