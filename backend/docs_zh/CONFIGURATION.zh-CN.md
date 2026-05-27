# 配置指南

本指南说明如何为你的环境配置 DeerFlow。

## 配置版本管理

`config.example.yaml` 包含一个 `config_version` 字段，用于跟踪 schema 变更。当示例版本高于你本地 `config.yaml` 的版本时，应用会在启动时发出警告：

```
WARNING - Your config.yaml (version 0) is outdated — the latest version is 1.
Run `make config-upgrade` to merge new fields into your config.
```

- 若配置中**缺少 `config_version`**，会按版本 0 处理。
- 运行 `make config-upgrade` 可自动合并缺失字段（保留现有值，并创建 `.bak` 备份）。
- 当配置 schema 变更时，请同步提升 `config.example.yaml` 中的 `config_version`。

## 配置分区

### 模型（Models）

配置可供 agent 使用的 LLM 模型：

```yaml
models:
  - name: gpt-4                    # Internal identifier
    display_name: GPT-4            # 人类可读名称
    use: langchain_openai:ChatOpenAI  # LangChain 类路径
    model: gpt-4                   # API 使用的模型标识
    api_key: $OPENAI_API_KEY       # API 密钥（建议使用环境变量）
    max_tokens: 4096               # 单次请求最大 token
    temperature: 0.7               # 采样温度
```

**支持的 Provider：**
- OpenAI（`langchain_openai:ChatOpenAI`）
- Anthropic（`langchain_anthropic:ChatAnthropic`）
- DeepSeek（`langchain_deepseek:ChatDeepSeek`）
- Claude Code OAuth（`deerflow.models.claude_provider:ClaudeChatModel`）
- Codex CLI（`deerflow.models.openai_codex_provider:CodexChatModel`）
- 任何兼容 LangChain 的 Provider

CLI 驱动 Provider 示例：

```yaml
models:
  - name: gpt-5.4
    display_name: GPT-5.4 (Codex CLI)
    use: deerflow.models.openai_codex_provider:CodexChatModel
    model: gpt-5.4
    supports_thinking: true
    supports_reasoning_effort: true

  - name: claude-sonnet-4.6
    display_name: Claude Sonnet 4.6 (Claude Code OAuth)
    use: deerflow.models.claude_provider:ClaudeChatModel
    model: claude-sonnet-4-6
    max_tokens: 4096
    supports_thinking: true
```

**CLI 驱动 Provider 的认证行为：**
- `CodexChatModel` 从 `~/.codex/auth.json` 加载 Codex CLI 认证信息
- Codex Responses 端点当前拒绝 `max_tokens` 和 `max_output_tokens`，因此 `CodexChatModel` 不暴露请求级 token 上限
- `ClaudeChatModel` 支持 `CLAUDE_CODE_OAUTH_TOKEN`、`ANTHROPIC_AUTH_TOKEN`、`CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`、`CLAUDE_CODE_CREDENTIALS_PATH` 或明文 `~/.claude/.credentials.json`
- 在 macOS 上，DeerFlow 不会自动探测 Keychain。需要时请使用 `scripts/export_claude_code_oauth.py` 显式导出 Claude Code 认证

若要通过 LangChain 使用 OpenAI 的 `/v1/responses` 端点，继续使用 `langchain_openai:ChatOpenAI` 并设置：

```yaml
models:
  - name: gpt-5-responses
    display_name: GPT-5 (Responses API)
    use: langchain_openai:ChatOpenAI
    model: gpt-5
    api_key: $OPENAI_API_KEY
    use_responses_api: true
    output_version: responses/v1
```

对于 OpenAI 兼容网关（例如 Novita 或 OpenRouter），仍使用 `langchain_openai:ChatOpenAI` 并设置 `base_url`：

```yaml
models:
  - name: novita-deepseek-v3.2
    display_name: Novita DeepSeek V3.2
    use: langchain_openai:ChatOpenAI
    model: deepseek/deepseek-v3.2
    api_key: $NOVITA_API_KEY
    base_url: https://api.novita.ai/openai
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled

  - name: minimax-m2.5
    display_name: MiniMax M2.5
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.5
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: true

  - name: minimax-m2.5-highspeed
    display_name: MiniMax M2.5 Highspeed
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.5-highspeed
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: true
  - name: openrouter-gemini-2.5-flash
    display_name: Gemini 2.5 Flash (OpenRouter)
    use: langchain_openai:ChatOpenAI
    model: google/gemini-2.5-flash-preview
    api_key: $OPENAI_API_KEY
    base_url: https://openrouter.ai/api/v1
```

如果你的 OpenRouter key 使用不同环境变量名，请将 `api_key` 显式指向该变量（例如 `api_key: $OPENROUTER_API_KEY`）。

**Thinking 模型：**
某些模型支持 “thinking” 模式以增强复杂推理：

```yaml
models:
  - name: deepseek-v3
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

**通过 OpenAI 兼容网关启用 Gemini thinking：**

当你通过 OpenAI 兼容代理（Vertex AI OpenAI compat endpoint、AI Studio 或第三方网关）启用 Gemini thinking 时，API 会在响应中的每个 tool-call 对象附带 `thought_signature`。后续请求在重放这些 assistant 消息时，**必须**把这些 signature 原样回传到 tool-call 条目中，否则 API 会返回：

```
HTTP 400 INVALID_ARGUMENT: function call `<tool>` in the N. content block is
missing a `thought_signature`.
```

标准 `langchain_openai:ChatOpenAI` 在序列化消息时会静默丢弃 `thought_signature`。请改用 `deerflow.models.patched_openai:PatchedChatOpenAI`——它会把 tool-call signatures（来源于 `AIMessage.additional_kwargs["tool_calls"]`）重新注入到每次出站 payload：

```yaml
models:
  - name: gemini-2.5-pro-thinking
    display_name: Gemini 2.5 Pro (Thinking)
    use: deerflow.models.patched_openai:PatchedChatOpenAI
    model: google/gemini-2.5-pro-preview   # model name as expected by your gateway
    api_key: $GEMINI_API_KEY
    base_url: https://<your-openai-compat-gateway>/v1
    max_tokens: 16384
    supports_thinking: true
    supports_vision: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

对于**不启用** thinking 的 Gemini（例如通过 OpenRouter 且未开启 thinking），直接使用 `langchain_openai:ChatOpenAI` 并设置 `supports_thinking: false` 即可，无需补丁。

### 工具分组（Tool Groups）

将工具组织为逻辑分组：

```yaml
tool_groups:
  - name: web          # Web 浏览与搜索
  - name: file:read    # 只读文件操作
  - name: file:write   # 文件写入操作
  - name: bash         # Shell 命令执行
```

### 工具（Tools）

配置 agent 可用的具体工具：

```yaml
tools:
  - name: web_search
    group: web
    use: deerflow.community.tavily.tools:web_search_tool
    max_results: 5
    # api_key: $TAVILY_API_KEY  # 可选
```

**内置工具：**
- `web_search` - Web 搜索（DuckDuckGo、Tavily、Exa、InfoQuest、Firecrawl）
- `web_fetch` - 抓取网页（Jina AI、Exa、InfoQuest、Firecrawl）
- `ls` - 列出目录内容
- `read_file` - 读取文件内容
- `write_file` - 写入文件内容
- `str_replace` - 文件内字符串替换
- `bash` - 执行 bash 命令

### 沙箱（Sandbox）

DeerFlow 支持多种沙箱执行模式。请在 `config.yaml` 中配置你偏好的模式：

**本地执行**（在宿主机上直接运行沙箱代码）：
```yaml
sandbox:
   use: deerflow.sandbox.local:LocalSandboxProvider # Local execution
   allow_host_bash: false # default; host bash is disabled unless explicitly re-enabled
```

**Docker 执行**（在隔离 Docker 容器中运行沙箱代码）：
```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider # Docker-based sandbox
```

**基于 Kubernetes 的 Docker 执行**（通过 provisioner 服务在 Kubernetes Pod 中运行沙箱代码）：

该模式会在你的**宿主机集群**上为每个沙箱创建独立 Kubernetes Pod。需要 Docker Desktop K8s、OrbStack 或类似本地 K8s 环境。

```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider
   provisioner_url: http://provisioner:8002
```

使用 Docker 开发模式（`make docker-start`）时，仅当该 provisioner 模式被配置时，DeerFlow 才会启动 `provisioner` 服务。在本地或普通 Docker 沙箱模式下，`provisioner` 会被跳过。

详细配置、前置条件与排障请参阅 [Provisioner Setup Guide](../../docker/provisioner/README.md)。

在本地执行和 Docker 隔离之间选择：

**选项 1：本地沙箱**（默认，配置更简单）：
```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
```

`allow_host_bash` 默认值刻意为 `false`。DeerFlow 本地沙箱是宿主机侧的便捷模式，不是安全的 shell 隔离边界。如果你需要 `bash`，优先使用 `AioSandboxProvider`。仅在完全可信的单用户本地流程中才建议设置 `allow_host_bash: true`。

**选项 2：Docker 沙箱**（隔离更好，更安全）：
```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  port: 8080
  auto_start: true
  container_prefix: deer-flow-sandbox

  # Optional: Additional mounts
  mounts:
    - host_path: /path/on/host
      container_path: /path/in/container
      read_only: false
```

当你配置 `sandbox.mounts` 时，DeerFlow 会把这些 `container_path` 写入 agent 提示词，以便 agent 能直接发现并操作挂载目录，而不是默认假设所有内容都位于 `/mnt/user-data` 下。

对于使用 localhost 的裸机 Docker 沙箱运行，DeerFlow 默认将沙箱 HTTP 端口绑定到 `127.0.0.1`，避免暴露到所有宿主机网卡。若采用 Docker-outside-of-Docker 并通过 `host.docker.internal` 连接，则为兼容性保留更宽泛绑定。若部署需要不同绑定地址，请显式设置 `DEER_FLOW_SANDBOX_BIND_HOST`。

### 技能（Skills）

为专门工作流配置技能目录：

```yaml
skills:
  # 宿主机路径（可选，默认：../skills）
  path: /custom/path/to/skills

  # 容器挂载路径（默认：/mnt/skills）
  container_path: /mnt/skills
```

**Skills 工作方式：**
- Skills 存储在 `deer-flow/skills/{public,custom}/`
- 每个 skill 都有一个包含元数据的 `SKILL.md`
- Skills 会被自动发现并加载
- 通过路径映射，在本地与 Docker 沙箱中都可用

**按 Agent 过滤 Skills：**
自定义 agent 可在其 `config.yaml`（位于 `workspace/agents/<agent_name>/config.yaml`）中定义 `skills` 字段，限制加载的技能：
- **省略或设为 `null`**：加载全局启用的全部技能（默认回退）。
- **`[]`（空列表）**：该 agent 禁用全部技能。
- **`["skill-name"]`**：仅加载显式指定技能。

### 标题生成

自动会话标题生成：

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # Use first model in list
```

### GitHub API Token（可选，用于 GitHub Deep Research Skill）

默认 GitHub API 限流较严格。若你需要频繁进行项目研究，建议配置具备只读权限的个人访问令牌（PAT）。

**配置步骤：**
1. 在 `.env` 文件中取消注释 `GITHUB_TOKEN` 并填入你的 personal access token
2. 重启 DeerFlow 服务使其生效

## 环境变量

DeerFlow 支持以 `$` 前缀进行环境变量替换：

```yaml
models:
  - api_key: $OPENAI_API_KEY  # 从环境变量读取
```

**常用环境变量：**
- `OPENAI_API_KEY` - OpenAI API 密钥
- `ANTHROPIC_API_KEY` - Anthropic API 密钥
- `DEEPSEEK_API_KEY` - DeepSeek API 密钥
- `NOVITA_API_KEY` - Novita API 密钥（OpenAI 兼容端点）
- `TAVILY_API_KEY` - Tavily 搜索 API 密钥
- `DEER_FLOW_PROJECT_ROOT` - 相对运行时路径所基于的项目根目录
- `DEER_FLOW_CONFIG_PATH` - 自定义配置文件路径
- `DEER_FLOW_EXTENSIONS_CONFIG_PATH` - 自定义 extensions 配置文件路径
- `DEER_FLOW_HOME` - 运行时状态目录（默认是项目根目录下的 `.deer-flow`）
- `DEER_FLOW_SKILLS_PATH` - 当 `skills.path` 省略时的技能目录
- `GATEWAY_ENABLE_DOCS` - 设为 `false` 可禁用 Swagger UI（`/docs`）、ReDoc（`/redoc`）与 OpenAPI schema（`/openapi.json`）端点（默认：`true`）

## 配置文件位置

配置文件应放在**项目根目录**（`deer-flow/config.yaml`）。当进程可能从其他工作目录启动时，请设置 `DEER_FLOW_PROJECT_ROOT`；或设置 `DEER_FLOW_CONFIG_PATH` 指向特定文件。

## 配置优先级

DeerFlow 按以下顺序查找配置：

1. 代码中 `config_path` 参数指定的路径
2. 环境变量 `DEER_FLOW_CONFIG_PATH` 指定路径
3. `DEER_FLOW_PROJECT_ROOT` 下的 `config.yaml`；若未设置 `DEER_FLOW_PROJECT_ROOT`，则使用当前工作目录下的 `config.yaml`
4. 为兼容单仓库结构保留的 legacy backend/repository-root 位置

## 最佳实践

1. **将 `config.yaml` 放在项目根目录** - 若运行时从其他位置启动，请设置 `DEER_FLOW_PROJECT_ROOT`
2. **不要提交 `config.yaml`** - 它已在 `.gitignore` 中
3. **用环境变量管理密钥** - 不要硬编码 API key
4. **保持 `config.example.yaml` 更新** - 记录所有新选项
5. **本地先验证配置变更** - 再部署
6. **生产环境使用 Docker 沙箱** - 隔离与安全性更好

## 故障排查

### “找不到配置文件（Config file not found）”
- 确认 `config.yaml` 位于**项目根目录**（`deer-flow/config.yaml`）
- 若运行时从项目根目录外启动，请设置 `DEER_FLOW_PROJECT_ROOT`
- 或设置环境变量 `DEER_FLOW_CONFIG_PATH` 到自定义位置

### “Invalid API key”
- 验证环境变量设置是否正确
- 检查环境变量引用是否使用了 `$` 前缀

### “Skills not loading”
- 检查 `deer-flow/skills/` 目录是否存在
- 确认技能包含有效的 `SKILL.md` 文件
- 若使用自定义路径，请检查 `skills.path` 或 `DEER_FLOW_SKILLS_PATH`

### “Docker 沙箱启动失败（Docker sandbox fails to start）”
- 确认 Docker 正在运行
- 检查 8080（或配置端口）是否可用
- 验证 Docker 镜像可访问

## 示例

完整配置示例请参阅 `config.example.yaml`。
