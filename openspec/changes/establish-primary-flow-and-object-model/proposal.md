## Why

DeerFlow 当前缺少统一的跨模块主流程定义和对象模型基线。不同团队（产品、前端、网关、运行时）对 thread、run、upload、artifact 等核心概念的理解和命名不一致，导致状态语义混乱、跳转链路断裂、排期口径不统一。在三个月路线图开始实施前，必须先收敛这一基线，避免后续实现沿不同对象模型分叉。

## What Changes

- 定版 DeerFlow 第一主流程图："任务/对话 → 工具/知识 → 报告/产物 → 闭环/治理"
- 定版主对象模型清单：thread、run、upload、artifact、knowledge base、report run、closure ticket 的业务含义、生命周期边界和主要跳转关系
- 明确工作台一级导航中主入口页面 vs 扩展域页面的划分
- 识别并列出所有仍未拍板的问题，将其与主流程定义解耦

## Capabilities

### New Capabilities

- `primary-flow-definition`: DeerFlow 第一主流程图及跨角色共识版本
- `object-model-baseline`: 主对象模型清单，含各对象的职责、状态和关系定义
- `workspace-navigation-taxonomy`: 工作台一级导航的主入口与扩展域分类

### Modified Capabilities

<!-- 本次为基线收敛，不直接修改已有 spec 的需求行为 -->

## Impact

- 影响产品、前端、后端、网关、运行时所有团队对核心概念的共同理解
- 后续 ISSUE-02（统一状态语义）、ISSUE-03（打通跳转链路）、ISSUE-04（知识主链）均依赖此基线
- 交付物为共识文档和模型清单，不涉及代码变更
