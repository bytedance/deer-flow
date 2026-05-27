# Guardrails：工具调用前（Pre-Tool-Call）授权

> **背景：** [Issue #1213](https://github.com/bytedance/deer-flow/issues/1213) —— DeerFlow 已有 Docker 沙箱与通过 `ask_clarification` 进行的人类确认机制，但仍缺少一个确定性的、策略驱动的工具调用授权层。执行自主多步骤任务的 agent 可以用任意参数调用任意已加载工具。Guardrails 会新增一个 middleware，在工具执行**之前**按策略评估每一次工具调用。

## 为什么需要 Guardrails

```
Without guardrails:                      With guardrails:

  Agent                                    Agent
    │                                        │
    ▼                                        ▼
  ┌──────────┐                             ┌──────────┐
  │ bash     │──▶ executes immediately     │ bash     │──▶ GuardrailMiddleware
  │ rm -rf / │                             │ rm -rf / │        │
  └──────────┘                             └──────────┘        ▼
                                                         ┌──────────────┐
                                                         │  Provider    │
                                                         │  evaluates   │
                                                         │  against     │
                                                         │  policy      │
                                                         └──────┬───────┘
                                                                │
                                                          ┌─────┴─────┐
                                                          │           │
                                                        ALLOW       DENY
                                                          │           │
                                                          ▼           ▼
                                                      Tool runs   Agent sees:
                                                      normally    "Guardrail denied:
                                                                   rm -rf blocked"
```

- **沙箱（sandboxing）** 提供的是进程隔离，不是语义授权。处于沙箱里的 `bash` 仍可通过 `curl` 外传数据。
- **人工确认（human approval）**（`ask_clarification`）要求每个动作都有人参与，不适合自主工作流。
- **Guardrails** 提供可确定复现、策略驱动且无需人工介入的授权能力。

## 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Middleware Chain                               │
│                                                                      │
│  1. ThreadDataMiddleware     ─── per-thread dirs                     │
│  2. UploadsMiddleware        ─── file upload tracking                │
│  3. SandboxMiddleware        ─── sandbox acquisition                 │
│  4. DanglingToolCallMiddleware ── fix incomplete tool calls           │
│  5. GuardrailMiddleware ◄──── EVALUATES EVERY TOOL CALL             │
│  6. ToolErrorHandlingMiddleware ── convert exceptions to messages     │
│  7-12. (Summarization, Title, Memory, Vision, Subagent, Clarify)    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                         │
                         ▼
           ┌──────────────────────────┐
           │    GuardrailProvider     │  ◄── pluggable: any class
           │    (configured in YAML)  │      with evaluate/aevaluate
           └────────────┬─────────────┘
                        │
              ┌─────────┼──────────────┐
              │         │              │
              ▼         ▼              ▼
         Built-in   OAP Passport    Custom
         Allowlist  Provider        Provider
         (zero dep) (open standard) (your code)
                        │
                  Any implementation
                  (e.g. APort, or
                   your own evaluator)
```

`GuardrailMiddleware` 实现了 `wrap_tool_call` / `awrap_tool_call`（与 `ToolErrorHandlingMiddleware` 一样遵循 `AgentMiddleware` 模式）。其流程为：

1. 构建 `GuardrailRequest`，包含工具名、参数和 passport 引用
2. 调用已配置 provider 的 `provider.evaluate(request)`
3. 若为 **deny**：返回带原因的 `ToolMessage(status="error")`，agent 会看到拒绝结果并调整行为
4. 若为 **allow**：透传给实际工具处理器
5. 若 **provider 报错** 且 `fail_closed=true`（默认）：阻断本次调用
6. `GraphBubbleUp` 异常（LangGraph 控制信号）始终向上抛出，不会被捕获

## 三种 Provider 方案

### 方案 1：内置 AllowlistProvider（零依赖）

最简单的方案。随 DeerFlow 提供。可按工具名阻止或允许；无需外部包、passport 或网络。

**config.yaml：**
```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["bash", "write_file"]
```

上述配置会在所有请求中阻断 `bash` 和 `write_file`，其余工具放行。

你也可以改用 allowlist（仅允许以下工具）：
```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      allowed_tools: ["web_search", "read_file", "ls"]
```

**可快速验证：**
1. 将以上配置加入 `config.yaml`
2. 启动 DeerFlow：`make dev`
3. 对 agent 提问："Use bash to run echo hello"
4. agent 会看到：`Guardrail denied: tool 'bash' was blocked (oap.tool_not_allowed)`

### 方案 2：OAP Passport Provider（策略驱动）

用于基于 [Open Agent Passport (OAP)](https://github.com/aporthq/aport-spec) 开放标准执行策略。OAP passport 是一个 JSON 文档，用于声明 agent 的身份、能力和运行限制。任何能读取 OAP passport 并返回 OAP 兼容决策的 provider，都可与 DeerFlow 配合。

```
┌─────────────────────────────────────────────────────────────┐
│                    OAP Passport (JSON)                        │
│                   (open standard, any provider)              │
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
               Any OAP-compliant provider
          ┌────────────────┼────────────────┐
          │                │                │
     Your own         APort (ref.      Other future
     evaluator        implementation)  implementations
```

**手动创建 passport：**

OAP passport 本质上就是一个 JSON 文件。你可以按 [OAP 规范](https://github.com/aporthq/aport-spec/blob/main/oap/oap-spec.md) 手工编写，并使用 [JSON schema](https://github.com/aporthq/aport-spec/blob/main/oap/passport-schema.json) 进行校验。模板可参考 [examples](https://github.com/aporthq/aport-spec/tree/main/oap/examples) 目录。

**使用 APort 作为参考实现：**

[APort Agent Guardrails](https://github.com/aporthq/aport-agent-guardrails) 是一个开源（Apache 2.0）的 OAP provider 实现，支持 passport 创建、本地评估和可选托管 API 评估。

```bash
pip install aport-agent-guardrails
aport setup --framework deerflow
```

这会创建：
- `~/.aport/deerflow/config.yaml` —— 评估器配置（本地模式或 API 模式）
- `~/.aport/deerflow/aport/passport.json` —— 带能力与限制的 OAP passport

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

任何支持 `framework` 关键字参数并实现 `evaluate`/`aevaluate` 的 provider 都可工作。OAP 标准定义的是 passport 格式与决策码；DeerFlow 不绑定具体实现方。

**passport 可控制内容：**

| Passport field | 作用 | 示例 |
|---|---|---|
| `capabilities[].id` | 允许 agent 使用的工具能力类别 | `system.command.execute`, `data.file.write` |
| `limits.*.allowed_commands` | 允许执行的命令 | `["git", "npm", "node"]`，或 `["*"]` 表示全部允许 |
| `limits.*.blocked_patterns` | 永远拒绝的模式 | `["rm -rf", "sudo", "chmod 777"]` |
| `status` | 总开关（熔断） | `active`, `suspended`, `revoked` |

**评估模式（依 provider 实现而定）：**

OAP provider 可能支持不同评估模式。例如，APort 参考实现支持：

| 模式 | 工作方式 | 网络 | 延迟 |
|---|---|---|---|
| **Local** | 本地评估 passport（bash 脚本） | 无 | ~300ms |
| **API** | 将 passport + 上下文发送到托管评估器，返回签名决策 | 需要 | ~65ms |

自定义 OAP provider 可实现任意评估策略——DeerFlow middleware 不关心 provider 如何得出结论。

**可快速验证：**
1. 按上文完成安装和配置
2. 启动 DeerFlow，然后提问："Create a file called test.txt with content hello"
3. 再提问："Now delete it using bash rm -rf"
4. Guardrail 会阻断：`oap.blocked_pattern: Command contains blocked pattern: rm -rf`

### 方案 3：自定义 Provider（Bring Your Own）

任何包含 `evaluate(request)` 和 `aevaluate(request)` 方法的 Python 类都可用。无需基类或继承关系——这是结构化协议（structural protocol）。

```python
# my_guardrail.py

class MyGuardrailProvider:
    name = "my-company"

    def evaluate(self, request):
        from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason

        # 示例：阻断所有包含 "delete" 的 bash 命令
        if request.tool_name == "bash" and "delete" in str(request.tool_input):
            return GuardrailDecision(
                allow=False,
                reasons=[GuardrailReason(code="custom.blocked", message="delete not allowed")],
                policy_id="custom.v1",
            )
        return GuardrailDecision(allow=True, reasons=[GuardrailReason(code="oap.allowed")])

    async def aevaluate(self, request):
        return self.evaluate(request)
```

**config.yaml：**
```yaml
guardrails:
  enabled: true
  provider:
    use: my_guardrail:MyGuardrailProvider
```

请确保 `my_guardrail.py` 位于 Python 路径上（例如放在 backend 目录下，或安装为 package）。

**可快速验证：**
1. 在 backend 目录创建 `my_guardrail.py`
2. 添加上述配置
3. 启动 DeerFlow 并提问："Use bash to delete test.txt"
4. 你的 provider 会阻断该操作

## 实现 Provider

### 必需接口

```
┌──────────────────────────────────────────────────┐
│              GuardrailProvider Protocol            │
│                                                   │
│  name: str                                        │
│                                                   │
│  evaluate(request: GuardrailRequest)              │
│      -> GuardrailDecision                         │
│                                                   │
│  aevaluate(request: GuardrailRequest)   (async)   │
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

### DeerFlow 工具名

下列名称即 provider 在 `request.tool_name` 中会看到的工具名：

| Tool | 作用 |
|---|---|
| `bash` | Shell 命令执行 |
| `write_file` | 新建/覆盖文件 |
| `str_replace` | 编辑文件（查找并替换） |
| `read_file` | 读取文件内容 |
| `ls` | 列出目录 |
| `web_search` | 网页搜索查询 |
| `web_fetch` | 抓取 URL 内容 |
| `image_search` | 图片搜索 |
| `present_files` | 向用户展示文件 |
| `view_image` | 显示图片 |
| `ask_clarification` | 向用户提问 |
| `task` | 委派给 subagent |
| `mcp__*` | MCP 工具（动态） |

### OAP 原因码

[OAP 规范](https://github.com/aporthq/aport-spec)中使用的标准代码：

| Code | 含义 |
|---|---|
| `oap.allowed` | 工具调用已授权 |
| `oap.tool_not_allowed` | 工具不在 allowlist 中 |
| `oap.command_not_allowed` | 命令不在 allowed_commands 中 |
| `oap.blocked_pattern` | 命令匹配了被阻断的模式 |
| `oap.limit_exceeded` | 操作超出限制 |
| `oap.passport_suspended` | passport 状态为 suspended/revoked |
| `oap.evaluator_error` | provider 崩溃（fail-closed） |

### Provider 加载

DeerFlow 通过 `resolve_variable()` 加载 provider——该机制与模型、工具、sandbox provider 一致。`use:` 字段是 Python 类路径：`package.module:ClassName`。

若配置了 `config:`，provider 将以 `**config` 方式实例化；此外还会始终注入 `framework="deerflow"`。建议接受 `**kwargs` 以保持前向兼容：

```python
class YourProvider:
    def __init__(self, framework: str = "generic", **kwargs):
        # framework="deerflow" 告诉你应使用哪套配置目录
        ...
```

## 配置参考

```yaml
guardrails:
  # 启用/禁用 guardrail middleware（默认：false）
  enabled: true

  # 当 provider 抛异常时是否阻断工具调用（默认：true）
  fail_closed: true

  # Passport 引用 —— 作为 request.agent_id 传给 provider。
  # 可为文件路径、托管 agent ID，或 null（由 provider 自行解析配置）。
  passport: null

  # Provider：通过 resolve_variable 按类路径加载
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:  # 可选，传给 provider.__init__ 的 kwargs
      denied_tools: ["bash"]
```

## 测试

```bash
cd backend
uv run python -m pytest tests/test_guardrail_middleware.py -v
```

共 25 个测试，覆盖：
- AllowlistProvider：allow、deny、allowlist+denylist 同时配置、异步路径
- GuardrailMiddleware：allow 透传、带 OAP 代码的 deny、fail-closed、fail-open、passport 透传、空 reasons 回退、空工具名、协议 `isinstance` 校验
- 异步路径：`awrap_tool_call` 的 allow、deny、fail-closed、fail-open
- GraphBubbleUp：LangGraph 控制信号可透传（不会被捕获）
- 配置：默认值、`from_dict`、单例加载/重置

## 文件

```
packages/harness/deerflow/guardrails/
    __init__.py              # Public exports
    provider.py              # GuardrailProvider protocol, GuardrailRequest, GuardrailDecision
    middleware.py             # GuardrailMiddleware (AgentMiddleware subclass)
    builtin.py               # AllowlistProvider (zero deps)

packages/harness/deerflow/config/
    guardrails_config.py     # GuardrailsConfig Pydantic model + singleton

packages/harness/deerflow/agents/middlewares/
    tool_error_handling_middleware.py  # Registers GuardrailMiddleware in chain

config.example.yaml          # Three provider options documented
tests/test_guardrail_middleware.py  # 25 tests
docs/GUARDRAILS.md           # This file
```
