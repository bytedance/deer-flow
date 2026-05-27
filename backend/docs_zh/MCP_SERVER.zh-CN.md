# MCP（Model Context Protocol）配置

DeerFlow 支持可配置的 MCP Server 与技能（skills）来扩展能力，这些配置从项目根目录下专门的 `extensions_config.json` 文件中加载。

## 设置

1. 将 `extensions_config.example.json` 复制为项目根目录中的 `extensions_config.json`。
   ```bash
   # 复制示例配置
   cp extensions_config.example.json extensions_config.json
   ```

2. 将目标 MCP Server 或技能的 `"enabled"` 设为 `true` 以启用。
3. 按需配置每个 Server 的命令、参数与环境变量。
4. 重启应用以加载并注册 MCP 工具。

## 文件系统类 MCP Server

DeerFlow 已经提供了内置文件工具，用于线程作用域（thread-scoped）的工作区访问。
不要再为同一个 DeerFlow 工作区额外添加文件系统类 MCP Server。两套文件工具的路径语义不同，可能导致 LLM 的工具选择和文件访问行为不稳定。

DeerFlow 当前不会为文件系统类 Server 适配 MCP Roots 模式。具体来说，它不会发布每线程 MCP roots，也不会将 DeerFlow 沙箱路径（例如 `/mnt/user-data/...`）映射到 `@modelcontextprotocol/server-filesystem` 可接受的路径。处理 DeerFlow 工作区文件时，请使用 DeerFlow 内置文件工具。

## OAuth 支持（HTTP/SSE MCP Server）

对于 `http` 和 `sse` 类型的 MCP Server，DeerFlow 支持 OAuth token 获取与自动刷新。

- 支持的授权类型（grant）：`client_credentials`、`refresh_token`
- 在 `extensions_config.json` 中按 Server 配置 `oauth` 块
- 密钥建议通过环境变量提供（例如：`$MCP_OAUTH_CLIENT_SECRET`）

示例：

```json
{
   "mcpServers": {
      "secure-http-server": {
         "enabled": true,
         "type": "http",
         "url": "https://api.example.com/mcp",
         "oauth": {
            "enabled": true,
            "token_url": "https://auth.example.com/oauth/token",
            "grant_type": "client_credentials",
            "client_id": "$MCP_OAUTH_CLIENT_ID",
            "client_secret": "$MCP_OAUTH_CLIENT_SECRET",
            "scope": "mcp.read",
            "refresh_skew_seconds": 60
         }
      }
   }
}
```

## 自定义工具拦截器（interceptor）

你可以注册自定义 interceptor，使其在每次 MCP 工具调用前执行。这可用于注入每请求头（例如来自 LangGraph 执行上下文的用户鉴权 token）、日志记录或指标采集。

在 `extensions_config.json` 中通过 `mcpInterceptors` 字段声明 interceptor：

```json
{
  "mcpInterceptors": [
    "my_package.mcp.auth:build_auth_interceptor"
  ],
  "mcpServers": { ... }
}
```

每个条目都是 `module:variable` 格式的 Python 导入路径（由 `resolve_variable` 解析）。该变量必须是**无参 builder 函数**：返回一个与 `MultiServerMCPClient` 的 `tool_interceptors` 接口兼容的异步 interceptor；若返回 `None` 则跳过。

从 LangGraph 元数据注入鉴权头的 interceptor 示例：

```python
def build_auth_interceptor():
    async def interceptor(request, handler):
        from langgraph.config import get_config
        metadata = get_config().get("metadata", {})
        headers = dict(request.headers or {})
        if token := metadata.get("auth_token"):
            headers["X-Auth-Token"] = token
        return await handler(request.override(headers=headers))
    return interceptor
```

- 接受单个字符串值，并会规范化为仅含一个元素的列表。
- 无效路径或 builder 构建失败会记录 warning，但不会阻塞其他 interceptor。
- builder 的返回值必须是 `callable`；不可调用值会被跳过并记录 warning。

## 工作机制

MCP Server 会暴露工具，这些工具在运行时会被自动发现并集成进 DeerFlow 的 agent 系统。启用后，无需额外改动代码即可供 agent 使用。

## 能力示例

MCP Server 可提供以下能力：

- **数据库**（如 PostgreSQL）
- **外部 API**（如 GitHub、Brave Search）
- **浏览器自动化**（如 Puppeteer）
- **自定义 MCP Server 实现**

## 了解更多

Model Context Protocol 的详细文档请见：  
https://modelcontextprotocol.io
