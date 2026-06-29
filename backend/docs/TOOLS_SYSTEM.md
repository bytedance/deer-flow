# 工具系统 (Tool System)

> 关于 Tool 与 Skill 的职责边界和选择标准，参见 [TOOL_VS_SKILL.md](TOOL_VS_SKILL.md)。

`get_available_tools(groups, include_mcp, model_name, subagent_enabled)` 组装工具集。

## 工具分类

```
┌─────────────────────────────────────────────────────────────────┐
│                      配置定义工具                                  │
│  来源: config.yaml via resolve_variable()                        │
└─────────────────────────────────────────────────────────────────┘
                              +
┌─────────────────────────────────────────────────────────────────┐
│                      MCP 工具                                    │
│  来源: 启用的 MCP 服务器（懒加载，mtime 缓存失效）                   │
└─────────────────────────────────────────────────────────────────┘
                              +
┌─────────────────────────────────────────────────────────────────┐
│                      内置工具                                    │
│  present_files, ask_clarification, view_image, http_connector,   │
│  setup_agent, update_agent, closure_ticket_*                     │
└─────────────────────────────────────────────────────────────────┘
                              +
┌─────────────────────────────────────────────────────────────────┐
│                      子代理工具 (可选)                             │
│  task - 委派给子代理                                              │
└─────────────────────────────────────────────────────────────────┘
```

## 内置工具详解

### 文件与交互

| 工具 | 职责 | 特殊行为 |
|------|------|----------|
| `present_files` | 使输出文件对用户可见 | 仅限 `/mnt/user-data/outputs` |
| `ask_clarification` | 请求澄清 | 被 ClarificationMiddleware 拦截 → 中断 |
| `view_image` | 读取图片为 base64 | 仅当模型支持视觉时添加 |

### HTTP 连接器

**`http_connector`** - 调用预配置的 HTTP 端点
- 异步，带重试/截断/结构化日志
- 配置驱动: `config.yaml` 的 `http_connectors` 部分
- 按 `tenant_id` 键控
- 详见 [HTTP_CONNECTORS.md](HTTP_CONNECTORS.md)

### Agent 管理

| 工具 | 职责 | 绑定条件 |
|------|------|----------|
| `setup_agent` | 持久化新自定义 Agent 的 `SOUL.md` 和 `config.yaml` | `is_bootstrap=True` |
| `update_agent` | 持久化当前 Agent 的自更新 | `agent_name` 已设置且 `is_bootstrap=False` |

### 闭环工单

| 工具 | 职责 | 特殊行为 |
|------|------|----------|
| `create_closure_ticket` | 创建闭环工单 | `tenant_id` / `actor_id` 来自 runnable config |
| `list_closure_tickets` | 列出工单 | 同上 |
| `update_closure_ticket` | 更新工单 | 拒绝 `status` 写入（`STATUS_FORBIDDEN`） |
| `close_closure_ticket` | 关闭工单 | 需要 `closure:verify` 权限 |

**状态转换**: 状态移动通过 `close_closure_ticket`（验证关闭 / 拒绝）或 `/api/closure/tickets/{id}/transition` 路由。

**权限**: `close_closure_ticket` 需要 `closure:verify`，授予 `is_superadmin` / `is_tenant_admin` 主体。

## 子代理工具

**`task`** - 委派任务给子代理

参数:
- `description` - 任务描述
- `prompt` - 详细提示
- `subagent_type` - 子代理类型
- `max_turns` - 最大轮次

条件: `subagent_enabled = True`

## 社区工具 (`packages/harness/deerflow/community/`)

| 目录 | 工具 | 说明 |
|------|------|------|
| `tavily/` | `web_search`, `web_fetch` | Web 搜索（默认 5 结果）和抓取（4KB 限制） |
| `jina_ai/` | `web_fetch` | 通过 Jina reader API 抓取，带可读性提取 |
| `firecrawl/` | `web_scrape` | 通过 Firecrawl API 抓取 |
| `image_search/` | `image_search` | 通过 DuckDuckGo 图片搜索 |

## ACP Agent 工具

**`invoke_acp_agent`** - 调用外部 ACP 兼容 Agent

配置: `config.yaml` 中的 ACP Agent

**要求**:
- ACP 启动器必须是真正的 ACP 适配器
- 标准 `codex` CLI 不兼容 ACP；配置包装器如 `npx -y @zed-industries/codex-acp` 或安装的 `codex-acp` 二进制
- 缺失 ACP 可执行文件返回可操作错误消息而非原始 `[Errno 2]`

**工作区**: 每个线程使用独立工作区 `{base_dir}/users/{user_id}/threads/{thread_id}/acp-workspace/`
- Lead agent 通过虚拟路径 `/mnt/acp-workspace/`（只读）访问
- Docker 沙箱模式: 目录卷挂载到容器 `/mnt/acp-workspace`（只读）
- 本地沙箱模式: `tools.py` 处理路径转换

## 工具合并逻辑

`get_available_tools()` 在 `deerflow/tools/tools.py` 中:

1. **配置解析**: 从 `config.yaml` 通过 `resolve_variable()` 解析
2. **MCP 工具**: 从启用的 MCP 服务器加载（懒初始化，mtime 缓存失效）
3. **内置工具**: 始终包含（部分条件性）
4. **Tenant MCP 合并**: 如果提供 `tenant_mcp_configs`，tenant 工具替换同 server 名前缀的全局工具
5. **Agent 过滤**: 应用 Agent 级 `mcp_servers` 过滤器

## 配置示例

### config.yaml

```yaml
tools:
  - use: deerflow.community.tavily:web_search
    group: web
    config:
      api_key: $TAVILY_API_KEY
      max_results: 5
  
  - use: deerflow.community.jina_ai:web_fetch
    group: web
    config:
      api_key: $JINA_API_KEY

http_connectors:
  default:
    - name: ins_api
      url: https://ins.example.com/api
      method: POST
      auth_type: bearer
      auth_token_env: $INS_API_TOKEN
      timeout_seconds: 30
```

### extensions_config.json

```json
{
  "mcpServers": {
    "filesystem": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
```

## 工具组 (Tool Groups)

`config.yaml` 中的 `tool_groups` 定义逻辑分组:

```yaml
tool_groups:
  - name: web
    description: Web 搜索和抓取工具
  - name: sandbox
    description: 沙箱文件操作工具
  - name: report
    description: 报告生成工具
```

Agent 配置中通过 `tool_groups` 字段选择启用的组:

```yaml
# Agent config.yaml
tool_groups:
  - web
  - sandbox
```

## 最佳实践

### 添加工具

1. **内置工具**: 在 `packages/harness/deerflow/tools/builtins/` 创建
2. **社区工具**: 在 `packages/harness/deerflow/community/` 创建
3. **MCP 工具**: 配置 `extensions_config.json`
4. **配置工具**: 在 `config.yaml` 添加 `tools` 条目

### 工具命名

- 使用清晰的动词-名词模式: `web_search`, `read_file`, `create_ticket`
- 避免通用名称: `process`, `handle`, `do_something`

### 错误处理

- 工具应返回结构化错误而非抛出异常
- 使用 `ToolErrorHandlingMiddleware` 捕获未处理异常
- 提供可操作的错误消息
