## 1. Run Metadata 记录

- [ ] 1.1 定义 ReportRunMetadata 数据结构（templateId, templateVersion, knowledgeSources, triggerContext）
- [ ] 1.2 在报告运行引擎中实现 metadata 快照记录逻辑
- [ ] 1.3 实现 metadata 存储和查询接口

## 2. 产物血缘

- [ ] 2.1 报告产物关联 run_id
- [ ] 2.2 实现产物到 run 的回溯查询 API
- [ ] 2.3 前端实现产物→run→模板的回溯展示

## 3. 失败语义

- [ ] 3.1 实现模板失效错误语义和用户提示
- [ ] 3.2 实现知识不可用错误语义和用户提示
- [ ] 3.3 实现运行中断错误语义和重试入口

## 4. 端到端验证

- [ ] 4.1 编写模板→运行→产物的端到端验证测试
- [ ] 4.2 验证三类失败场景的错误信息准确性
