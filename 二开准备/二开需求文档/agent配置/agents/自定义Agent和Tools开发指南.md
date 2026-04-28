# DeerFlow 自定义 Agent 和 Tools 开发指南

本文档详细说明如何在 DeerFlow 框架中自主规划、创建和扩展自定义 Agent 与 Tools。

---

## 目录

1. [架构概览](#架构概览)
2. [自定义主 Agent](#自定义主-agent)
3. [自定义 Subagent（子 Agent）](#自定义-subagent子-agent)
4. [自定义工具（Tools）](#自定义工具tools)
5. [自定义技能（Skills）](#自定义技能skills)
6. [完整配置示例](#完整配置示例)
7. [最佳实践与注意事项](#最佳实践与注意事项)

---

## 架构概览

DeerFlow 是一个基于 LangGraph/LangChain 构建的多 Agent AI 框架，核心架构如下：

```
Lead Agent（主 Agent）
    │
    ├── Subagent: general-purpose（通用复杂任务）
    ├── Subagent: bash（命令执行）
    └── 自定义 Subagent（按需扩展）
```

**四层扩展体系**：
- **Agent** — 业务逻辑的承载体，定义人格、能力和行为边界
- **Subagent** — 主 Agent 委托给子任务的处理单元
- **Tools** — Agent 可调用的外部能力（搜索、文件操作、MCP 服务等）
- **Skills** — 可插拔的行为模板，通过 SKILL.md 文件定义

---

## 自定义主 Agent

### 1. 目录结构

```bash
# 在项目根目录下创建
mkdir -p agents/my-agent-name
```

完整目录结构：

```
agents/your-agent-name/
├── config.yaml          # Agent 配置文件（必需）
└── SOUL.md              # 人格定义文件（可选）
```

### 2. config.yaml 配置项

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `name` | string | 是 | Agent 唯一标识，必须符合正则 `^[A-Za-z0-9-]+$` | `my-researcher` |
| `description` | string | 否 | Agent 描述，用于工具匹配和 LLM 理解 | `"A research agent"` |
| `model` | string | 否 | 覆盖默认模型的模型名 | `gpt-4o` |
| `tool_groups` | list[string] | 否 | 允许使用的工具组列表 | `["web", "file"]` |
| `skills` | list[string] | 否 | 启用的技能名称列表 | `["deep-research"]` |

### 3. 配置示例

```yaml
# agents/my-researcher/config.yaml
name: my-researcher
description: A specialized research agent for academic papers and technical documentation
model: gpt-4o                    # 覆盖默认模型（可选）
tool_groups: ["web", "file"]     # 限制只能使用 web 和 file 工具组
skills: ["deep-research"]        # 启用深度研究技能
```

### 4. SOUL.md 人格定义（可选）

SOUL.md 文件用于定义 Agent 的人格、价值观和行为边界，会被注入到系统提示中。

```markdown
---
name: my-researcher
---

# Researcher Soul

## Personality & Values
- Always be thorough and methodical in research
- Cite sources with [citation](URL) format
- Never fabricate data or statistics

## Behavior Guidelines
1. Start by understanding the user's core question
2. Break down complex topics into manageable parts
3. Validate all findings before presenting conclusions
```

### 5. 注册机制

**自动扫描发现**：框架启动时会自动扫描 `agents/` 目录下的所有子目录，无需手动注册。只要创建符合规范的目录和文件，Agent 就会被自动加载。

---

## 自定义 Subagent（子 Agent）

Subagent 是主 Agent 在遇到复杂任务时委托处理的专用单元。

### 1. 在 config.yaml 中注册

```yaml
# config.yaml
subagents:
  custom_agents:
    code-reviewer:
      name: code-reviewer                        # 子 Agent 唯一标识
      description: >                              # LLM 何时委托此子 Agent（关键！）
        A specialized agent for reviewing and 
        improving code quality, performance, 
        and security.
      system_prompt: |                            # 子 Agent 的系统提示词
        You are an expert code reviewer. Analyze 
        code for correctness, performance, security,
        and best practices. Provide actionable feedback.
      tools: ["read_file", "write_file"]          # 可选：限制工具集（None=继承父级所有）
      disallowed_tools: []                        # 排除的工具列表（默认排除 task, ask_clarification, present_files）
      model: inherit                              # 或指定具体模型名如 "gpt-4o-mini"
      max_turns: 30                               # 最大轮次（默认 50）
      timeout_seconds: 600                        # 超时时间秒（默认 900）
```

### 2. Per-Agent 覆盖

针对特定 Agent 的 Subagent 行为进行个性化调整：

```yaml
# config.yaml
agents:
  code-reviewer:                                    # Agent 名与上面一致
    model: gpt-4o-mini                              # 仅对 my-researcher 使用 code-reviewer 时生效
    skills: ["code-documentation"]                  # 覆盖该 Agent 使用的技能
```

### 3. 内置 Subagent

框架预置了两个子 Agent：

| 名称 | 用途 | 工具限制 |
|------|------|---------|
| `general-purpose` | 通用复杂任务，多步推理 | 继承所有工具 |
| `bash` | Bash 命令执行 | 仅限 shell 相关工具 |

通过 `task_tool`（`@tool("task")`）由主 Agent 委托调用。

### 4. 注册顺序（三层覆盖机制）

```
1. 内置 Subagent (BUILTIN_SUBAGENTS)      ← 最低优先级
2. 自定义 Subagent (config.yaml 的 subagents.custom_agents)
3. Per-Agent 覆盖 (config.yaml 的 agents)  ← 最高优先级
```

---

## 自定义工具（Tools）

### 1. 方式一：使用 `@tool()` 装饰器（推荐）

适用于简单的工具函数，代码简洁。

```python
# my_tools/custom_search.py
from langchain.tools import tool

@tool("custom_search")
def custom_search(query: str, engine: str = "default") -> str:
    """Search using a custom search engine.
    
    Args:
        query: The search query string to search for
        engine: Search engine to use (default, academic, news)
        
    Returns:
        Formatted search results as a string
    """
    # 实现你的逻辑
    results = do_custom_search(query, engine)
    return format_results(results)
```

### 2. 方式二：使用 Pydantic Tool 类

适用于需要复杂输入验证和更精细控制的场景。

```python
# my_tools/custom_tool.py
from langchain.tools import BaseTool
from pydantic import BaseModel, Field


class MyCustomInput(BaseModel):
    """自定义输入参数的 Schema"""
    query: str = Field(description="Search query to execute")
    limit: int = Field(default=10, description="Maximum number of results")


class MyCustomTool(BaseTool):
    name: str = "my_custom_tool"                    # 工具名（唯一标识）
    description: str = "Perform a custom search operation"   # 工具描述（供 LLM 理解何时使用）
    args_schema: type[BaseModel] = MyCustomInput    # 输入参数 Schema
    
    def _run(self, query: str, limit: int = 10) -> str:
        """Tool 的实际执行逻辑"""
        results = do_custom_search(query, limit)
        return format_results(results)
```

### 3. 在 config.yaml 中注册工具

```yaml
# config.yaml
tools:
  # 内置工具...
  
  # 自定义工具注册
  - name: custom_search                           # 工具名（唯一标识）
    use: "my_tools.custom_search:custom_search"   # module_path:attribute_name（反射加载）
    group: search                                 # 分组标识（用于 tool_groups 过滤）
```

**关键机制**：`use` 字段通过字符串反射导入 Python 对象，格式为 `模块路径:属性名`。例如：
- `my_tools.custom_search:custom_search` → 从 `my_tools/custom_search.py` 导入 `custom_search`
- `my_package.tools:MyCustomTool` → 从 `my_package/tools.py` 导入 `MyCustomTool`

### 4. 在 Agent 中启用工具组

```yaml
# agents/my-agent/config.yaml
tool_groups: ["search", "web"]   # 包含自定义的 "search" 组和内置的 "web" 组
```

---

## 自定义技能（Skills）

Skills 是通过 SKILL.md 文件定义的可插拔行为模板，用于扩展 Agent 的能力。

### 1. 目录结构

```bash
# 在项目根目录下创建
mkdir -p skills/custom/my-skill
```

完整目录树：

```
skills/
├── public/                          # 内置公开技能（框架自带）
│   ├── deep-research/SKILL.md       # 深度研究技能
│   │                               # + references/ (可选的参考资料)
│   └── code-documentation/SKILL.md  # 代码文档技能
├── custom/                          # 用户自定义技能（按需创建）
│   └── my-skill/
│       ├── SKILL.md                 # 技能定义文件（必需）
│       └── references/              # 可选的参考资料目录
│           └── example.md
```

### 2. SKILL.md 文件格式

```markdown
---
name: my-sskill                           # 技能唯一标识符（Python 标识符格式）
description: >                            # **触发机制**：LLM 根据此描述决定是否使用该技能
  Use this skill when the user needs to 
  perform custom task X. Trigger on 
  phrases like "do X", "handle Y".
---

# My Custom Skill

## Overview
简要描述这个技能的作用和适用场景。

## When to use
详细说明何时应该使用此技能，包括：
- 用户输入的特征
- 任务类型的判断标准
- 与其他技能的区分

## Steps
1. **第一步**：具体操作步骤一
   - 子步骤或注意事项
   
2. **第二步**：具体操作步骤二
   - 示例代码或输出格式

3. **第三步**：验证和总结

## References (optional)
- See references/example.md for more details
```

### 3. Progressive Disclosure（渐进式加载）

Skills 使用三层加载策略以节省 token 消耗：

| 层级 | 内容 | 触发时机 | Token 限制 |
|------|------|---------|-----------|
| **1. 元数据** | name + description | 始终在上下文中 | ~100 词 |
| **2. SKILL.md body** | 技能正文（步骤、说明） | 技能触发时加载 | 建议 <500 行 |
| **3. Bundled resources** | references/, scripts/ | 按需动态加载 | 无限制 |

### 4. 启用/禁用控制

在 `extensions_config.json` 中可以控制自定义技能的启用状态：

```json
{
  "skills": {
    "my-skill": {
      "enabled": true
    }
  }
}
```

---

## 完整配置示例

### config.yaml 结构摘要

```yaml
# ============================================
# 模型定义
# ============================================
models:
  - name: gpt-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o

# ============================================
# 自定义工具注册
# ============================================
tools:
  # 内置工具...
  
  # 自定义搜索工具
  - name: custom_search
    use: "my_tools.custom_search:custom_search"
    group: search
  
  # 自定义文件处理工具
  - name: file_processor
    use: "my_tools.file_ops:FileProcessorTool"
    group: file

# ============================================
# Subagent 配置
# ============================================
subagents:
  custom_agents:
    code-reviewer:
      name: code-reviewer
      description: >
        A specialized agent for reviewing and 
        improving code quality.
      system_prompt: |
        You are an expert code reviewer. Analyze 
        code for correctness, performance, security,
        and best practices.
      tools: ["read_file"]                  # 可选：限制工具集
      disallowed_tools: []                  # 排除的工具（默认排除 task, ask_clarification, present_files）
      model: inherit                        # 或 "gpt-4o-mini"
      max_turns: 30                         # 最大轮次（默认 50）
      timeout_seconds: 600                  # 超时秒（默认 900）
  
  timeout_seconds: 900    # 全局默认超时
  max_turns: 50           # 全局默认最大轮次

# ============================================
# Per-Agent 覆盖（针对特定 Agent 的子 Agent 行为调整）
# ============================================
agents:
  code-reviewer:
    model: gpt-4o-mini                              # 仅对 my-researcher 使用 code-reviewer 时生效
    skills: ["code-documentation"]                  # 覆盖该 Agent 使用的技能

# ============================================
# 其他配置
# ============================================
tool_search:
  enabled: true                                     # 启用工具搜索（MCP 工具按需调用）

memory:
  enabled: true                                     # 启用记忆系统
  max_facts: 50                                     # 最大记忆事实数

sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider  # 沙箱配置
```

---

## 最佳实践与注意事项

### 1. Agent 设计原则

- **单一职责**：每个 Agent 应有明确的功能边界，避免功能混杂
- **清晰的 description**：`description` 字段直接影响 LLM 对 Agent 能力的理解，务必准确描述
- **合理的 tool_groups**：限制工具组可以提高安全性和减少 token 消耗
- **SOUL.md 的重要性**：通过 SOUL.md 定义人格和行为边界，使 Agent 表现更一致

### 2. Subagent 委托策略

- **description 是触发关键**：LLM 根据 `description` 决定是否委托给子 Agent，描述应清晰说明何时使用
- **工具隔离**：通过 `disallowed_tools` 限制子 Agent 的工具访问权限，提高安全性
- **轮次控制**：设置合理的 `max_turns` 和 `timeout_seconds`，防止无限循环

### 3. 工具开发规范

- **命名唯一性**：确保工具名全局唯一，避免冲突
- **描述清晰**：`description` 字段直接影响 LLM 对工具的调度，务必准确且详细
- **输入验证**：使用 Pydantic BaseModel 定义输入参数 Schema，实现类型安全和自动校验
- **错误处理**：在工具内部处理可能的异常情况，返回友好的错误信息

### 4. Skills 编写技巧

- **description 决定触发率**：LLM 根据此描述决定是否使用该技能，应包含明确的触发条件
- **步骤清晰可操作**：每一步都应具体、明确，避免模糊的描述
- **合理使用 references**：将详细参考资料放在 `references/` 目录下，按需加载节省 token
- **技能粒度适中**：过大的技能难以维护，过小的技能增加管理成本

### 5. 安全注意事项

- **沙箱隔离**：在使用沙箱模式时，host bash 工具会被自动过滤
- **工具组限制**：通过 `tool_groups` 严格控制 Agent 可访问的工具范围
- **子 Agent 权限**：使用 `disallowed_tools` 排除危险操作（如 `task`, `ask_clarification`）
- **文件路径控制**：在自定义工具中验证文件路径，防止路径遍历攻击

### 6. 调试与排错

- **日志输出**：检查后端日志确认 Agent/Tools/Skills 是否正确加载
- **配置校验**：框架使用 Pydantic 进行配置校验，启动时会报告格式错误
- **测试工具注册**：通过 API 接口检查已注册的工具列表
- **技能触发测试**：观察 LLM 的实际行为，验证 `description` 是否有效触发预期技能

---

## 附录：扩展能力全景图

| 扩展类型 | 定义位置 | 核心文件/机制 | 注册方式 |
|---------|---------|-------------|---------|
| **自定义 Agent** | `agents/{name}/config.yaml` + `SOUL.md` | agents_config.py | 自动扫描发现（创建目录即可） |
| **自定义 Subagent** | config.yaml → `subagents.custom_agents` | subagents_config.py | YAML 配置添加 |
| **自定义工具** | Python 模块 + config.yaml | tools/tools.py | `use: module_path:attr` 反射加载 |
| **自定义 Skill** | `skills/custom/{name}/SKILL.md` | skills/loader.py | 自动扫描 + extensions 控制 |
| **自定义 Middleware** | Python 模块 | agents/middlewares/ | `@Next/@Prev` 装饰器声明位置 |

---

## 参考文档

- DeerFlow 官方文档：https://deerflow-ai.github.io/
- LangChain Tools 文档：https://python.langchain.com/docs/modules/tools/
- LangGraph 文档：https://langchain-ai.github.io/langgraph/
- MCP (Model Context Protocol)：https://modelcontextprotocol.io/

---

*本文档基于 DeerFlow v2.x 版本编写，适用于自定义扩展开发。*
