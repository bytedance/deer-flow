## Context

DeerFlow 有五种能力类型（Model、Skill、MCP、Connector、Agent），当前每种能力有自己的管理方式和命名约定。需要统一治理模型后再进入实现。

## Goals / Non-Goals

**Goals:**
- 统一五类能力的配置和发布词汇表
- 明确全局/租户字段边界
- 定义发布、回滚、停用和变更责任
- 结论可直接指导 ISSUE-10 和 ISSUE-11

**Non-Goals:**
- 不实现配置管理界面
- 不改动现有能力的内部实现

## Decisions

### 决策 1：统一配置模型基础属性 + 扩展属性

- **选择**：所有能力共享 base fields（name, type, scope, status, owner, version, audit），各类型有 type-specific extension fields
- **替代方案**：每类能力独立 schema → 无法统一治理
- **理由**：基础属性统一是治理的前提，扩展属性保留灵活性

### 决策 2：Scope 采用三值枚举

- **选择**：GLOBAL（平台级）| TENANT（租户级）| TENANT_OVERRIDE（租户覆盖全局）
- **替代方案**：只有 GLOBAL/TENANT 两值 → 无法表达租户定制全局能力的场景
- **理由**：三值模型覆盖了全部实际场景

## Risks / Trade-offs

- [风险] 扩展属性过于灵活导致变相分裂 → 扩展字段也纳入 schema review
