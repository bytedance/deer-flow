# Implementation Plan

- [x] 1. 实现 MCP 工具信息收集功能

  - 创建 collect_mcp_tools_info 函数，从 MCP 客户端获取工具信息
  - 确保函数能够处理连接错误和异常情况
  - 在 src/graph/nodes.py 中实现该函数
  - _Requirements: 1.1_

- [x] 2. 扩展 Plan 模型以支持 MCP 工具

  - [x] 2.1 创建 StepTool 类，表示步骤中使用的工具

    - 在 src/prompts/planner_model.py 中实现 StepTool 类
    - 实现工具名称、描述、服务器和参数等属性
    - 添加序列化和反序列化支持
    - _Requirements: 1.3, 3.1_

  - [x] 2.2 扩展 Step 类，添加工具字段

    - 修改 src/prompts/planner_model.py 中的 Step 类，添加 tools 字段
    - 确保向后兼容性
    - _Requirements: 1.3, 3.1_

  - [x] 2.3 更新 Plan 模型验证逻辑
    - 确保扩展后的模型能够正确验证
    - 添加工具相关的验证规则
    - _Requirements: 1.3, 3.1_

- [x] 3. 修改 planner_node 函数

  - [x] 3.1 集成 MCP 工具信息收集

    - 在 planner_node 函数中调用 collect_mcp_tools_info 函数
    - 将工具信息添加到状态中
    - _Requirements: 1.1, 1.2_

  - [x] 3.2 更新 planner 提示模板

    - 在 src/prompts/planner.md 中添加 MCP 工具信息部分
    - 指导 LLM 考虑工具并在适当情况下使用
    - _Requirements: 1.2, 2.1, 2.2, 2.3_

  - [x] 3.3 处理工具感知计划的解析
    - 确保能够正确解析包含工具信息的计划
    - 处理解析错误和回退机制
    - _Requirements: 1.3, 3.1_

- [x] 4. 扩展 Configuration 类

  - [x] 4.1 添加 mcp_planner_integration 配置选项

    - 在 src/config/configuration.py 中添加 mcp_planner_integration 字段
    - 实现配置读取和验证逻辑
    - _Requirements: 4.1, 4.2_

  - [x] 4.2 实现配置界面
    - 在前端添加 MCP 工具配置界面
    - 添加全局开关控制功能
    - 实现配置保存和加载
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 5. 前端计划展示增强（可选）

  - [x] 5.1 基础工具标记

    - 在计划展示中标记使用了 MCP 工具的步骤
    - 添加简单的工具信息提示
    - _Requirements: 4.1, 4.2_

  - [x] 5.2 工具详情展示
    - 实现工具详情悬浮卡片
    - 显示工具描述和参数信息
    - _Requirements: 4.2, 4.3_
