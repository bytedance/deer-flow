"""
Lead Agent模块 - DeerFlow的主代理

===================
设计思路说明
===================

**为什么需要这个模块**：
1. **应用层入口**：提供配置驱动的代理创建API
2. **生产就绪**：集成所有可用的中间件和功能
3. **默认实现**：作为DeerFlow的标准代理实现
4. **简化使用**：用户无需手动配置中间件

**核心功能**：
- make_lead_agent: 从config.yaml创建配置好的代理

**为什么这样设计**：
- **约定优于配置**：提供合理的默认值
- **可覆盖性**：支持通过配置文件覆盖行为
- **完整性**：包含所有必要的中间件

**使用方式**：
```python
from deerflow.agents import make_lead_agent

agent = make_lead_agent()  # 从config.yaml读取配置
```
"""

from .agent import make_lead_agent

__all__ = ["make_lead_agent"]
