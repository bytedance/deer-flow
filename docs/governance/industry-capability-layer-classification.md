# 行业能力三层分类结论

> **评审日期**：2026-05-23
> **评审范围**：DeerFlow 全量后端模块、API 路由、前端页面、Skill 集合
> **分类标准**：以"复用范围"为第一原则
>
> | 层级 | 定义 | 复用范围 |
> |------|------|----------|
> | **Core Platform** | 所有租户共用的基础能力 | 全局复用，与行业无关 |
> | **Enterprise Control Plane** | 租户级管控和定制 | 租户隔离，可配置但非行业专属 |
> | **Industry Solution Layer** | 行业特定的业务逻辑和数据模型 | 单一/少数行业，依赖外部行业系统 |

---

## 一、Core Platform（通用平台层）

以下能力面向所有租户提供，不包含行业专属逻辑，应纳入 Core Platform。

### 1.1 基础设施

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 配置框架 | `deerflow.config.*` | 所有模块的基础依赖，与行业无关 |
| 持久化层 | `deerflow.persistence` | 通用 ORM 和 DB 操作 |
| 运行时 | `deerflow.runtime` | user_context, serialization, journal 均为通用能力 |
| 缓存 | `deerflow.cache` | 通用缓存抽象 |
| 追踪 | `deerflow.tracing` | 通用 OpenTelemetry 追踪 |
| 事件系统 | `deerflow.events` | 通用事件总线 |
| 沙箱 | `deerflow.sandbox` | 通用代码执行沙箱 |
| 文件上传 | `deerflow.uploads` | 通用文件上传/存储 |
| 共享工具 | `deerflow.shared`, `deerflow.utils` | 通用工具函数 |
| HTTP Connector | `deerflow.config.http_connector_config` | 通用 HTTP 客户端配置 |

### 1.2 Agent & AI 引擎

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| Agent 框架 | `deerflow.agents` | 通用 Agent 编排（lead agent, memory, prompts, sub-agents） |
| Agent 工厂 | `deerflow.agents.factory` | 通用 Agent 创建工厂 |
| 工具系统 | `deerflow.tools` | 通用 Tool 注册和调度 |
| 模型管理 | `deerflow.models` | 通用 LLM 模型接入 |
| ACP 协议 | `deerflow.config.acp_config` | 通用 Agent 通信协议 |
| GenUI | `deerflow.config.*`, `frontend: genui/` | 通用生成式 UI |
| 流式桥接 | `deerflow.config.stream_bridge_config` | 通用流式传输配置 |

### 1.3 知识 & 检索

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| RAG 框架 | `deerflow.rag`, `deerflow.config.rag_config` | 通用 RAG 管道（embedding + vector store） |
| 知识库管理 | `deerflow.knowledge_base` | 通用知识库 CRUD、索引、检索 |
| 知识库访问控制 | `deerflow.knowledge_base.access_control` | 通用权限模型 |
| 知识库索引 | `deerflow.knowledge_base.indexing` | 通用文档索引管道 |

### 1.4 质量 & 安全

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| Guardrails | `deerflow.guardrails` | 通用安全护栏 |
| 内容安全 | `deerflow.content_safety` | 通用内容审核 |
| 评估框架 | `deerflow.evaluation` | 通用评估框架 |
| 反馈系统 | `deerflow.feedback` | 通用用户反馈 |
| 反思 | `deerflow.reflection` | 通用 Agent 反思 |
| 成本追踪 | `deerflow.cost` | 通用 Token 成本核算 |
| Token 用量 | `deerflow.config.token_usage_config` | 通用用量追踪 |

### 1.5 报告引擎（通用部分）

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 报告模板 DSL 引擎 | `deerflow.report_templates.schema` | 通用 DSL schema 定义 |
| 模板版本管理 | `deerflow.report_templates.repository` | 通用模板版本/发布/归档 |
| 通用渲染器 | `deerflow.report_templates.generic_renderer` | 通用 Markdown/HTML 渲染 |
| DSL 校验器 | `deerflow.report_templates.validator` | 通用 DSL 语法校验 |
| 脚本注册表 | `deerflow.report_templates.script_registry` | 通用查询脚本注册 |
| Push Block | `deerflow.report_templates.push_block` | 通用推送块抽象 |
| 模板权限 | `deerflow.report_templates.permissions` | 通用 RBAC 权限矩阵 |

### 1.6 闭环管理（通用部分）

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 状态机 | `deerflow.closed_loop.state_machine` | 通用工单状态流转引擎 |
| 工单数据层 | `deerflow.closed_loop.repository` | 通用工单 CRUD |
| 审计事件 | `deerflow.closed_loop.events` | 通用不可变审计日志 |
| 定时任务 | `deerflow.closed_loop.jobs` | 通用 SLA 超期检测 |

### 1.7 前端通用页面

| 能力 | 当前路由 | 归属理由 |
|------|----------|----------|
| Chat 工作台 | `workspace/chats/` | 通用会话界面 |
| Agent 管理 | `workspace/agents/` | 通用 Agent 配置界面 |
| 知识库管理 | `workspace/knowledge-bases/` | 通用知识库 UI |
| 能力管理 | `workspace/capabilities/` | 通用能力清单 UI |
| Debug | `workspace/debug/` | 通用调试工具 |

---

## 二、Enterprise Control Plane（企业管控面）

以下能力面向租户管理员，提供隔离、定制和管控功能，应纳入 Enterprise Control Plane。

### 2.1 多租户管控

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 租户解析 | `deerflow.config.tenant` | 租户上下文提取，租户级配置注入点 |
| 租户存储 | `deerflow.config.tenant_storage` | 租户隔离的存储路径管理 |
| 租户状态 | `api: /api/tenant-status` | 租户级健康检查和状态 |
| 能力作用域 | `deerflow.config.capability_scope` | GLOBAL→TENANT 继承/覆盖/停用传播 |
| 租户 Guard | `frontend: tenant-guard-wrapper` | 前端租户隔离守卫 |

### 2.2 Agent / Skill 租户管控

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 租户级 Agent | `api: /api/tenants/{id}/agents` | 租户管理员创建/管理租户可见 Agent |
| 租户级 MCP | `api: /api/tenants/{id}/mcp-servers` | 租户管理员配置租户 MCP 服务器 |
| 租户级 Connector | `api: /api/tenants/{id}/connectors` | 租户级 HTTP 连接器配置 |
| Skill 启用/禁用 | `extensions_config.skills` | 租户级 Skill 开关，通过 ExtensionsConfig 管理 |
| Agent 权限 | `persistence.agent.auth` | 租户内 Agent 可见性（private/tenant_public） |
| Agent Soul 覆盖 | `load_tenant_agent_soul()` | 租户级 Agent 提示词定制 |

### 2.3 认证 & 权限管控

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 通用认证 | `api: /api/auth` | JWT + API Key 认证框架 |
| 权限中间件 | `app.gateway.authz` | `@require_permission` 装饰器 |
| CSRF 中间件 | `app.gateway.csrf_middleware` | 安全中间件 |
| Auth 配置 | `deerflow.config.auth_config` | 租户可选 local/ins_base provider |

### 2.4 报告管控（租户级）

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 模板可见性 | Scope.tenant / Scope.private | 租户级模板隔离 |
| 报告运行历史 | `api: /api/report-runs` | 租户隔离的运行记录 |
| 导出触发器 | `frontend: export-trigger` | 租户级报告导出 |

### 2.5 闭环管控（租户级）

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| SLA 配置 | `closure_sla_configs` 表 | 租户级 SLA 时限覆盖 |
| 工单权限 | `deerflow.closed_loop.permissions` | 租户内 closure:read/write/verify 三元组 |
| 通知汇总 | `api: /api/closure/notifications/summary` | 租户内待办/超期/待验证计数 |

### 2.6 前端管控页面

| 能力 | 当前路由 | 归属理由 |
|------|----------|----------|
| 闭环管理 | `workspace/closed-loop/` | 租户内工单管理界面 |
| 设置页面 | `frontend: settings/` | 租户管理员配置界面 |
| 管理后台 | `api: /api/admin` | 租户管理员操作 API |

---

## 三、Industry Solution Layer（行业方案层）

以下能力直接依赖外部行业系统（ins-base-rpc / ins-bus-rpc），或包含特定行业的诊断逻辑和数据处理，应纳入 Industry Solution Layer。

### 3.1 InS 认证集成

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| InS Base 认证 | `api: /api/v1/auth/ins-base` | 直接依赖外部 Java 微服务 ins-base-rpc |
| InS Auth Provider | `app.gateway.auth.ins_base_provider` | ins-base JWT 验证和用户转换 |
| RSA 加密登录 | `auth_config.rsa_public_key` | InS 体系特有的密码加密方式 |

### 3.2 组织 & 设备集成

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| 组织树 | `api: /api/organize` | 代理到 ins-bus-rpc，行业组织层级结构 |
| 设备/机器 API | `api: /api/machine` | 代理到 ins-bus-rpc，行业设备拓扑 |
| 部件信息查询 | `api: /api/machine/component-info` | 行业特有的部件层级数据 |

### 3.3 行业诊断 Skill

以下 Skill 包含行业特定的诊断逻辑、信号处理算法和故障模型：

| 能力 | Skill 名称 | 归属理由 |
|------|-----------|----------|
| 旋转设备故障诊断 | `rotating-fault-diagnosis` | 旋转机械特有的故障模式（不平衡、不对中、松动等） |
| 振动故障诊断 | `vibration-fault-diagnosis` | 振动频谱分析，行业标准 ISO 10816 |
| 泵故障诊断 | `pump-fault-diagnosis` | 泵特有的气蚀、回流等故障模式 |
| 往复设备故障诊断 | `reciprocating-fault-diagnosis` | 往复压缩机/泵特有的故障 |
| 静态设备腐蚀诊断 | `static-equipment-corrosion-diagnosis` | 塔器/容器/管道腐蚀评估 |
| 旋转设备上下文 | `rotating-device-context` | 旋转设备领域知识 |

### 3.4 行业数据 Skill

以下 Skill 提供行业特有的数据采集和特征提取：

| 能力 | Skill 名称 | 归属理由 |
|------|-----------|----------|
| 趋势数据获取 | `ins-get-trend-data*` (4 个变体) | 从 InS 系统获取时序趋势数据 |
| 波形数据获取 | `ins-get-waveform-data` | 从 InS 系统获取高频波形数据 |
| 轴心轨迹数据 | `ins-get-orbit-data` | 旋转设备特有的轴心轨迹数据 |
| 趋势特征提取 | `ins-extract-trend-features*` (4 个变体) | 行业特有的趋势特征工程 |
| 频谱波形特征 | `ins-extract-spectral-waveform-features` | 行业特有的频谱分析特征 |
| 轴心轨迹特征 | `ins-extract-orbit-centerline-features` | 行业特有的轴心轨迹特征提取 |
| 设备分析 | `ins-device-analysis*` (4 个变体) | 行业设备综合分析 |

### 3.5 行业数据分析

| 能力 | Skill 名称 | 归属理由 |
|------|-----------|----------|
| 数据分析师 | `data-analyst` | 行业报表和诊断数据的通用分析 |

### 3.6 RPC 基础设施

| 能力 | 当前模块 | 归属理由 |
|------|----------|----------|
| InS Base RPC 客户端 | `deerflow.rpc.ins_base_auth_service` | 与 ins-base-rpc Java 服务通信 |
| InS Org RPC 客户端 | `deerflow.rpc.ins_base_org_service` | 与 ins-bus-rpc 组织服务通信 |
| 设备 RPC 客户端 | `deerflow.rpc.machine_service` | 与 ins-bus-rpc 设备服务通信 |
| Nacos 注册中心 | `deerflow.rpc.nacos_registry` | 行业微服务的服务发现 |
| RPC 框架 | `deerflow.rpc.rpc_client` | 通用 RPC 客户端（HTTP + 重试） |
| RPC 配置 | `deerflow.config.rpc_config`, `nacos_config` | RPC 超时、重试、Nacos 地址配置 |

### 3.7 前端行业页面

| 能力 | 当前路由 | 归属理由 |
|------|----------|----------|
| 报告模板管理 | `workspace/report-templates/` | 行业报告模板的创建和管理（DSL 编辑、发布） |
| 报告运行历史 | `workspace/report-runs/` | 行业报告运行记录查看 |

---

## 四、关键边界判断说明

### 4.1 报告模板系统：一分为二

报告模板系统跨两个层级：

- **Core Platform**：DSL 引擎（schema.py, validator.py, repository.py 的版本管理, generic_renderer.py, script_registry.py）
- **Industry Solution Layer**：行业报告模板的 DSL 内容（定义在 skills/custom/ 下的具体模板）、行业查询脚本（scripts/ 下的 Python 脚本）、前端模板编辑界面

**判断依据**：DSL 引擎是通用的声明式报告框架，可被任何行业复用；具体的 DSL 模板内容（如"日报-设备检查"模板）包含行业知识。

### 4.2 闭环工单系统：一分为二

- **Core Platform**：状态机引擎、工单仓储层、审计事件
- **Enterprise Control Plane**：SLA 时限配置（租户级覆盖）、工单权限模型

**判断依据**：状态机和数据层是通用工作流基础设施；SLA 和权限与具体租户的运维策略相关。

### 4.3 RPC 框架 vs RPC 服务

- **Core Platform**：`rpc_client.py` 通用 RPC 客户端（HTTP 重试、超时）
- **Industry Solution Layer**：`ins_base_auth_service.py`, `machine_service.py` 等具体服务适配器
- **Enterprise Control Plane**：`rpc_config.py` RPC 配置（超时/端点可由租户覆盖）

**判断依据**：通用 RPC 机制属于 Core；具体行业系统适配属于 Industry；租户级配置覆盖属于 Enterprise。

---

## 五、统计汇总

| 层级 | 能力数量 |
|------|---------|
| Core Platform | 44 |
| Enterprise Control Plane | 18 |
| Industry Solution Layer | 30 |
| **合计** | **92** |
