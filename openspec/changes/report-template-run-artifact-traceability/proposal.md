## Why

报告模块当前停留在孤立的"结果页"——用户和运营人员无法回答"这份报告是由哪版模板、哪条运行、哪些知识输入产出的"。模板变更后，历史报告失去上下文；运行中断后，无法追溯到具体断点。需要建立从模板到产物的完整可追踪链路。

## What Changes

- 报告运行记录可看到模板版本、触发上下文和主要输入来源
- 报告产物可回溯到对应的 report run
- 模板失效、知识不可用、运行中断等场景的错误语义清晰
- 至少有一条从模板到产物的端到端验证路径

## Capabilities

### New Capabilities

- `report-run-context-recording`: 报告运行的模板版本、触发上下文和知识来源记录
- `report-artifact-lineage`: 报告产物到 report run 的回溯链路
- `report-failure-semantics`: 模板失效、知识不可用、运行中断的错误分类与语义

### Modified Capabilities

<!-- 可能涉及现有报告生成模块的错误处理 -->

## Impact

- 影响报告模板管理、报告运行引擎、报告产物存储
- 需要为每次 report run 记录元数据上下文
- 依赖 ISSUE-03（聊天-报告跳转链路）和 ISSUE-04（知识主链）
