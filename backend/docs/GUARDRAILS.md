# Guardrails: 工具调用前的授权层

===================
设计思路说明
===================

**为什么需要Guardrails（防护栏）**：
1. 沙箱提供进程隔离，但不能防止语义上的危险操作
2. 人工确认（ask_clarification）需要每步都介入，不适合自动化流程
3. Guardrails提供确定性的、基于策略的授权，无需人工干预

**核心设计原则**：
- 前置拦截：在工具调用执行前进行评估
- 策略驱动：基于配置的策略决定允许或拒绝
- 可插拔：支持多种Provider实现
- 失败安全：默认阻止不确定的操作

**为什么放在中间件链的第5位**：
1. 前面的中间件准备上下文（ThreadData、Uploads、Sandbox）
2. 后面的中间件处理工具调用的结果
3. Guardrails需要在工具实际执行前做决策

> **背景**：[Issue #1213](https://github.com/bytedance/deer-flow/issues/1213) — DeerFlow 有 Docker 沙箱和人工确认（`ask_clarification`），但没有确定性的、基于策略的工具调用授权层。运行自主多步任务的 Agent 可以使用任何已加载的工具执行任何参数。Guardrails 添加了一个中间件，在执行**之前**根据策略评估每个工具调用。

## 为什么需要 Guardrails

```
没有 guardrails:                      有 guardrails:

  Agent                                    Agent
    │                                        │
    ▼                                        ▼
  ┌──────────┐                             ┌──────────┐
  │ bash     │──▶ 立即执行                  │ bash     │──▶ GuardrailMiddleware
  │ rm -rf / │                             │ rm -rf / │        │
  └──────────┘                             └──────────┘        ▼
                                                         ┌──────────────┐
                                                         │  Provider    │
                                                         │  根据策略     │
                                                         │  评估        │
                                                         └──────┬───────┘
                                                                │
                                                          ┌─────┴─────┐
                                                          │           │
                                                        允许         拒绝
                                                          │           │
                                                          ▼           ▼
                                                      正常执行     Agent看到：
                                                                      "防护栏拒绝:
                                                                       rm -rf被阻止"
```

**三种安全机制对比**：

| 机制 | 作用 | 局限 |
|------|------|------|
| **沙箱** | 进程隔离，防止逃逸 | 不能防止语义上的危险操作（如数据泄露） |
| **人工确认** | 每步操作都需要人确认 | 不适合自动化工作流 |
| **防护栏** | 确定性的策略驱动授权 | 需要预先配置策略 |

- **沙箱** 提供进程隔离但不提供语义授权。沙箱化的 `bash` 仍然可以 `curl` 数据出去。
- **人工确认** (`ask_clarification`) 对每个操作都需要人在场。对自主工作流不可行。
- **防护栏** 提供无需人工干预的确定性、基于策略的授权。

## 架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                        中间件链                                       │
│                                                                      │
│  1. ThreadDataMiddleware     ─── 每线程目录                           │
│  2. UploadsMiddleware        ─── 文件上传跟踪                         │
│  3. SandboxMiddleware        ─── 沙箱获取                             │
│  4. DanglingToolCallMiddleware ── 修复不完整的工具调用                │
│  5. GuardrailMiddleware ◄──── 评估每个工具调用                       │
│  6. ToolErrorHandlingMiddleware ── 将异常转换为消息                   │
│  7-12. (摘要、标题、记忆、视觉、子代理、澄清)                         │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                         │
                         ▼
           ┌──────────────────────────┐
           │    GuardrailProvider     │  ◄── 可插拔: 任何类
           │    (在YAML中配置)        │      只要有 evaluate/aevaluate
           └────────────┬─────────────┘
                        │
              ┌─────────┼──────────────┐
              │         │              │
              ▼         ▼              ▼
         内置白名单   OAP Passport    自定义
         Provider    Provider        Provider
         (零依赖)    (开放标准)      (你的代码)
                        │
                  任何实现
                  (如 APort，或
                   你自己的评估器)
```

**为什么GuardrailMiddleware实现wrap_tool_call**：
- 与ToolErrorHandlingMiddleware使用相同的模式
- 在工具调用前拦截，评估后再决定是否执行
- 支持同步和异步两种路径

`GuardrailMiddleware` 实现 `wrap_tool_call` / `awrap_tool_call`（与 `ToolErrorHandlingMiddleware` 使用相同的 `AgentMiddleware` 模式）。它：

1. 构建 `GuardrailRequest`，包含工具名、参数和护照引用
2. 调用配置的 provider 的 `evaluate(request)` 方法
3. 如果**拒绝**：返回 `ToolMessage(status="error")` 并附上原因 -- Agent 看到拒绝信息并适应
4. 如果**允许**：传递给实际的工具处理器
5. 如果 **provider 错误** 且 `fail_closed=true`（默认）：阻止调用
6. `GraphBubbleUp` 异常（LangGraph 控制信号）始终传播，从不捕获

**为什么拒绝时返回error消息而不是抛异常**：
- Agent可以"看到"拒绝原因并调整策略
- 异常会中断整个执行流程
- 保持与工具执行错误的语义一致

## 三种 Provider 选项

### 选项 1：内置 AllowlistProvider（零依赖）

最简单的选项。DeerFlow 自带。按工具名称阻止或允许。无需外部包，无需护照，无需网络。

**config.yaml:**
```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["bash", "write_file"]
```

这将阻止所有请求的 `bash` 和 `write_file`。所有其他工具通过。

也可以使用白名单（只允许这些工具）：
```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      allowed_tools: ["web_search", "read_file", "ls"]
```

**为什么提供白名单和黑名单两种模式**：
- 白名单：默认拒绝，只允许明确列出的工具（更安全）
- 黑名单：默认允许，只阻止明确列出的工具（更灵活）
- 适应不同的安全策略需求

**试用：**
1. 将上述配置添加到你的 `config.yaml`
2. 启动 DeerFlow：`make dev`
3. 问 Agent："用 bash 运行 echo hello"
4. Agent 看到：`Guardrail denied: tool 'bash' was blocked (oap.tool_not_allowed)`

### 选项 2：OAP Passport Provider（基于策略）

用于基于 [Open Agent Passport (OAP)](https://github.com/aporthq/aport-spec) 开放标准的策略执行。OAP 护照是一个 JSON 文档，声明了 agent 的身份、能力和操作限制。任何读取 OAP 护照并返回 OAP 兼容决策的 provider 都可用于 DeerFlow。

```
┌─────────────────────────────────────────────────────────────┐
│                    OAP Passport (JSON)                        │
│                   (开放标准，任何 provider)                    │
│  {                                                           │
│    "spec_version": "oap/1.0",                                │
│    "status": "active",                                       │
│    "capabilities": [                                         │
│      {"id": "system.command.execute"},                       │
│      {"id": "data.file.read"},                               │
│      {"id": "data.file.write"},                              │
│      {"id": "web.fetch"},                                    │
│      {"id": "mcp.tool.execute"}                              │
│    ],                                                        │
│    "limits": {                                               │
│      "system.command.execute": {                             │
│        "allowed_commands": ["git", "npm", "node", "ls"],     │
│        "blocked_patterns": ["rm -rf", "sudo", "chmod 777"]   │
│      }                                                       │
│    }                                                         │
│  }                                                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
               任何 OAP 兼容的 provider
          ┌────────────────┼────────────────┐
          │                │                │
     你自己的         APort (参考       其他未来的
     评估器          实现)            实现
```

**为什么使用OAP标准**：
- 开放标准，不绑定特定实现
- 护照可移植，支持不同平台
- 社区维护，持续演进

**手动创建护照：**

OAP 护照只是一个 JSON 文件。你可以按照 [OAP 规范](https://github.com/aporthq/aport-spec/blob/main/oap/oap-spec.md) 手动创建，并使用 [JSON schema](https://github.com/aporthq/aport-spec/blob/main/oap/passport-schema.json) 验证。查看 [examples](https://github.com/aporthq/aport-spec/tree/main/oap/examples) 目录获取模板。

**使用 APort 作为参考实现：**

[APort Agent Guardrails](https://github.com/aporthq/aport-agent-guardrails) 是一个开源（Apache 2.0）的 OAP provider 实现。它处理护照创建、本地评估和可选的托管 API 评估。

```bash
pip install aport-agent-guardrails
aport setup --framework deerflow
```

这会创建：
- `~/.aport/deerflow/config.yaml` -- 评估器配置（本地或 API 模式）
- `~/.aport/deerflow/aport/passport.json` -- 包含能力和限制的 OAP 护照

**config.yaml（使用 APort 作为 provider）：**
```yaml
guardrails:
  enabled: true
  provider:
    use: aport_guardrails.providers.generic:OAPGuardrailProvider
```

**config.yaml（使用你自己的 OAP provider）：**
```yaml
guardrails:
  enabled: true
  provider:
    use: my_oap_provider:MyOAPProvider
    config:
      passport_path: ./my-passport.json
```

任何接受 `framework` 作为 kwarg 并实现 `evaluate`/`aevaluate` 的 provider 都可以工作。OAP 标准定义护照格式和决策代码；DeerFlow 不关心哪个 provider 读取它们。

**护照控制的内容：**

| 护照字段 | 作用 | 示例 |
|---|---|---|
| `capabilities[].id` | Agent 可以使用的工具类别 | `system.command.execute`, `data.file.write` |
| `limits.*.allowed_commands` | 允许的命令 | `["git", "npm", "node"]` 或 `["*"]` 表示全部 |
| `limits.*.blocked_patterns` | 始终拒绝的模式 | `["rm -rf", "sudo", "chmod 777"]` |
| `status` | 紧急停止开关 | `active`, `suspended`, `revoked` |

**评估模式（取决于 provider）：**

OAP provider 可能支持不同的评估模式。例如，APort 参考实现支持：

| 模式 | 工作方式 | 网络 | 延迟 |
|---|---|---|
| **本地** | 本地评估护照（bash 脚本） | 无 | ~300ms |
| **API** | 发送护照 + 上下文到托管评估器。签名决策。 | 是 | ~65ms |

自定义 OAP provider 可以实现任何评估策略 -- DeerFlow 中间件不关心 provider 如何做出决策。

**试用：**
1. 按上述方式安装和设置
2. 启动 DeerFlow 并问："创建一个名为 test.txt 的文件，内容是 hello"
3. 然后问："现在用 bash rm -rf 删除它"
4. 防护栏阻止：`oap.blocked_pattern: 命令包含被阻止的模式: rm -rf`

### 选项 3：自定义 Provider（自带）

任何带有 `evaluate(request)` 和 `aevaluate(request)` 方法的 Python 类都可以。无需基类或继承 -- 它是结构化协议。

```python
# my_guardrail.py

class MyGuardrailProvider:
    name = "my-company"

    def evaluate(self, request):
        from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason

        # 示例：阻止任何包含 "delete" 的 bash 命令
        if request.tool_name == "bash" and "delete" in str(request.tool_input):
            return GuardrailDecision(
                allow=False,
                reasons=[GuardrailReason(code="custom.blocked", message="不允许 delete")],
                policy_id="custom.v1",
            )
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request):
        return self.evaluate(request)
```

**config.yaml:**
```yaml
guardrails:
  enabled: true
  provider:
    use: my_guardrail:MyGuardrailProvider
```

确保 `my_guardrail.py` 在 Python 路径上（例如在 backend 目录或作为包安装）。

**试用：**
1. 在 backend 目录创建 `my_guardrail.py`
2. 添加配置
3. 启动 DeerFlow 并问："用 bash 删除 test.txt"
4. 你的 provider 阻止它

## 实现 Provider

### 必需接口

```
┌──────────────────────────────────────────────────┐
│              GuardrailProvider 协议                │
│                                                   │
│  name: str                                        │
│                                                   │
│  evaluate(request: GuardrailRequest)              │
│      -> GuardrailDecision                         │
│                                                   │
│  aevaluate(request: GuardrailRequest)   (异步)    │
│      -> GuardrailDecision                         │
└──────────────────────────────────────────────────┘

┌──────────────────────────┐    ┌──────────────────────────┐
│     GuardrailRequest      │    │    GuardrailDecision      │
│                           │    │                           │
│  tool_name: str           │    │  allow: bool              │
│  tool_input: dict         │    │  reasons: [GuardrailReason]│
│  agent_id: str | None     │    │  policy_id: str | None    │
│  thread_id: str | None    │    │  metadata: dict           │
│  is_subagent: bool        │    │                           │
│  timestamp: str           │    │  GuardrailReason:         │
│                           │    │    code: str              │
└──────────────────────────┘    │    message: str           │
                                └──────────────────────────┘
```

**为什么使用结构化协议而非继承**：
- 更灵活，不强制基类
- 易于测试和模拟
- 支持第三方实现

### DeerFlow 工具名称

你的 provider 将在 `request.tool_name` 中看到这些工具名称：

| 工具 | 作用 |
|---|---|
| `bash` | Shell 命令执行 |
| `write_file` | 创建/覆盖文件 |
| `str_replace` | 编辑文件（查找和替换） |
| `read_file` | 读取文件内容 |
| `ls` | 列出目录 |
| `web_search` | 网络搜索查询 |
| `web_fetch` | 获取 URL 内容 |
| `image_search` | 图片搜索 |
| `present_file` | 向用户展示文件 |
| `view_image` | 显示图片 |
| `ask_clarification` | 向用户提问 |
| `task` | 委派给子代理 |
| `mcp__*` | MCP 工具（动态） |

### OAP 原因代码

[OAP 规范](https://github.com/aporthq/aport-spec) 使用的标准代码：

| 代码 | 含义 |
|---|---|
| `oap.allowed` | 工具调用已授权 |
| `oap.tool_not_allowed` | 工具不在白名单中 |
| `oap.command_not_allowed` | 命令不在 allowed_commands 中 |
| `oap.blocked_pattern` | 命令匹配被阻止的模式 |
| `oap.limit_exceeded` | 操作超过限制 |
| `oap.passport_suspended` | 护照状态是 suspended/revoked |
| `oap.evaluator_error` | Provider 崩溃（fail-closed） |

### Provider 加载

DeerFlow 通过 `resolve_variable()` 加载 provider -- 与模型、工具和沙箱 provider 使用相同的机制。`use:` 字段是 Python 类路径：`package.module:ClassName`。

如果设置了 `config:`，provider 会用 `**config` kwargs 实例化，加上 `framework="deerflow"` 始终注入。接受 `**kwargs` 以保持向前兼容：

```python
class YourProvider:
    def __init__(self, framework: str = "generic", **kwargs):
        # framework="deerflow" 告诉你使用哪个配置目录
        ...
```

**为什么注入framework参数**：
- Provider可能需要访问特定框架的配置
- 便于同一provider支持多个框架
- 保持向后兼容性

## 配置参考

```yaml
guardrails:
  # 启用/禁用防护栏中间件（默认：false）
  enabled: true

  # 如果 provider 抛出异常是否阻止工具调用（默认：true）
  fail_closed: true

  # 护照引用 -- 作为 request.agent_id 传递给 provider。
  # 文件路径、托管 agent ID 或 null（provider 从其配置解析）。
  passport: null

  # Provider: 通过类路径通过 resolve_variable 加载
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:  # 可选 kwargs 传递给 provider.__init__
      denied_tools: ["bash"]
```

**为什么fail_closed默认为true**：
- 安全优先：不确定时阻止操作
- 符合安全最佳实践
- 可通过配置调整为fail-open

## 测试

```bash
cd backend
uv run python -m pytest tests/test_guardrail_middleware.py -v
```

25 个测试覆盖：
- AllowlistProvider: 允许、拒绝、白名单+黑名单、异步
- GuardrailMiddleware: 允许通过、拒绝带 OAP 代码、fail-closed、fail-open、护照转发、空原因回退、空工具名、协议 isinstance 检查
- 异步路径: awrap_tool_call 的允许、拒绝、fail-closed、fail-open
- GraphBubbleUp: LangGraph 控制信号传播通过（不被捕获）
- 配置: 默认值、from_dict、单例加载/重置

## 文件

```
packages/harness/deerflow/guardrails/
    __init__.py              # 公共导出
    provider.py              # GuardrailProvider 协议，GuardrailRequest，GuardrailDecision
    middleware.py             # GuardrailMiddleware (AgentMiddleware 子类)
    builtin.py               # AllowlistProvider (零依赖)

packages/harness/deerflow/config/
    guardrails_config.py     # GuardrailsConfig Pydantic 模型 + 单例

packages/harness/deerflow/agents/middlewares/
    tool_error_handling_middleware.py  # 在链中注册 GuardrailMiddleware

config.example.yaml          # 记录了三种 provider 选项
tests/test_guardrail_middleware.py  # 25 个测试
docs/GUARDRAILS.md           # 本文件
```
