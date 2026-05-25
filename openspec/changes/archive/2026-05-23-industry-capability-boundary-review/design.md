## Context

DeerFlow 计划采用三层产品结构：Core Platform（通用平台）、Enterprise Control Plane（企业管控面）、Industry Solution Layer（行业方案层）。当前行业能力分散在各模块中，边界不清晰，需要在正式分层前做一次完整评审。

## Goals / Non-Goals

**Goals:**
- 逐项评审 InS 认证、组织、设备、行业报表、诊断链路等能力的归属
- 归类为 Core Platform / Enterprise Control Plane / Industry Solution Layer
- 争议能力列入待决清单
- 结论直接指导后续分层实施

**Non-Goals:**
- 不改变任何能力的代码实现
- 不决定行业层的具体交付方式（由 ISSUE-15 覆盖）

## Decisions

### 决策 1：三层分类标准

- **选择**：Core Platform = 所有租户共用的基础能力；Enterprise Control Plane = 租户级管控和定制；Industry Solution Layer = 行业特定的业务逻辑和数据模型
- **理由**：以"复用范围"作为分类的第一原则

### 决策 2：争议能力不强制分类

- **选择**：暂时无法明确归属的能力列入待决清单，标明争议点，后续迭代解决
- **理由**：宁可留下明确标注的灰色地带，也不做强行分类

## Risks / Trade-offs

- [风险] 行业团队与平台团队对分类有分歧 → 架构负责人做最终仲裁
