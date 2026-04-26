# 配置指南

本指南解释如何为您的环境配置DeerFlow。

## 配置版本管理

===================
设计思路说明
===================

**为什么需要配置版本管理**：
`config.example.yaml`包含一个`config_version`字段，用于跟踪schema更改。当示例版本高于本地`config.yaml`时，应用程序会发出启动警告：

```
WARNING - 您的config.yaml（版本0）已过时 — 最新版本为1。
运行`make config-upgrade`以将新字段合并到您的配置中。
```

**设计决策**：
- **缺失的`config_version`**被视为版本0
- 运行`make config-upgrade`自动合并缺失字段（保留现有值，创建`.bak`备份）
- 更改配置schema时，在`config.example.yaml`中增加`config_version`

**架构优势**：
- **向后兼容**：自动升级，用户无需手动合并配置
- **安全升级**：创建备份，避免数据丢失
- **清晰提示**：警告消息明确告知用户需要升级

---

## 配置章节

### 模型配置

为代理配置可用的LLM模型：

```yaml
models:
  - name: gpt-4                    # 内部标识符
    display_name: GPT-4            # 人类可读名称
    use: langchain_openai:ChatOpenAI  # LangChain类路径
    model: gpt-4                   # API的模型标识符
    api_key: $OPENAI_API_KEY       # API密钥（使用环境变量）
    max_tokens: 4096               # 每个请求的最大token数
    temperature: 0.7               # 采样温度
```

**支持的提供商**：
- OpenAI (`langchain_openai:ChatOpenAI`)
- Anthropic (`langchain_anthropic:ChatAnthropic`)
- DeepSeek (`langchain_deepseek:ChatDeepSeek`)
- Claude Code OAuth (`deerflow.models.claude_provider:ClaudeChatModel`)
- Codex CLI (`deerflow.models.openai_codex_provider:CodexChatModel`)
- 任何LangChain兼容的提供商

CLI支持的提供商示例：

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

**CLI支持的提供商的认证行为**：
- `CodexChatModel`从`~/.codex/auth.json`加载Codex CLI认证
- Codex响应端点当前拒绝`max_tokens`和`max_output_tokens`，因此`CodexChatModel`不暴露请求级别的token上限
- `ClaudeChatModel`接受`CLAUDE_CODE_OAUTH_TOKEN`、`ANTHROPIC_AUTH_TOKEN`、`CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`、`CLAUDE_CODE_CREDENTIALS_PATH`或明文`~/.claude/.credentials.json`
- 在macOS上，DeerFlow不会自动探测Keychain。需要时使用`scripts/export_claude_code_oauth.py`显式导出Claude Code认证

要使用OpenAI的`/v1/responses`端点和LangChain，继续使用`langchain_openai:ChatOpenAI`并设置：

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

对于OpenAI兼容的网关（例如Novita或OpenRouter），继续使用`langchain_openai:ChatOpenAI`并设置`base_url`：

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
    temperature: 1.0  # MiniMax要求temperature在(0.0, 1.0]范围内
    supports_vision: true

  - name: minimax-m2.5-highspeed
    display_name: MiniMax M2.5 Highspeed
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.5-highspeed
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax要求temperature在(0.0, 1.0]范围内
    supports_vision: true
  - name: openrouter-gemini-2.5-flash
    display_name: Gemini 2.5 Flash (OpenRouter)
    use: langchain_openai:ChatOpenAI
    model: google/gemini-2.5-flash-preview
    api_key: $OPENAI_API_KEY
    base_url: https://openrouter.ai/api/v1
```

如果您的OpenRouter密钥位于不同的环境变量名称，请明确将`api_key`指向该变量（例如`api_key: $OPENROUTER_API_KEY`）。

**思考模型**：
某些模型支持"思考"模式进行复杂推理：

```yaml
models:
  - name: deepseek-v3
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

**通过OpenAI兼容网关启用思考的Gemini**：

当通过OpenAI兼容代理（Vertex AI OpenAI兼容端点、AI Studio或第三方网关）路由Gemini并启用思考时，API会在响应中返回的每个tool-call对象上附加`thought_signature`。每个重放这些助手消息的后续请求**必须**在tool-call条目上回显这些签名，否则API返回：

```
HTTP 400 INVALID_ARGUMENT: function call `<tool>` in the N. content block is
missing a `thought_signature`.
```

标准的`langchain_openai:ChatOpenAI`在序列化消息时静默删除`thought_signature`。改用`deerflow.models.patched_openai:PatchedChatOpenAI` - 它将tool-call签名（源自`AIMessage.additional_kwargs["tool_calls"]`）重新注入到每个传出负载中：

```yaml
models:
  - name: gemini-2.5-pro-thinking
    display_name: Gemini 2.5 Pro (Thinking)
    use: deerflow.models.patched_openai:PatchedChatOpenAI
    model: google/gemini-2.5-pro-preview   # 网关期望的模型名称
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

对于**不**启用思考访问的Gemini（例如，通过未激活思考的OpenRouter），普通的`langchain_openai:ChatOpenAI`和`supports_thinking: false`就足够了，不需要补丁。

### 工具组

将工具组织成逻辑组：

```yaml
tool_groups:
  - name: web          # Web浏览和搜索
  - name: file:read    # 只读文件操作
  - name: file:write   # 写文件操作
  - name: bash         # Shell命令执行
```

### 工具配置

配置代理可用的特定工具：

```yaml
tools:
  - name: web_search
    group: web
    use: deerflow.community.tavily.tools:web_search_tool
    max_results: 5
    # api_key: $TAVILY_API_KEY  # 可选
```

**内置工具**：
- `web_search` - 搜索网页（Tavily）
- `web_fetch` - 获取网页（Jina AI）
- `ls` - 列出目录内容
- `read_file` - 读取文件内容
- `write_file` - 写入文件内容
- `str_replace` - 文件中的字符串替换
- `bash` - 执行bash命令

### 沙箱配置

DeerFlow支持多种沙箱执行模式。在`config.yaml`中配置您的首选模式：

**本地执行**（直接在主机上运行沙箱代码）：
```yaml
sandbox:
   use: deerflow.sandbox.local:LocalSandboxProvider # 本地执行
   allow_host_bash: false # 默认；除非明确重新启用，否则禁用主机bash
```

**Docker执行**（在隔离的Docker容器中运行沙箱代码）：
```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider # 基于Docker的沙箱
```

**通过Kubernetes的Docker执行**（通过provisioner服务在Kubernetes pod中运行沙箱代码）：

此模式在**主机集群**上的隔离Kubernetes Pod中运行每个沙箱。需要Docker Desktop K8s、OrbStack或类似的本地K8s设置。

```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider
   provisioner_url: http://provisioner:8002
```

使用Docker开发（`make docker-start`）时，只有配置了此provisioner模式，DeerFlow才启动`provisioner`服务。在本地或纯Docker沙箱模式下，跳过`provisioner`。

有关详细配置、先决条件和故障排除，请参阅[Provisioner设置指南](../../docker/provisioner/README.md)。

在本地执行或基于Docker的隔离之间选择：

**选项1：本地沙箱**（默认，设置更简单）：
```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
```

`allow_host_bash`默认为`false`。DeerFlow的本地沙箱是主机端便利模式，不是安全的shell隔离边界。如果您需要`bash`，更倾向于`AioSandboxProvider`。仅对完全受信任的单用户本地工作流设置`allow_host_bash: true`。

**选项2：Docker沙箱**（隔离，更安全）：
```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  port: 8080
  auto_start: true
  container_prefix: deer-flow-sandbox

  # 可选：额外的挂载
  mounts:
    - host_path: /host/path
      container_path: /container/path
      read_only: false
```

### 技能配置

为专门的工作流配置技能目录：

```yaml
skills:
  # 主机路径（可选，默认：../skills）
  path: /custom/path/to/skills

  # 容器挂载路径（默认：/mnt/skills）
  container_path: /mnt/skills
```

**技能工作原理**：
- 技能存储在`deer-flow/skills/{public,custom}/`中
- 每个技能都有带有元数据的`SKILL.md`文件
- 技能自动发现和加载
- 通过路径映射在本地和Docker沙箱中都可用

### 标题生成

自动对话标题生成：

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # 使用列表中的第一个模型
```

### GitHub API令牌（可选，用于GitHub深度研究技能）

默认的GitHub API速率限制相当严格。对于频繁的项目研究，我们建议配置具有只读权限的个人访问令牌（PAT）。

**配置步骤**：
1. 在`.env`文件中取消注释`GITHUB_TOKEN`行并添加您的个人访问令牌
2. 重启DeerFlow服务以应用更改

## 环境变量

DeerFlow支持使用`$`前缀进行环境变量替换：

```yaml
models:
  - api_key: $OPENAI_API_KEY  # 从环境读取
```

**常用环境变量**：
- `OPENAI_API_KEY` - OpenAI API密钥
- `ANTHROPIC_API_KEY` - Anthropic API密钥
- `DEEPSEEK_API_KEY` - DeepSeek API密钥
- `NOVITA_API_KEY` - Novita API密钥（OpenAI兼容端点）
- `TAVILY_API_KEY` - Tavily搜索API密钥
- `DEER_FLOW_CONFIG_PATH` - 自定义配置文件路径

## 配置位置

配置文件应放置在**项目根目录**（`deer-flow/config.yaml`）中，而非backend目录。

## 配置优先级

DeerFlow按以下顺序搜索配置：

1. 代码中通过`config_path`参数指定的路径
2. `DEER_FLOW_CONFIG_PATH`环境变量的路径
3. 当前工作目录中的`config.yaml`（通常是运行时的`backend/`）
4. 父目录中的`config.yaml`（项目根目录：`deer-flow/`）

## 最佳实践

1. **将`config.yaml`放在项目根目录** - 而非`backend/`目录
2. **永远不要提交`config.yaml`** - 它已在`.gitignore`中
3. **为机密使用环境变量** - 不要硬编码API密钥
4. **保持`config.example.yaml`更新** - 记录所有新选项
5. **在本地测试配置更改** - 部署前
6. **为生产使用Docker沙箱** - 更好的隔离和安全性

## 故障排除

### "找不到配置文件"
- 确保`config.yaml`存在于**项目根目录**（`deer-flow/config.yaml`）
- 后端默认搜索父目录，因此首选根目录位置
- 或者，将`DEER_FLOW_CONFIG_PATH`环境变量设置为自定义位置

### "无效的API密钥"
- 验证环境变量设置正确
- 检查是否对env var引用使用了`$`前缀

### "技能未加载"
- 检查`deer-flow/skills/`目录是否存在
- 验证技能具有有效的`SKILL.md`文件
- 如果使用自定义路径，检查`skills.path`配置

### "Docker沙箱启动失败"
- 确保Docker正在运行
- 检查端口8080（或配置的端口）是否可用
- 验证Docker镜像可访问

## 示例

有关所有配置选项的完整示例，请参阅`config.example.yaml`。
