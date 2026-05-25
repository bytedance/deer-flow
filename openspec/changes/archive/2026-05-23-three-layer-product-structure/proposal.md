## Why

ISSUE-13 完成了三层分层评审，但分层结论如果不转化为正式的产品与交付原则，将停留在概念层无法指导实施。需要把 Core Platform、Enterprise Control Plane、Industry Solution Layer 转成包含目标用户、核心职责、变更原则和发布影响范围的正式原则。

## What Changes

- 三层结构的职责、边界和目标用户被清晰写明
- 每层的变更原则和发布影响范围被明确定义
- 新增需求可据此判断应该进入哪一层
- 材料可直接复用于 roadmap、评审和对外产品表述

## Capabilities

### New Capabilities

- `three-layer-responsibility-matrix`: 三层各自的职责、目标用户和边界定义
- `change-principles-per-layer`: 每层的变更原则和发布影响范围
- `requirement-layer-routing`: 新增需求判断归属哪一层的决策标准

### Modified Capabilities

<!-- 原则文档类，不修改现有 spec -->

## Impact

- 指导所有后续需求的归属判断
- 直接影响 ISSUE-15（行业层交付方式）
- 可用于对外产品表述和架构评审
- 依赖 ISSUE-13（行业能力边界评审）
