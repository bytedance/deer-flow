"""
Token使用统计配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义token使用统计开关
2. 控制中间件行为

**为什么需要token统计**：
- 追踪API成本
- 监控使用情况
- 优化提示词长度
- 预算管理和限制

**统计内容**：
- 输入token数
- 输出token数
- 总token数
- 按模型分类统计

**为什么默认禁用**：
- 减少性能开销
- 不需要时避免日志噪音
- 按需启用
"""

from pydantic import BaseModel, Field


class TokenUsageConfig(BaseModel):
    """Token使用统计配置

    **enabled字段**：
    - 是否启用token使用统计中间件
    - 默认禁用（False）
    - 启用后自动记录每次调用的token使用

    **统计工作原理**：
    1. 中间件拦截模型调用
    2. 提取token使用信息
    3. 记录到日志或数据库
    4. 汇总和报告

    **使用场景**：
    - 成本追踪和预算管理
    - 性能优化分析
    - 用户使用统计
    - 调试和监控
    """

    enabled: bool = Field(default=False, description="Enable token usage tracking middleware")
