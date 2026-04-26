# MCP (Model Context Protocol) 配置指南

===================
设计思路说明
===================

**为什么需要MCP**：
1. 扩展Agent能力：通过MCP服务器访问外部系统
2. 标准化接口：统一不同工具的接入方式
3. 插件化架构：动态加载工具，无需修改核心代码

**核心设计原则**：
- 配置驱动：通过JSON配置管理MCP服务器
- 多传输支持：stdio/sse/http适应不同场景
- OAuth集成：支持需要认证的企业MCP服务器

**为什么使用extensions_config.json**：
- 集中管理所有扩展（MCP和Skills）
- 支持热重载，修改后无需重启
- 便于版本控制和团队协作

DeerFlow 支持可配置的 MCP 服务器和技能来扩展其能力，这些从项目根目录的专用 `extensions_config.json` 文件加载。

## 设置

1. 将 `extensions_config.example.json` 复制到项目根目录的 `extensions_config.json`。
   ```bash
   # 复制示例配置
   cp extensions_config.example.json extensions_config.json
   ```

2. 通过设置 `"enabled": true` 启用所需的 MCP 服务器或技能。

3. 根据需要配置每个服务器的命令、参数和环境变量。

4. 重启应用以加载并注册 MCP 工具。

**为什么需要复制配置文件**：
- 避免将本地配置提交到git
- 保留示例作为参考
- 支持多环境配置

## OAuth 支持（HTTP/SSE MCP 服务器）

对于 `http` 和 `sse` MCP 服务器，DeerFlow 支持 OAuth token 获取和自动 token 刷新。

- 支持的授权类型：`client_credentials`、`refresh_token`
- 在 `extensions_config.json` 中配置每个服务器的 `oauth` 块
- 密钥应通过环境变量提供（例如：`$MCP_OAUTH_CLIENT_SECRET`）

**为什么需要OAuth支持**：
- 企业MCP服务器通常需要认证
- Token会过期，需要自动刷新
- 支持多种OAuth流程

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

**为什么使用环境变量引用**：
- 避免在配置文件中硬编码密钥
- 支持多环境部署
- 提高安全性

## 工作原理

MCP 服务器暴露工具，这些工具在运行时自动发现并集成到 DeerFlow 的 agent 系统中。一旦启用，这些工具就可以被 agent 使用，而无需额外的代码更改。

**为什么是自动发现**：
- 降低集成成本
- 支持动态加载
- 无需修改核心代码

## 示例能力

MCP 服务器可以提供访问：

- **文件系统**
- **数据库**（例如 PostgreSQL）
- **外部 API**（例如 GitHub、Brave Search）
- **浏览器自动化**（例如 Puppeteer）
- **自定义 MCP 服务器实现**

**为什么支持这些能力**：
- 满足常见的企业需求
- 覆盖主要的数据源
- 支持自定义扩展

## 了解更多

关于 Model Context Protocol 的详细文档，请访问：
https://modelcontextprotocol.io

**为什么链接到官方文档**：
- 协议不断演进
- 提供最新的规范
- 支持社区贡献
