## ADDED Requirements

### Requirement: 对象模型清单覆盖全部 8 个核心对象

系统 SHALL 提供一份主对象模型清单，覆盖以下 8 个核心对象：thread、run、upload、artifact、knowledge base、report template、report run、closure ticket。

每个对象 SHALL 包含：
- **业务含义**：一句话定义
- **生命周期状态**：用 Mermaid `state` 图或表格列出所有状态和合法转换
- **关键关系**：列出与该对象有直接关联的其他对象和关联方式
- **主要 API 入口**：列出创建、查询、更新、删除对应的 Gateway API 端点

#### Scenario: 每个对象定义完整
- **WHEN** 新加入团队的开发或产品人员需要理解某个对象
- **THEN** 可以在对象模型清单中找到该对象的完整定义，无需查阅代码

#### Scenario: 对象间关系清晰
- **WHEN** 需要理解 thread 和 report run 的关系
- **THEN** 可以在两个对象的"关键关系"字段中找到彼此的关联方式和约束

### Requirement: 对象状态机有明确的状态转换规则

对于有生命周期的对象（thread、run、upload、report run、closure ticket），系统 SHALL 定义所有合法状态和状态转换路径。

状态定义 SHALL 覆盖：
- **初始状态**：对象创建时的默认状态
- **中间状态**：对象在执行或处理中的状态
- **终态**：对象不再变化的状态（成功、失败、取消）
- **非法转换**：明确标注哪些状态转换不可逆（如已完成的 run 不能回到执行中）

#### Scenario: 状态语义前后一致
- **WHEN** 前端展示状态标签和后端日志记录状态
- **THEN** 使用相同的状态名称和含义，不会出现状态命名歧义

#### Scenario: 失败状态可知恢复路径
- **WHEN** 对象处于失败状态（如 upload 转换失败、run 执行失败）
- **THEN** 状态定义中明确该失败是否可恢复，以及恢复动作（重试/重传/人工处理）

### Requirement: 对象模型基线可校验

系统 SHALL 确保对象模型定义中的 API 端点可以与当前 Gateway 路由实际注册的端点对应。

#### Scenario: API 端点与 Gateway 路由一致
- **WHEN** 对象模型清单列出某个对象的主要 API 入口
- **THEN** 这些端点可以在 `app/gateway/routers/` 中找到对应的路由注册
