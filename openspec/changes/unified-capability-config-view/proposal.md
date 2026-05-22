## Why

当前平台配置者需要在多个孤立页面或接口之间理解 Model、Skill、MCP、Connector、Agent 的关系，缺乏统一的配置视图。在 ISSUE-09 定版了统一配置模型后，需要交付一版统一能力配置视图，让配置者从单一入口理解和治理平台能力。

## What Changes

- 配置者可在统一入口查看主要能力类型及其关键状态
- 每类能力至少支持查看、识别作用域和查看最近变更
- 术语、状态和操作提示与 ISSUE-09 的治理口径一致
- 不再需要依赖多套不一致的配置认知来理解平台能力

## Capabilities

### New Capabilities

- `unified-capability-list-view`: 统一入口的能力列表视图，展示所有类型和关键状态
- `capability-detail-view`: 每类能力的详情视图，含作用域和最近变更

### Modified Capabilities

<!-- 一期独立构建，不修改现有 spec -->

## Impact

- 新增管理台配置视图页面
- 需要查询跨五种能力类型的聚合数据
- 依赖 ISSUE-09（统一配置模型）
