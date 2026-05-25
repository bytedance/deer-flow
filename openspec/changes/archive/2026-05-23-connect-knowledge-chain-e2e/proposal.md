## Why

ISSUE-01 和 ISSUE-02 已定版主流程和状态语义，ISSUE-03 打通了跳转链路，但知识主链（上传→索引→检索→报告消费）仍缺少可演示、可验证的端到端路径。当前各环节独立工作（上传可创建文档、索引后台处理、LLM 可检索），但在以下方面存在断层：上传后索引状态对用户不够明确（需轮询等完成）、权限一致性缺少跨链路验证、缺少一条真正的端到端集成测试覆盖全流程。

## What Changes

- 上传反馈增强：上传完成后即时显示索引排队状态（pending→indexing→indexed/failed），前端轮询直到终态
- 权限一致性加固：在 `search_knowledge_base` 检索和 report run 上下文消费 KB 时，统一通过 `KbAccessControl` 校验，确保 workspace/retrieval/report 三链路使用同一权限模型
- 报告模板 DSL 中 `data_steps` 增加 KB 检索作为显式数据源选项，使报告可直接声明"本步骤从 KB 获取数据"
- 端到端集成测试：新增真实 pipeline 测试（upload→await index→search→report template data step），覆盖索引未完成/索引失败/权限拒绝三种边界场景

## Capabilities

### Modified Capabilities

- `upload-index-pipeline-visibility`: 上传后索引状态反馈增强（即时状态展示 + 轮询直到终态）
- `knowledge-permission-consistency`: 确认 `KbAccessControl` 在 workspace/retrieval/report run 三条链路上统一应用，补齐 report run 上下文中的权限校验
- `knowledge-chain-e2e-verification`: 从结构模拟升级为真实 pipeline 集成测试（真实上传→索引→检索→报告消费）

## Impact

- Frontend: `kb-documents-dialog.tsx`（上传后即时反馈）、`kb-index-health-card.tsx`（轮询增强）
- Backend: `knowledge_base/`（无新增，加固权限校验路径）、`report_templates/`（可选 KB 数据源声明）、`rag/tools.py`（权限校验文档化）
- Tests: `test_knowledge_chain_e2e.py`（从模拟升级为真实集成测试）
