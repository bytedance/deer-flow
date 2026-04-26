"""Gateway路由模块初始化

===================
设计思路说明
===================

**核心职责**：
作为Gateway路由层的统一入口，负责：
1. 聚合所有子路由模块
2. 通过__all__声明公共API
3. 为FastAPI应用提供一致的路由注册接口

**为什么需要这个模块**：
1. **模块化组织**：将不同功能的路由分散到独立文件中，提高可维护性
2. **统一导入**：外部只需从routers包导入，无需知道内部文件结构
3. **清晰的API边界**：通过__all__明确哪些模块是公共的

**架构说明**：
- 每个子模块（artifacts、assistants_compat等）负责一个功能领域的路由
- 主应用通过from app.gateway.routers import *一次性加载所有路由
- 使用FastAPI的include_router()机制将子路由挂载到主应用

**子模块说明**：
- artifacts: 文件产物管理API
- assistants_compat: LangGraph兼容性API（助手查询）
- mcp: MCP（Model Context Protocol）相关API
- models: 模型管理API
- skills: 技能/工具管理API
- suggestions: 建议生成API
- threads: 会话线程管理API
- thread_runs: 线程运行API
- uploads: 文件上传API
"""

from . import artifacts, assistants_compat, mcp, models, skills, suggestions, thread_runs, threads, uploads

# 为什么使用__all__：
# 1. 明确声明公共API：控制from app.gateway.routers import *的行为
# 2. 避免导入私有模块：未在__all__中的模块不会被意外导入
# 3. 文档作用：阅读代码的人可以快速了解有哪些路由模块
# 4. IDE支持：帮助IDE提供准确的自动补全
__all__ = ["artifacts", "assistants_compat", "mcp", "models", "skills", "suggestions", "threads", "thread_runs", "uploads"]
