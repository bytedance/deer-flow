"""中间件模块 - 代理执行链的扩展点

===================
设计思路说明
===================

**核心职责**：
提供中间件的统一入口和组织方式。虽然此文件为空，但它定义了
中间件模块的边界，便于导入和组织各个中间件组件。

**为什么需要这个模块**：
1. **模块组织**：将相关中间件放在同一目录下
2. **导入便利**：提供from deerflow.agents.middlewares import XXX的导入方式
3. **文档作用**：明确这是一个中间件包

**中间件列表**：
- clarification_middleware: 拦截澄清请求并中断执行
- dangling_tool_call_middleware: 修复悬空的工具调用
- deferred_tool_filter_middleware: 过滤延迟工具的schema
- sandbox_middleware: 管理沙箱环境
- title_middleware: 自动生成对话标题
- uploads_middleware: 处理文件上传
- view_image_middleware: 支持视觉模型

**架构说明**：
- 每个中间件都是独立的模块
- 中间件按特定顺序执行
- 支持同步和异步两种模式
- 可以修改请求和响应
"""
