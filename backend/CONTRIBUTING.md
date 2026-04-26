# 贡献 DeerFlow 后端

感谢您对 DeerFlow 贡献的兴趣！本文档提供了为后端代码库做贡献的指南和说明。

---

## 目录

- [快速开始](#快速开始)
- [开发设置](#开发设置)
- [项目结构](#项目结构)
- [代码风格](#代码风格)
- [进行更改](#进行更改)
- [测试](#测试)
- [拉取请求流程](#拉取请求流程)
- [架构指南](#架构指南)

---

## 快速开始

### 前置要求

- Python 3.12 或更高版本
- [uv](https://docs.astral.sh/uv/) 包管理器
- Git
- Docker（可选，用于 Docker 沙箱测试）

### Fork 和克隆

1. 在 GitHub 上 Fork 仓库
2. 本地克隆您的 fork：
   ```bash
   git clone https://github.com/YOUR_USERNAME/deer-flow.git
   cd deer-flow
   ```

---

## 开发设置

### 安装依赖

```bash
# 从项目根目录
cp config.example.yaml config.yaml

# 安装后端依赖
cd backend
make install
```

### 配置环境

为测试设置您的 API keys：

```bash
export OPENAI_API_KEY="your-api-key"
# 根据需要添加其他 keys
```

### 运行开发服务器

```bash
# 终端 1：LangGraph 服务器
make dev

# 终端 2：Gateway API
make gateway
```

---

## 项目结构

```
backend/src/
├── agents/                  # 代理系统
│   ├── lead_agent/         # 主代理实现
│   │   └── agent.py        # 代理工厂和创建
│   ├── middlewares/        # 代理中间件
│   │   ├── thread_data_middleware.py
│   │   ├── sandbox_middleware.py
│   │   ├── title_middleware.py
│   │   ├── uploads_middleware.py
│   │   ├── view_image_middleware.py
│   │   └── clarification_middleware.py
│   └── thread_state.py     # 线程状态定义
│
├── gateway/                 # FastAPI Gateway
│   ├── app.py              # FastAPI 应用
│   └── routers/            # 路由处理器
│       ├── models.py       # /api/models 端点
│       ├── mcp.py          # /api/mcp 端点
│       ├── skills.py       # /api/skills 端点
│       ├── artifacts.py    # /api/threads/.../artifacts
│       └── uploads.py      # /api/threads/.../uploads
│
├── sandbox/                 # 沙箱执行
│   ├── __init__.py         # 沙箱接口
│   ├── local.py            # 本地沙箱提供者
│   └── tools.py            # 沙箱工具（bash、文件操作）
│
├── tools/                   # 代理工具
│   └── builtins/           # 内置工具
│       ├── present_file_tool.py
│       ├── ask_clarification_tool.py
│       └── view_image_tool.py
│
├── mcp/                     # MCP 集成
│   └── manager.py          # MCP 服务器管理
│
├── models/                  # 模型系统
│   └── factory.py          # 模型工厂
│
├── skills/                  # 技能系统
│   └── loader.py           # 技能加载器
│
├── config/                  # 配置
│   ├── app_config.py       # 主应用配置
│   ├── extensions_config.py # 扩展配置
│   └── summarization_config.py
│
├── community/               # 社区工具
│   ├── tavily/             # Tavily 网络搜索
│   ├── jina/               # Jina 网络获取
│   ├── firecrawl/          # Firecrawl 爬取
│   └── aio_sandbox/        # Docker 沙箱
│
├── reflection/              # 动态加载
│   └── __init__.py         # 模块解析
│
└── utils/                   # 工具
    └── __init__.py
```

---

## 代码风格

### Lint 和格式化

我们使用 `ruff` 进行 lint 和格式化：

```bash
# 检查问题
make lint

# 自动修复和格式化
make format
```

### 风格指南

- **行长度**：最多 240 字符
- **Python 版本**：允许 3.12+ 特性
- **类型提示**：为函数签名使用类型提示
- **引号**：字符串使用双引号
- **缩进**：4 个空格（无制表符）
- **导入**：按标准库、第三方、本地分组

### 文档字符串

为公共函数和类使用文档字符串：

```python
def create_chat_model(name: str, thinking_enabled: bool = False) -> BaseChatModel:
    """从配置创建聊天模型实例。

    Args:
        name: 在 config.yaml 中定义的模型名称
        thinking_enabled: 是否启用扩展思考

    Returns:
        配置好的 LangChain 聊天模型实例

    Raises:
        ValueError: 如果在配置中找不到模型名称
    """
    ...
```

---

## 进行更改

### 分支命名

使用描述性分支名称：

- `feature/add-new-tool` - 新功能
- `fix/sandbox-timeout` - 错误修复
- `docs/update-readme` - 文档
- `refactor/config-system` - 代码重构

### 提交消息

编写清晰、简洁的提交消息：

```
feat: 添加对 Claude 3.5 模型的支持

- 在 config.yaml 中添加模型配置
- 更新模型工厂以处理 Claude 特定设置
- 为新模型添加测试
```

前缀类型：
- `feat:` - 新功能
- `fix:` - 错误修复
- `docs:` - 文档
- `refactor:` - 代码重构
- `test:` - 测试
- `chore:` - 构建/配置更改

---

## 测试

### 运行测试

```bash
uv run pytest
```

### 编写测试

在 `tests/` 目录中放置测试，镜像源代码结构：

```
tests/
├── test_models/
│   └── test_factory.py
├── test_sandbox/
│   └── test_local.py
└── test_gateway/
    └── test_models_router.py
```

示例测试：

```python
import pytest
from deerflow.models.factory import create_chat_model

def test_create_chat_model_with_valid_name():
    """测试有效的模型名称创建模型实例。"""
    model = create_chat_model("gpt-4")
    assert model is not None

def test_create_chat_model_with_invalid_name():
    """测试无效的模型名称引发 ValueError。"""
    with pytest.raises(ValueError):
        create_chat_model("nonexistent-model")
```

---

## 拉取请求流程

### 提交前

1. **确保测试通过**：`uv run pytest`
2. **运行 linter**：`make lint`
3. **格式化代码**：`make format`
4. **更新文档**（如需要）

### PR 描述

在您的 PR 描述中包含：

- **What**：更改的简要描述
- **Why**：更改的动机
- **How**：实现方法
- **Testing**：如何测试这些更改

### 审查流程

1. 提交带有清晰描述的 PR
2. 处理审查反馈
3. 确保 CI 通过
4. 维护者将在批准后合并

---

## 架构指南

### 添加新工具

1. 在 `packages/harness/deerflow/tools/builtins/` 或 `packages/harness/deerflow/community/` 中创建工具：

```python
# packages/harness/deerflow/tools/builtins/my_tool.py
from langchain_core.tools import tool

@tool
def my_tool(param: str) -> str:
    """代理的工具描述。

    Args:
        param: 参数描述

    Returns:
        返回值描述
    """
    return f"Result: {param}"
```

2. 在 `config.yaml` 中注册：

```yaml
tools:
  - name: my_tool
    group: my_group
    use: deerflow.tools.builtins.my_tool:my_tool
```

### 添加新中间件

1. 在 `packages/harness/deerflow/agents/middlewares/` 中创建中间件：

```python
# packages/harness/deerflow/agents/middlewares/my_middleware.py
from langchain.agents.middleware import BaseMiddleware
from langchain_core.runnables import RunnableConfig

class MyMiddleware(BaseMiddleware):
    """中间件描述。"""

    def transform_state(self, state: dict, config: RunnableConfig) -> dict:
        """在代理执行前转换状态。"""
        # 根据需要修改状态
        return state
```

2. 在 `packages/harness/deerflow/agents/lead_agent/agent.py` 中注册：

```python
middlewares = [
    ThreadDataMiddleware(),
    SandboxMiddleware(),
    MyMiddleware(),  # 添加您的中间件
    TitleMiddleware(),
    ClarificationMiddleware(),
]
```

### 添加新 API 端点

1. 在 `app/gateway/routers/` 中创建路由器：

```python
# app/gateway/routers/my_router.py
from fastapi import APIRouter

router = APIRouter(prefix="/my-endpoint", tags=["my-endpoint"])

@router.get("/")
async def get_items():
    """获取所有项目。"""
    return {"items": []}

@router.post("/")
async def create_item(data: dict):
    """创建新项目。"""
    return {"created": data}
```

2. 在 `app/gateway/app.py` 中注册：

```python
from app.gateway.routers import my_router

app.include_router(my_router.router)
```

### 配置更改

添加新配置选项时：

1. 在 `packages/harness/deerflow/config/app_config.py` 中更新新字段
2. 在 `config.example.yaml` 中添加默认值
3. 在 `docs/CONFIGURATION.md` 中记录

### MCP 服务器集成

添加对新 MCP 服务器的支持：

1. 在 `extensions_config.json` 中添加配置：

```json
{
  "mcpServers": {
    "my-server": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@my-org/mcp-server"],
      "description": "My MCP Server"
    }
  }
}
```

2. 使用新服务器更新 `extensions_config.example.json`

### 技能开发

创建新技能：

1. 在 `skills/public/` 或 `skills/custom/` 中创建目录：

```
skills/public/my-skill/
└── SKILL.md
```

2. 编写带有 YAML front matter 的 `SKILL.md`：

```markdown
---
name: My Skill
description: 这个技能的作用
license: MIT
allowed-tools:
  - read_file
  - write_file
  - bash
---

# My Skill

启用此技能时代理的指令...
```

---

## 有问题？

如果您对贡献有疑问：

1. 查看 `docs/` 中的现有文档
2. 在 GitHub 上查找类似的问题或 PR
3. 在 GitHub 上打开讨论或问题

感谢您为 DeerFlow 做出贡献！
