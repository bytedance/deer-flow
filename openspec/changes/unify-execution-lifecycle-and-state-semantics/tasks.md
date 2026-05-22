## 1. 状态枚举定义

- [ ] 1.1 审计当前前后端代码中 thread、run、upload、artifact 的所有状态枚举定义
- [ ] 1.2 在 API 契约层（共享 schema 或 proto）定义统一状态枚举
- [ ] 1.3 将统一枚举同步到后端模型定义，标注旧枚举的废弃路径
- [ ] 1.4 将统一枚举同步到前端常量/类型定义

## 2. 失败分类实现

- [ ] 2.1 实现三层失败分类（EXECUTION_FAILED / UPLOAD_FAILED / EXTERNAL_DEPENDENCY_UNAVAILABLE）
- [ ] 2.2 为每种失败类型定义用户提示文案和可恢复动作
- [ ] 2.3 改造后端错误返回，使每个失败响应携带 failure_category 和 failed_layer 字段

## 3. 前端状态展示统一

- [ ] 3.1 更新所有展示 thread/run 状态的组件，使用统一状态枚举和文案
- [ ] 3.2 更新上传组件，展示 UPLOADING / PENDING_INDEX / INDEXING / INDEXED / FAILED 状态
- [ ] 3.3 更新 artifact 展示组件，使用 GENERATING / READY / FAILED 状态
- [ ] 3.4 实现在主链 UI 中展示失败层标识（runtime / gateway / external）

## 4. 日志与监控适配

- [ ] 4.1 统一后端日志中状态字段的命名和取值
- [ ] 4.2 确保日志中包含失败分类和层级信息，支持按层聚合查询

## 5. 回归测试

- [ ] 5.1 编写 thread/run 状态转换的回归测试
- [ ] 5.2 编写 upload 状态转换的回归测试
- [ ] 5.3 编写 artifact 状态转换的回归测试
- [ ] 5.4 编写三类失败场景（执行失败、上传失败、外部依赖不可用）的端到端测试验证
