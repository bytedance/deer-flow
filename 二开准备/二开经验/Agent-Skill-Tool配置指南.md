# Agent / Skill / Tool 配置指南

本文档说明如何在 DeerFlow 二开项目中配置 Agent、Skill 和 Tool。

---

## 一、整体架构

```
config.yaml (全局配置)
├── models          → 模型配置（LLM 连接信息）
├── tool_groups     → 工具组声明
├── tools           → 工具注册（名称 → Python 模块映射）
├── skills          → Skills 目录配置
├── subagents       → 子 Agent 超时/轮次配置
└── custom_agents   → 自定义子 Agent 定义（描述、提示词、工具、模型）

backend/.deer-flow/agents/
├── novel-master/           ← 主 Agent
│   ├── SOUL.md             ← 人格/指令提示词
│   └── config.yaml         ← Agent 配置（模型、工具组、技能、子 Agent 开关）
├── novel-writer/           ← 子 Agent 1
│   ├── SOUL.md
│   └── config.yaml
├── continuity-auditor/     ← 子 Agent 2
│   └── ...
└── ...                     ← 更多子 Agent
```

---

## 二、配置 Tool（工具）

### 2.1 工具注册流程

工具在 `config.yaml` 中注册，分为两步：

#### 步骤 1：声明工具组

```yaml
tool_groups:
  - name: web              # 网络搜索组
  - name: file:read        # 文件读取组
  - name: file:write       # 文件写入组
  - name: bash             # 命令行组
  - name: novel            # 小说写作工具组（自定义）
```

#### 步骤 2：注册具体工具

```yaml
tools:
  # === 内置工具示例 ===
  - name: read_file
    group: file:read
    use: deerflow.sandbox.tools:read_file_tool

  - name: write_file
    group: file:write
    use: deerflow.sandbox.tools:write_file_tool

  # === 自定义工具示例 ===
  - name: context_assembler
    group: novel
    use: my_tools.context_assembler:context_assembler

  - name: card_validator
    group: novel
    use: my_tools.card_validator:card_validator
```

**字段说明**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 工具名称（Agent 调用时使用的名称） | `card_validator` |
| `group` | 所属工具组 | `novel` |
| `use` | Python 模块映射：`模块路径:函数名` | `my_tools.card_validator:card_validator` |

### 2.2 编写自定义 Tool

在 `my_tools/` 目录下创建 Python 文件：

```python
# my_tools/card_validator.py
from langchain.tools import tool

@tool("card_validator")
def card_validator(card_path: str, fix: bool = True) -> str:
    """验证并规范化 card.json 文件格式。

    Args:
        card_path: card.json 文件路径
        fix: 是否自动修复格式问题
    """
    # ... 工具逻辑
    return "验证结果报告"
```

**要点**：
- 使用 `@tool("工具名")` 装饰器
- 函数必须有类型注解和 docstring
- 返回字符串作为工具输出
- 在 `config.yaml` 中注册后，Agent 即可调用

### 2.3 工具使用示例

Agent 在对话中调用工具：

```
调用 card_validator 验证文件：
- card_path: "book/测试项目/card.json"
- fix: true
```

---

## 三、配置 Agent

### 3.1 Agent 目录结构

每个 Agent 在 `backend/.deer-flow/agents/<agent-name>/` 下有一个目录：

```
backend/.deer-flow/agents/novel-master/
├── SOUL.md      # Agent 人格/指令提示词（核心）
└── config.yaml  # Agent 运行配置
```

### 3.2 config.yaml 配置

```yaml
name: novel-master
description: |
  小说创作系统主控Agent，负责协调所有子Agent完成小说创作任务。
  接收用户指令，判断任务类型，调用合适的子Agent，管理整个创作流程。
model: null                        # null = 使用全局默认模型
tool_groups:                       # 此 Agent 可用的工具组
  - file:read
  - file:write
  - bash
  - novel                          # 包含自定义工具（context_assembler 等）
skills:                            # 此 Agent 可用的技能
  - novel-post-write-validator
  - novel-anti-ai-detector
  - novel-plan-compliance
subagent_enabled: true             # 是否允许调用子 Agent
max_concurrent_subagents: 3        # 最大并发子 Agent 数量
```

**字段说明**：

| 字段 | 说明 | 示例值 |
|------|------|--------|
| `name` | Agent 名称 | `novel-master` |
| `description` | Agent 描述（用于子 Agent 发现） | 多行文本 |
| `model` | 使用的模型（null=继承全局） | `null` 或模型名 |
| `tool_groups` | 可用工具组列表 | `["file:read", "novel"]` |
| `skills` | 可用技能列表 | `["novel-post-write-validator"]` |
| `subagent_enabled` | 是否启用子 Agent 调用 | `true`/`false` |
| `max_concurrent_subagents` | 最大并发子 Agent 数 | `3` |

### 3.3 SOUL.md 配置

SOUL.md 是 Agent 的核心人格文件，定义了：
- Agent 的角色和职责
- 工作流程和决策树
- 输入输出规范
- 目录结构认知
- 注意事项和约束

**标准 SOUL.md 结构**：

```markdown
# [系统名称] - [Agent名称] Agent

你是 [描述]。

## 职责
1. ...
2. ...

## 工作流程
### 步骤1：...
### 步骤2：...

## 输入输出
...

## 目录结构
...

## 当前环境
- 工作目录：${__WORKING_DIR__}
```

### 3.4 子 Agent 配置

子 Agent 在 `config.yaml` 的 `subagents.custom_agents` 中定义：

```yaml
subagents:
  timeout_seconds: 900              # 默认超时
  max_turns: 50                     # 默认最大轮次

  # 特定 Agent 的超时覆盖
  agents:
    novel-writer:
      timeout_seconds: 1800
      max_turns: 80

  # 自定义子 Agent 定义
  custom_agents:
    novel-writer:
      description: |
        长篇网文写手，负责根据写作任务汇总撰写小说正文。
      system_prompt: |
        你是一个专业的长篇网文写手...
        ## 写作风格要求
        1. ...
        2. ...
      tools:                        # 此子 Agent 可用的具体工具
        - read_file
        - write_file
      model: inherit                # inherit = 继承父 Agent 模型
      max_turns: 80
      timeout_seconds: 1800
```

**字段说明**：

| 字段 | 说明 | 示例值 |
|------|------|--------|
| `description` | 子 Agent 描述（用于主 Agent 发现） | 多行文本 |
| `system_prompt` | 子 Agent 的系统提示词 | 多行文本 |
| `tools` | 子 Agent 可用的工具列表 | `["read_file", "write_file"]` |
| `model` | 使用的模型 | `inherit` 或模型名 |
| `max_turns` | 最大对话轮次 | `80` |
| `timeout_seconds` | 超时时间（秒） | `1800` |

### 3.5 新增 Agent 的完整流程

1. **创建 Agent 目录**：
   ```
   backend/.deer-flow/agents/my-new-agent/
   ├── SOUL.md
   └── config.yaml
   ```

2. **编写 SOUL.md**：定义 Agent 人格和职责

3. **编写 config.yaml**：
   ```yaml
   name: my-new-agent
   description: 描述此 Agent 的功能
   model: null
   tool_groups:
     - file:read
     - file:write
   subagent_enabled: false
   ```

4. **如需作为子 Agent 被调用**，在 `config.yaml` 的 `subagents.custom_agents` 中添加定义

5. **重启服务**使配置生效

---

## 四、配置 Skill（技能）

### 4.1 Skill 注册

Skill 在 `config.yaml` 中配置目录：

```yaml
skills:
  path: skills                    # 相对于项目根目录的路径
  container_path: /mnt/skills     # 沙箱内的路径
```

### 4.2 在 Agent 中使用

在 Agent 的 `config.yaml` 中声明要使用的技能：

```yaml
skills:
  - novel-post-write-validator
  - novel-anti-ai-detector
  - novel-plan-compliance
```

### 4.3 Skill 目录结构

每个 Skill 是一个独立的目录，包含：

```
skills/novel-post-write-validator/
├── SKILL.md          # 技能描述和使用说明
├── prompt.md         # 技能提示词
└── ...               # 其他相关文件
```

---

## 五、工具 / 技能 / Agent 的关系

```
Agent (novel-master)
├── 使用 tool_groups → 获得一组工具
│   ├── file:read    → read_file, glob, grep
│   ├── file:write   → write_file, str_replace
│   └── novel        → context_assembler, card_validator, ...
│
├── 使用 skills      → 加载技能提示词
│   ├── novel-post-write-validator
│   └── novel-anti-ai-detector
│
└── 调用子 Agent     → 通过 task 工具委派任务
    ├── novel-writer
    ├── novel-architect
    └── continuity-auditor
```

**区别**：

| 概念 | 本质 | 用途 | 执行方式 |
|------|------|------|----------|
| **Tool** | Python 函数 | 执行具体操作（读写文件、验证格式等） | Agent 直接调用 |
| **Skill** | 提示词模板 | 增强 Agent 的特定能力 | 自动加载到上下文 |
| **Agent** | 独立 LLM 会话 | 执行复杂任务（写正文、审核等） | 通过 task 工具委派 |

---

## 六、常用配置示例

### 6.1 给 Agent 添加新工具

1. 在 `my_tools/` 下创建工具文件
2. 在 `config.yaml` 的 `tools` 段注册
3. 确保工具所属的 `tool_group` 已声明
4. Agent 的 `config.yaml` 中引用该工具组

### 6.2 修改子 Agent 超时

```yaml
subagents:
  agents:
    my-agent:
      timeout_seconds: 3600    # 改为 1 小时
      max_turns: 100           # 改为 100 轮
```

### 6.3 创建新的工具组

```yaml
tool_groups:
  - name: my-custom-group    # 新增工具组

tools:
  - name: my-tool
    group: my-custom-group   # 归入新工具组
    use: my_tools.my_module:my_function
```

然后在 Agent 配置中引用：

```yaml
tool_groups:
  - file:read
  - my-custom-group          # 引用新工具组
```

---

## 七、调试技巧

### 7.1 验证工具是否注册

检查 `config.yaml` 中 `tools` 段是否有对应条目。

### 7.2 验证 Agent 是否能使用工具

检查 Agent 的 `config.yaml` 中 `tool_groups` 是否包含该工具所属的组。

### 7.3 查看 Agent 提示词

直接读取 `backend/.deer-flow/agents/<agent-name>/SOUL.md`。

### 7.4 重启服务

修改配置后需要重启服务：
```bash
make dev
```
