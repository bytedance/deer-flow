## Why

DeerFlow 当前缺少一份被产品、架构、前后端共同认可的第一主流程定义和主对象模型基线。各模块独立演进，thread、run、artifact、report run、closure ticket 等核心对象的边界、生命周期和跳转关系没有统一文档，导致后续实现会沿着不同对象模型分叉。在进入更多跨模块开发（闭环工单、报告链路、能力配置）之前必须先收敛这一基线。

## What Changes

- 输出第一主流程图：固定"任务/对话 → 工具/知识 → 报告/产物 → 闭环/治理"的主链定义，标注各节点间的跳转关系
- 输出主对象模型清单：定义 thread、run、upload、artifact、knowledge base、report template、report run、closure ticket 共 8 个核心对象的业务含义、生命周期状态、关键关系和主要 API 入口
- 分类工作台一级导航：明确哪些页面属于主入口（核心工作流），哪些属于扩展域（管理/配置/设置）
- 列出所有仍未拍板的边界问题，不混在主流程定义里

## Capabilities

### New Capabilities

- `primary-flow-definition`: 第一主流程定义，含主流程图、节点职责、跳转关系
- `primary-object-model`: 主对象模型，含 8 个核心对象的定义、状态机、关系图

### Modified Capabilities

<!-- None — this is a baseline documentation change, no existing spec requirements are changing -->

## Impact

- 本文档产出本身即为交付物，不涉及代码变更
- 后续 ISSUE-02（统一生命周期）、ISSUE-03（打通跳转链路）、ISSUE-04（知识主链）将以此基线为输入
- 影响范围：产品、前端导航设计、后端 API 边界、网关路由结构
