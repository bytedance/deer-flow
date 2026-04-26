# 【文档13】工具与技能 —— Agent的"手"和"技能包"

## 1. 五分钟速览

**这篇文档解决什么问题？**

如果你想了解：
- Tool（工具）是什么？
- Skill（技能）是什么？
- DeerFlow的工具和技能系统如何实现？
- 如何添加自定义工具和技能？

那么这篇文档给你**工具与技能系统的完整认知**。

**阅读后你将获得**：
- Tool和Skill的核心概念和区别
- DeerFlow工具系统的实际实现（基于源码）
- 技能系统的加载和注入机制
- 面试时关于工具技能问题的精炼回答

---

## 2. Tool vs Skill：核心区别

### 2.1 对比表格

| 维度 | Tool（工具） | Skill（技能） |
|------|-------------|--------------|
| **定义** | Agent能调用的单个函数 | 打包好的完整能力 |
| **粒度** | 原子能力，单一功能 | 组合能力，完整方案 |
| **源码位置** | `tools/builtins/` | `skills/public/` |
| **存储格式** | Python类 | SKILL.md |
| **Agent使用** | 直接调用 | 通过提示词注入 |
| **示例** | search_web、bash、read_file | deep_research、data-analysis |

### 2.2 类比理解

```
Tool = 单个工具
→ 螺丝刀、扳手、锤子

Skill = 完整方案
→ 工具箱 + 使用手册
→ 例如：修车技能 = 扳手 + 螺丝刀 + 手册

DeerFlow中的关系：
→ Agent通过工具调用单个功能
→ Agent通过技能执行完整任务
→ 技能内部使用多个工具
```

---

## 3. 工具系统（基于实际代码）

### 3.1 工具加载机制

**源码位置**：`backend/packages/harness/deerflow/tools/__init__.py`

```python
# 来自：tools/__init__.py（简化）

def get_available_tools(
    model_name=None,
    groups=None,
    subagent_enabled=False,
    include_mcp=True
):
    """
    工具加载流程：
    1. 配置定义的工具（config.yaml）
    2. MCP工具（动态加载）
    3. 内置工具（builtins/）
    4. 子代理工具（如果启用）
    """

    tools = []

    # 1. 配置定义的工具
    config_tools = _resolve_tools_from_config()
    tools.extend(config_tools)

    # 2. MCP工具（懒加载，缓存）
    if include_mcp:
        mcp_tools = get_cached_mcp_tools()
        tools.extend(mcp_tools)

    # 3. 内置工具
    from deerflow.tools.builtins import (
        present_file_tool,
        ask_clarification_tool,
        view_image_tool
    )
    tools.extend([
        present_file_tool,
        ask_clarification_tool,
        view_image_tool  # 条件：模型支持vision
    ])

    # 4. 子代理工具
    if subagent_enabled:
        from deerflow.subagents import task_tool
        tools.append(task_tool)

    # 5. 沙箱工具
    from deerflow.sandbox.tools import (
        bash_tool,
        ls_tool,
        read_file_tool,
        write_file_tool
    )
    tools.extend([bash_tool, ls_tool, read_file_tool, write_file_tool])

    return tools
```

### 3.2 内置工具详解

**源码位置**：`backend/packages/harness/deerflow/tools/builtins/`

```
present_file_tool:
→ 展示输出文件
→ 只能展示/mnt/user-data/outputs/
→ 让用户看到Agent生成的文件

ask_clarification_tool:
→ 请求用户澄清
→ 被ClarificationMiddleware拦截
→ 中断执行，等待用户回复

view_image_tool:
→ 查看图像
→ 转换为base64
→ 只在模型支持vision时添加
```

### 3.3 沙箱工具

**源码位置**：`backend/packages/harness/deerflow/sandbox/tools.py`

```python
# 沙箱工具（简化）

bash_tool = {
    "name": "bash",
    "description": "执行bash命令",
    "parameters": {
        "command": {"type": "string"},
        "timeout": {"type": "integer", "default": 30}
    }
}

read_file_tool = {
    "name": "read_file",
    "description": "读取文件内容",
    "parameters": {
        "file_path": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"}
    }
}

write_file_tool = {
    "name": "write_file",
    "description": "写入文件",
    "parameters": {
        "file_path": {"type": "string"},
        "content": {"type": "string"}
    }
}

# 特点：
→ 虚拟路径转换（/mnt/user-data/ → 实际路径）
→ 权限检查
→ 错误处理
```

---

## 4. 技能系统（基于实际代码）

### 4.1 技能加载流程

**源码位置**：`backend/packages/harness/deerflow/skills/loader.py`

```python
# 来自：skills/loader.py

def load_skills(skills_path=None, enabled_only=False):
    """
    技能加载流程：
    1. 扫描public/和custom/目录
    2. 查找SKILL.md文件
    3. 解析YAML frontmatter
    4. 从extensions_config.json读取启用状态
    5. 按名称排序返回
    """

    skills = []

    # 扫描public和custom目录
    for category in ["public", "custom"]:
        category_path = skills_path / category

        # 递归查找SKILL.md
        for skill_file in category_path.rglob("SKILL.md"):
            # 解析技能文件
            skill = parse_skill_file(
                skill_file,
                category=category,
                relative_path=skill_file.parent.relative_to(category_path)
            )

            if skill:
                skills.append(skill)

    # 从配置更新启用状态
    extensions_config = ExtensionsConfig.from_file()
    for skill in skills:
        skill.enabled = extensions_config.is_skill_enabled(
            skill.name,
            skill.category
        )

    # 可选：只返回启用的技能
    if enabled_only:
        skills = [s for s in skills if s.enabled]

    return sorted(skills, key=lambda s: s.name)
```

### 4.2 SKILL.md格式

**源码位置**：`skills/public/*/SKILL.md`

```markdown
---
name: deep-research
description: 深度研究某个主题，生成完整报告
version: 1.0.0
author: DeerFlow Team
license: MIT
allowed-tools: [search_web, web_fetch, read_file, write_file]
---

# 深度研究技能

这是一个用于深度研究的技能...

## 使用方法
在DeerFlow中直接说："帮我研究XXX"
```

### 4.3 技能注入机制

**源码位置**：`backend/packages/harness/deerflow/agents/lead_agent/prompt.py`

```python
# 来自：prompt.py（简化）

def apply_prompt_template(
    subagent_enabled=False,
    max_concurrent_subagents=3,
    agent_name=None,
    available_skills=None
):
    """应用系统提示词"""

    # 加载启用的技能
    from deerflow.skills import load_skills

    enabled_skills = load_skills(enabled_only=True)

    # 构建技能部分
    skills_section = "## 可用技能\n"
    for skill in enabled_skills:
        skills_section += f"- **{skill.name}**: {skill.description}\n"
        skills_section += f"  容器路径: `/mnt/skills/{skill.path}`\n"

    # 构建系统提示词
    system_prompt = f"""
{skills_section}

## 你的角色
你是DeerFlow AI助手，可以使用上述技能...
"""

    return system_prompt
```

---

## 5. MCP工具集成

### 5.1 MCP配置

**配置文件**：`extensions_config.json`

```json
{
  "mcpServers": {
    "tavily": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@tavily/mcp-server"],
      "env": {
        "TAVILY_API_KEY": "$TAVILY_API_KEY"
      }
    },
    "filesystem": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"]
    }
  }
}
```

### 5.2 MCP工具加载

**源码位置**：`backend/packages/harness/deerflow/mcp/tools.py`

```python
# 来自：mcp/tools.py（简化）

def get_cached_mcp_tools():
    """获取缓存的MCP工具"""
    # 检查配置文件修改时间
    config_mtime = get_config_mtime()

    # 如果配置已更改，清除缓存
    if _cached_mcp_tools and _cached_mtime < config_mtime:
        _cached_mcp_tools = None

    # 加载MCP工具
    if _cached_mcp_tools is None:
        _cached_mcp_tools = _load_mcp_tools()
        _cached_mtime = config_mtime

    return _cached_mcp_tools

def _load_mcp_tools():
    """从MCP服务器加载工具"""
    from langchain_mcp_adapters import MultiServerMCPClient

    # 读取配置
    config = get_extensions_config()
    servers = config.mcpServers

    # 创建MCP客户端
    client = MultiServerMCPClient(servers)

    # 加载所有工具
    tools = []
    for server_name, server_config in servers.items():
        if server_config.enabled:
            server_tools = client.get_tools(server_name)
            tools.extend(server_tools)

    return tools
```

---

## 6. 设计思想

### 6.1 为什么分离Tool和Skill？

```
设计考量：

1. 灵活性 vs 便利性
   → Tool提供灵活性，可以自由组合
   → Skill提供便利性，开箱即用

2. 复用性
   → Tool是原子能力，可以跨场景复用
   → Skill是完整方案，可以跨任务复用

3. 学习曲线
   → Tool简单直接，易学易用
   → Skill封装复杂，但需要学习

4. 扩展性
   → Tool易于扩展
   → Skill可以通过组合Tool扩展
```

### 6.2 为什么用SKILL.md格式？

```
设计考量：

1. 人性化
   → Markdown易读易写
   → YAML frontmatter结构化

2. 可执行
   → 包含scripts目录
   → 包含templates和references

3. 可发现
   → 目录扫描容易
   → 统一的命名规则

4. 可版本控制
   → Git友好
   → Diff清晰
```

---

## 7. 面试要点

### Q1: Tool和Skill有什么区别？

**参考回答**：
```
核心区别：

Tool（工具）：
→ 原子能力，单个函数
→ 源码位置：tools/builtins/
→ 存储格式：Python类
→ Agent直接调用

Skill（技能）：
→ 完整方案，多个工具组合
→ 源码位置：skills/public/
→ 存储格式：SKILL.md
→ 通过提示词注入

类比：
Tool = 食材（鸡蛋、面粉）
Skill = 菜谱（蛋糕 = 鸡蛋+面粉+步骤）

为什么区分？
→ Tool提供灵活性
→ Skill提供便利性
→ 两者相辅相成
```

### Q2: DeerFlow有哪些内置工具？

**参考回答**：
```
内置工具（tools/builtins/）：

1. present_file_tool
   → 展示输出文件
   → 只能展示/mnt/user-data/outputs/

2. ask_clarification_tool
   → 请求用户澄清
   → 被ClarificationMiddleware拦截

3. view_image_tool
   → 查看图像
   → 转换为base64
   → 条件：模型支持vision

沙箱工具（sandbox/tools.py）：
1. bash - 执行命令
2. ls - 目录列表
3. read_file - 读取文件
4. write_file - 写入文件

特点：
→ 虚拟路径系统
→ 权限检查
→ 错误处理
```

### Q3: 技能系统如何加载和注入？

**参考回答**：
```
技能加载流程：

1. 扫描目录
   → 递归扫描public/和custom/
   → 查找SKILL.md文件

2. 解析技能
   → 解析YAML frontmatter
   → 提取name、description、allowed-tools

3. 读取启用状态
   → 从extensions_config.json读取
   → 更新enabled字段

4. 注入提示词
   → 在系统提示词中列出启用的技能
   → 包含技能名称、描述、容器路径

5. Agent使用
   → Agent根据任务选择技能
   → 技能内部的工具被调用

特点：
→ 动态加载，不需要重启
→ 启用状态可配置
→ 运行时更新
```

### Q4: MCP工具是如何集成的？

**参考回答**：
```
MCP集成流程：

1. 配置MCP服务器
   → extensions_config.json
   → 定义服务器类型、命令、参数

2. 懒加载
   → 首次使用时加载
   → 缓存工具列表
   → 配置更改时清除缓存

3. 工具获取
   → MultiServerMCPClient
   → 连接到MCP服务器
   → 获取工具列表

4. 工具调用
   → 与内置工具一样
   → 通过Agent调用
   → 返回结果

优势：
→ 标准化协议
→ 动态加载
→ 易于扩展
```

### Q5: 如何添加自定义工具？

**参考回答**：
```
添加自定义工具的步骤：

1. 定义工具函数
   def my_tool(param: str) -> str:
       # 实现逻辑
       return result

2. 注册工具（如果要复用）
   在config.yaml中定义

3. 添加到get_available_tools()
   或者通过config.yaml的tools字段

4. 测试验证
   → 单元测试
   → 集成测试

配置方式（config.yaml）：
tools:
  - name: my_tool
    use: mymodule:my_function
    group: custom

DeerFlow的扩展性是其核心优势。
```

---

## 8. 思考问题

### 8.1 理解检验

1. Tool和Skill的核心区别是什么？
2. DeerFlow有哪些内置工具？
3. 技能是如何加载和注入的？

### 8.2 设计思考

4. 为什么技能系统用SKILL.md格式？
5. MCP工具是如何集成到DeerFlow的？
6. 虚拟路径系统是如何工作的？

### 8.3 场景应用

7. 如果要创建一个"邮件发送"工具，应该怎么做？
8. 如果要创建一个"旅行规划"技能，需要哪些文件？
9. 如果要集成一个新的MCP服务器，应该怎么配置？

---

## 9. 本篇小结

**核心要点**：

1. **Tool**：原子能力，Python类，直接调用
2. **Skill**：完整方案，SKILL.md，提示词注入
3. **工具加载**：配置+MCP+内置+沙箱+子代理
4. **技能加载**：扫描SKILL.md→解析→注入提示词
5. **扩展方式**：工具通过config.yaml，技能通过SKILL.md

**你现在已经理解了工具与技能**，下一篇我们将深入**沙箱系统**，看看如何安全执行AI生成的代码。

---

## 10. 文档衔接

**本篇完结**，下一篇将解析：【14-沙箱系统：安全执行不可信代码】

**衔接说明**：
- 13篇解决了"Agent如何行动"的问题
- 14篇将解决"如何安全行动"的问题
- 工具调用可能涉及代码执行
- 沙箱是Agent安全能力的重要组成部分
