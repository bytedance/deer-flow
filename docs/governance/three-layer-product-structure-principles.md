# DeerFlow 三层产品结构原则

> **版本**：v1.0
> **日期**：2026-05-23
> **依赖**：[行业能力三层分类结论](./industry-capability-layer-classification.md)
> **配套**：[边界争议待决清单](./boundary-dispute-register.md)
>
> 本文档将 Core Platform、Enterprise Control Plane、Industry Solution Layer 三层转化为正式的产品原则，包含职责边界、目标用户、变更原则和需求路由标准。

---

## 一、Core Platform（通用平台层）

### 1.1 定位

Core Platform 是 DeerFlow 的基石，为所有租户提供与行业无关的基础 AI 能力。它是"一个平台，多个行业"的技术底座。

### 1.2 目标用户

| 用户类型 | 使用方式 |
|----------|----------|
| 平台开发者 | 在 Core 上构建和扩展能力 |
| 行业方案开发者 | 基于 Core 提供的 SDK/API 构建行业方案 |
| 租户管理员 | 通过 Enterprise Control Plane 使用 Core 提供的能力 |
| 最终用户 | 通过 Chat 工作台、Agent 等 Core 提供的界面交互 |

### 1.3 核心职责

1. **Agent 编排引擎**：Agent 生命周期管理、多 Agent 协作、工具调用、记忆管理
2. **AI 基础设施**：LLM 模型接入、RAG 管道、知识库管理、内容安全
3. **报告 DSL 引擎**：声明式报告模板定义、版本管理、渲染、脚本执行
4. **闭环工单引擎**：通用状态机、工单仓储、审计事件追踪
5. **Skill 框架**：Skill 加载、安全扫描、存储管理
6. **MCP 集成**：MCP 服务器注册、连接管理、协议适配
7. **安全 & 合规**：Guardrails、内容审核、反馈收集、评估框架
8. **可观测性**：追踪、成本核算、Token 用量统计
9. **基础设施**：配置管理、持久化、缓存、文件上传、沙箱、事件系统

### 1.4 包含的能力范围

参见 [行业能力三层分类结论 §一](./industry-capability-layer-classification.md#一core-platform通用平台层)，共 44 项能力。

### 1.5 与其他层的边界

- **与 Enterprise Control Plane**：Core 提供能力和 API，Enterprise 提供租户级配置和管控。Core 不关心租户如何启用/禁用能力，Enterprise 不关心能力如何实现。
- **与 Industry Solution Layer**：Core 提供通用框架（DSL 引擎、Skill 框架、Agent 框架），Industry 提供具体实现（行业模板、行业 Skill、行业 Agent）。

---

## 二、Enterprise Control Plane（企业管控面）

### 2.1 定位

Enterprise Control Plane 是租户管理员管控 DeerFlow 能力的操作面。它不创造新的 AI 能力，而是决定 Core Platform 和 Industry Solution Layer 的能力在当前租户内如何被使用、由谁使用、以什么策略使用。

### 2.2 目标用户

| 用户类型 | 使用方式 |
|----------|----------|
| 租户管理员 | 配置 Agent/Skill/MCP 的可见性和权限 |
| 运维负责人 | 配置 SLA 时限、告警策略 |
| 部门管理者 | 管理组织结构和用户权限 |
| 合规审计员 | 查看操作审计日志 |

### 2.3 核心职责

1. **多租户隔离**：租户上下文解析、存储路径隔离、能力作用域管理（GLOBAL→TENANT 继承/覆盖/停用）
2. **Agent/Skill 管控**：租户级 Agent 创建、Skill 启用/禁用、MCP 服务器配置
3. **认证集成**：JWT/API Key 认证、InS Base 认证提供者切换、权限中间件
4. **报告管控**：模板可见性管理（private/tenant/public）、运行历史查询
5. **闭环管控**：SLA 时限配置、工单权限管理
6. **连接器管理**：租户级 HTTP 连接器、外部 API 集成配置

### 2.4 包含的能力范围

参见 [行业能力三层分类结论 §二](./industry-capability-layer-classification.md#二enterprise-control-plane企业管控面)，共 18 项能力。

### 2.5 与其他层的边界

- **与 Core Platform**：Enterprise 依赖 Core 提供的能力，但通过配置层面对其进行管控。Enterprise 不修改 Core 代码。
- **与 Industry Solution Layer**：Enterprise 可管控 Industry 能力的启用状态（如禁用某个行业 Skill），但不修改 Industry 的逻辑。

---

## 三、Industry Solution Layer（行业方案层）

### 3.1 定位

Industry Solution Layer 是面向特定行业（电力、石化、钢铁等）的业务逻辑和数据集成层。它依赖 Core Platform 的通用框架，通过 Enterprise Control Plane 被租户采纳。

### 3.2 目标用户

| 用户类型 | 使用方式 |
|----------|----------|
| 行业解决方案开发者 | 开发行业 Skill、行业报告模板、行业 Agent |
| 领域专家 | 定义故障模型、诊断规则、报告模板的 DSL 内容 |
| 行业客户（最终用户） | 使用诊断 Agent、查看行业报告 |
| 系统集成商 | 将 DeerFlow 与行业外部系统（InS/DCS/MES）对接 |

### 3.3 核心职责

1. **行业系统集成**：与 InS Base（认证）、InS Bus（组织/设备）、DCS/MES 等外部系统的 RPC/API 适配
2. **行业诊断能力**：旋转/往复/振动/腐蚀等专业故障诊断 Skill
3. **行业数据采集**：趋势数据、波形数据、轴心轨迹数据的获取和特征提取
4. **行业报告内容**：日报/周报/月报的 DSL 模板定义和查询脚本
5. **行业知识内容**：设备手册、故障案例库、行业标准的预置知识

### 3.4 包含的能力范围

参见 [行业能力三层分类结论 §三](./industry-capability-layer-classification.md#三industry-solution-layer行业方案层)，共 30 项能力。

### 3.5 与其他层的边界

- **与 Core Platform**：Industry 使用 Core 的 DSL 引擎定义报告模板，使用 Core 的 Skill 框架注册行业 Skill。Industry 不修改 Core 框架代码。
- **与 Enterprise Control Plane**：Industry 能力可被 Enterprise 的 Skill 启用/禁用开关管控。Industry 不感知租户配置。

---

## 四、变更原则

### 4.1 Core Platform 变更原则

| 原则 | 说明 |
|------|------|
| **向后兼容** | API、DSL Schema、Skill 接口的变更必须保持向后兼容。废弃接口需先标记 `@deprecated`，至少一个版本后才能移除 |
| **渐进式发布** | 涉及全租户的变更采用灰度发布（canary → 10% → 50% → 100%） |
| **全租户影响评估** | 每次变更必须评估对所有租户的影响，输出影响分析报告 |
| **API 版本化** | 不兼容变更通过新版本 API 暴露（`/api/v2/...`），旧版本保持 6 个月 |
| **测试覆盖** | Core 变更需 ≥80% 测试覆盖，包含回归测试 |
| **架构评审** | 涉及模块边界变更需架构负责人审批 |

**发布影响范围**：所有租户。任何 Core 变更的 bug 可能影响全部客户。

**审批流程**：PR → Code Review → 架构评审（重大变更）→ CI 全量测试 → 灰度发布 → 全量

### 4.2 Enterprise Control Plane 变更原则

| 原则 | 说明 |
|------|------|
| **配置隔离** | 新增管控功能默认关闭，由租户管理员主动启用 |
| **租户不可见性** | 一个租户的配置变更不影响其他租户 |
| **可审计** | 所有管控操作记录审计日志（谁、何时、做了什么） |
| **SLA 感知** | 管控功能故障不应影响 Core Platform 的核心链路 |
| **增量配置** | 新配置项提供合理默认值，不强制租户迁移 |

**发布影响范围**：单个企业内的所有用户。新功能的管控配置默认不影响现有行为。

**审批流程**：PR → Code Review → CI 测试 → 直接发布（影响范围限于新功能配置）

### 4.3 Industry Solution Layer 变更原则

| 原则 | 说明 |
|------|------|
| **行业隔离** | 一个行业的 Skill/模板变更不影响其他行业 |
| **更快迭代** | 行业层允许更快的发布节奏（hotfix 可跳过灰度直接发布） |
| **行业范围评估** | 变更影响评估聚焦受影响的行业和租户 |
| **Skill 版本化** | 行业 Skill 使用语义版本（MAJOR.MINOR.PATCH），租户可选择版本 |
| **数据契约** | 与外部系统的接口（RPC 协议、数据格式）变更需上下游协调 |

**发布影响范围**：特定行业的租户。行业层 bug 只影响使用该行业能力的客户。

**审批流程**：PR → Code Review → 行业负责人审批 → CI 测试 → 发布

---

## 五、需求路由决策标准

### 5.1 决策树

新增需求按以下决策树判断归属层级：

```
新需求
  │
  ├─ 是否与特定行业的外部系统集成？
  │   └─ YES → 是否所有行业都需要？
  │       ├─ YES → Core Platform（通用集成框架）
  │       └─ NO  → Industry Solution Layer（行业特定适配器）
  │
  ├─ 是否所有租户都需要此能力？
  │   ├─ YES → 是否作为 API/SDK 暴露？
  │   │   ├─ YES → Core Platform
  │   │   └─ NO  → 是否能被配置开关控制？
  │   │       ├─ YES → Enterprise Control Plane（管控开关）
  │   │       └─ NO  → 重新审视（设计可能需要调整）
  │   └─ NO →
  │       ├─ 租户管理员配置决定？ → Enterprise Control Plane
  │       ├─ 特定行业业务逻辑？ → Industry Solution Layer
  │       └─ 不确定 → 列入争议清单，架构评审裁决
  │
  └─ 是否是对现有能力的管控/配置？
      └─ YES → Enterprise Control Plane
```

### 5.2 快速 Checklist

使用以下 checklist 辅助判断。在适用的选项前打勾：

```
□ 能力在所有行业通用           → Core Platform (得分 +2)
□ 能力涉及特定行业领域知识      → Industry Solution Layer (得分 +2)
□ 能力是租户管理员配置项        → Enterprise Control Plane (得分 +2)
□ 能力需要对接外部行业系统      → Industry Solution Layer (得分 +1)
□ 能力被多个行业 Skill 复用    → Core Platform (得分 +1)
□ 能力涉及租户间的数据隔离      → Enterprise Control Plane (得分 +1)
□ 能力由平台团队维护            → Core Platform
□ 能力由行业团队维护            → Industry Solution Layer
□ 能力由租户管理员自助配置      → Enterprise Control Plane
```

### 5.3 典型示例

| 需求 | 判断过程 | 归属 |
|------|----------|------|
| "增加 LDAP 认证" | 所有企业可能需要 LDAP，但具体配置因企业而异 | Enterprise Control Plane |
| "增加汽轮机故障诊断" | 仅电力行业需要，需要对接 DCS 数据 | Industry Solution Layer |
| "优化 Agent 记忆检索性能" | 所有 Agent 用户受益，与行业无关 | Core Platform |
| "租户可自定义 SLA 时限" | 管控配置项，租户管理员操作 | Enterprise Control Plane |
| "增加油液分析报告模板" | 特定行业（石化）的报告内容 | Industry Solution Layer |
| "报告 DSL 支持图表类型配置" | DSL 引擎能力增强，所有行业可复用 | Core Platform |

### 5.4 边界模糊时的处理

当决策树无法明确判定时：

1. **优先归 Core**：与行业无关的通用能力默认归 Core，后续可通过 Enterprise 管控
2. **争议升级**：列入 [边界争议待决清单](./boundary-dispute-register.md)，架构评审会裁决
3. **临时归属**：标记 `provisional: true`，在下一个评审周期重新评估

---

## 六、对外表述

本文档可直接用于以下场景：

### 6.1 产品 Roadmap

```
DeerFlow 产品架构：
┌──────────────────────────────────────────────┐
│          Industry Solution Layer              │
│  电力诊断 · 石化报告 · 钢铁分析 · ...         │
├──────────────────────────────────────────────┤
│        Enterprise Control Plane               │
│  租户管控 · SLA 配置 · 权限管理 · 审计        │
├──────────────────────────────────────────────┤
│            Core Platform                      │
│  Agent 引擎 · RAG · Skill 框架 · DSL 引擎     │
└──────────────────────────────────────────────┘
```

### 6.2 架构评审

- **技术创新点**：Core Platform 的通用 AI 基础设施
- **差异化竞争**：Industry Solution Layer 的深度行业能力
- **企业级就绪**：Enterprise Control Plane 的多租户管控

### 6.3 团队职责映射

| 层级 | 负责团队 | 关键角色 |
|------|----------|----------|
| Core Platform | 平台团队 | 平台架构负责人、Core 开发工程师 |
| Enterprise Control Plane | 平台团队 | 平台产品负责人、安全合规工程师 |
| Industry Solution Layer | 行业团队 | 行业解决方案负责人、领域专家 |

---

## 七、修订记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-05-23 | 初始版本，基于 ISSUE-13 分层结论 | 架构评审（自动化） |
