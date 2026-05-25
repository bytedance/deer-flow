## Context

基于 ISSUE-13 的分层分类结果，需要将 Core Platform / Enterprise Control Plane / Industry Solution Layer 三层转成正式的产品和发布原则。

## Goals / Non-Goals

**Goals:**
- 每层有清晰的职责、目标用户和边界
- 每层有变更原则和发布影响范围
- 新增需求能据此判断层级归属

**Non-Goals:**
- 不涉及代码层面的模块迁移
- 不决定行业层交付方式（ISSUE-15）

## Decisions

### 决策 1：每层以"谁受影响"定义发布影响范围

- **选择**：Core Platform 变更 → 所有租户；Enterprise Control Plane 变更 → 单个企业内所有用户；Industry Solution Layer 变更 → 特定行业的租户
- **理由**：以影响半径作为发布决策的核心维度

### 决策 2：变更原则分层

- **选择**：Core Platform 强调向后兼容和渐进式发布；Industry Solution Layer 允许更快的迭代节奏
- **理由**：不同层的稳定性要求不同

## Risks / Trade-offs

- [风险] 三层之间边界模糊区域的实际处理 → 以 ISSUE-13 的待决清单为指导，逐步收敛
