# 【28】API路由系统详解

## 1. 模块全局定位

- **所属项目**：deer-flow
- **层级位置**：`backend/app/gateway/routers/`
- **核心作用**：提供FastAPI RESTful接口，连接前端与LangGraph后端
- **业务价值**：作为系统的"API网关层"，统一处理模型查询、技能管理、MCP配置、文件上传等业务逻辑
- **设计初衷**：设计用于解决"后端能力暴露"问题——通过标准HTTP接口暴露后端功能，支持前端集成与第三方调用

## 2. 路由架构

### 2.1 路由列表

| 路由前缀 | 文件 | 端点数 | 核心功能 |
|---------|------|--------|---------|
| `/api/models` | `models.py` | 2 | 模型列表、模型详情 |
| `/api/mcp` | `mcp.py` | 2 | MCP配置查询、更新 |
| `/api/skills` | `skills.py` | 4 | 技能列表、详情、更新、安装 |
| `/api/memory` | `memory.py` | 4 | 记忆数据、重载、配置、状态 |
| `/api/uploads` | `uploads.py` | 3 | 文件上传、列表、删除 |
| `/api/threads` | `threads.py` | 1 | 线程本地数据清理 |
| `/api/artifacts` | `artifacts.py` | 1 | 工件文件服务 |
| `/api/suggestions` | `suggestions.py` | 1 | 后续问题生成 |

### 2.2 代理配置

```python
# nginx配置
location /api/langgraph/ {
    proxy_pass http://localhost:2024/;
}

location /api/ {
    proxy_pass http://localhost:8001/;
}
```

**设计考量**：
- **统一入口**：nginx作为单一入口点，简化CORS与认证配置
- **路径区分**：LangGraph路径明确标识，避免路由冲突
- **环境隔离**：开发环境直连，生产环境通过代理

## 3. 核心路由详解

### 3.1 模型路由（/api/models）

**GET /api/models**：返回所有可用模型列表
```json
{
  "models": [
    {
      "name": "claude-sonnet-4.6",
      "display_name": "Claude Sonnet 4.6",
      "supports_thinking": true,
      "supports_vision": true
    }
  ]
}
```

**GET /api/models/{name}**：返回单个模型详情

**设计亮点**：
- **能力标志暴露**：`supports_thinking`、`supports_vision`帮助前端动态调整UI
- **过滤逻辑**：只返回已配置模型，避免暴露未初始化模型

### 3.2 MCP路由（/api/mcp）

**GET /api/mcp/config**：返回MCP服务器配置
**PUT /api/mcp/config**：更新MCP配置并保存到`extensions_config.json`

**设计亮点**：
- **跨进程同步**：Gateway写文件后，LangGraph通过mtime检测自动更新
- **技能配置保留**：更新MCP配置时保留现有技能配置
- **自动创建**：配置文件不存在时自动创建

### 3.3 技能路由（/api/skills）

**GET /api/skills**：返回所有技能列表
**GET /api/skills/{name}**：返回单个技能详情
**PUT /api/skills/{name}**：更新技能启用状态
**POST /api/skills/install**：安装.skill归档

**设计亮点**：
- **状态同步**：更新后立即重载配置，确保下次查询反映新状态
- **归档安装**：支持从上传的.skill文件安装新技能
- **虚拟路径解析**：从线程虚拟路径定位.skill文件

### 3.4 记忆路由（/api/memory）

**GET /api/memory**：返回记忆数据
**POST /api/memory/reload**：强制重载记忆文件
**GET /api/memory/config**：返回记忆配置
**GET /api/memory/status**：返回配置与数据状态

**设计亮点**：
- **按代理隔离**：支持`agent_name`参数实现多代理记忆隔离
- **状态组合**：`/status`端点同时返回配置与数据，减少前端请求

### 3.5 上传路由（/api/uploads）

**POST /api/threads/{id}/uploads**：上传文件（支持PDF/PPT/Excel/Word转换）
**GET /api/threads/{id}/uploads/list**：列出已上传文件
**DELETE /api/threads/{id}/uploads/{filename}**：删除文件

**设计亮点**：
- **文档转换**：使用`markitdown`自动转换Office文档为Markdown
- **线程隔离**：文件存储在`threads/{thread_id}/user-data/uploads/`
- **全有或全无**：拒绝目录上传，确保原子性

### 3.6 工件路由（/api/artifacts）

**GET /api/threads/{id}/artifacts/{path}**：返回工件文件内容

**设计亮点**：
- **虚拟路径映射**：`/mnt/user-data/outputs/{filename}`映射到实际文件
- **安全下载**：HTML/SVG等活跃内容强制下载，防止XSS
- **Range支持**：支持大文件分块下载

### 3.7 线程路由（/api/threads）

**DELETE /api/threads/{id}**：删除线程本地数据

**设计亮点**：
- **本地清理**：删除`.deer-flow/threads/{id}`目录
- **LangGraph分离**：需先调用LangGraph API删除线程，再清理本地数据

### 3.8 建议路由（/api/suggestions）

**POST /api/threads/{id}/suggestions**：生成后续问题建议

**设计亮点**：
- **内容规范化**：统一处理block/list模型响应格式
- **配置驱动**：使用配置的提示词模板生成建议

## 4. 错误处理

### 4.1 统一错误响应

```python
{
  "detail": "Error message describing what went wrong"
}
```

### 4.2 HTTP状态码

- **200**：成功
- **400**：请求错误（如无效参数）
- **404**：资源不存在
- **409**：冲突（如技能已存在）
- **500**：服务器错误

## 5. 认证与授权

**当前状态**：API未实现认证，所有端点公开访问

**未来扩展**：
- JWT令牌认证
- API Key认证
- OAuth集成

## 6. 性能优化

### 6.1 响应缓存

- 模型列表：配置驱动，变更频率低，适合缓存
- 技能列表：文件扫描，可缓存短时间
- MCP配置：mtime驱动，无需额外缓存

### 6.2 异步处理

- 文件上传：异步处理文档转换
- 技能安装：异步解压与验证
- 记忆更新：后台队列处理

## 7. 文档衔接

本篇完结，继续生成剩余文档。

**后续文档**：
- 部署与运维指南
- 完整项目索引
