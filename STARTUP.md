# DeerFlow 启动指南

本文档介绍如何在本地运行 DeerFlow 项目。

## 环境要求

- Python 3.12+
- Node.js 18+
- pnpm
- uv (Python 包管理器)

## 配置步骤

### 1. 克隆项目

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
```

### 2. 安装依赖

**后端依赖**：
```bash
cd backend
uv sync
```

**前端依赖**：
```bash
cd frontend
pnpm install
```

### 3. 生成配置文件

```bash
python ./scripts/configure.py
```

### 4. 配置模型

编辑生成的 `config.yaml` 文件，配置你的 LLM 模型。例如使用 SiliconFlow 的 DeepSeek-V3.2：

```yaml
models:
  - name: deepseek-v3.2
    display_name: DeepSeek V3.2 (SiliconFlow)
    use: langchain_openai:ChatOpenAI
    model: deepseek-ai/DeepSeek-V3.2
    api_key: your-api-key
    base_url: https://api.siliconflow.cn/v1
    max_tokens: 4096
    temperature: 0.7
    supports_thinking: true
    supports_vision: false
```

### 5. 配置前端环境变量

编辑 `frontend/.env` 文件：

```env
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:2024
```

## 启动服务

DeerFlow 需要启动三个服务：LangGraph Server、Gateway API 和 Frontend。

### 启动 LangGraph Server（终端 1）

```bash
cd backend
uv run langgraph dev --allow-blocking
```

### 启动 Gateway API（终端 2）

```bash
cd backend
uv run uvicorn app.gateway.app:app --reload --host 0.0.0.0 --port 8001
```

### 启动 Frontend（终端 3）

```bash
cd frontend
pnpm run dev
```

## 访问应用

启动完成后，访问：**http://localhost:3000**

## Docker 启动方式（推荐）

如果想要更简单的启动方式，可以使用 Docker：

```bash
make up
```

这将启动所有服务，包括 nginx 反向代理，访问 **http://localhost:2026**。

## 常见问题

### 1. LangGraph 崩溃并出现 "Blocking call to os.getcwd" 错误

解决方案：使用 `--allow-blocking` 参数启动 LangGraph：

```bash
uv run langgraph dev --allow-blocking
```

### 2. Gateway API 连接失败

确保 Gateway 运行在正确的端口（8001），并配置正确的前端环境变量。

### 3. 浏览器显示 "Failed to fetch"

- 清除浏览器缓存
- 使用隐私模式
- 或强制刷新（Ctrl + Shift + R）
