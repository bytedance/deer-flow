# 接入 DeerFlow

**不改 DeerFlow 一行源码。** 两处配置搞定：审批走反射加载点，预算走中间件注入点。

本文引用的上游符号均已在本机源码中核对过，对应版本见文末「锁定的上游事实」。

---

## 1. 审批：挂 GuardrailProvider

DeerFlow 用 `resolve_variable()` 反射加载 guardrail provider，
与它加载 models / tools / sandbox 是**同一套机制**——这就是官方留的扩展点。

编辑 `deer-flow/config.yaml`：

```yaml
guardrails:
  enabled: true
  fail_closed: true # provider 抛异常时拦截而不是放行
  provider:
    use: "deerflow_governance.provider:ApprovalGuardrailProvider"
    config:
      config_path: "/abs/path/to/governance.yaml"
```

把插件装进 backend 的环境：

```bash
cd deer-flow/backend
uv pip install -e ../../deerflow-governance      # 或把 src/ 加进 PYTHONPATH
```

**验证挂上了没**：

```bash
cd deer-flow/backend && make dev
# 另开一个终端，让 agent 跑一个会命中 ask 规则的操作，然后：
governance pending
```

如果 `governance pending` 里出现了单子，说明 provider 已经在拦截链路上。

### 为什么 ask 要表达成 allow=False

`GuardrailDecision` 只有一个 `allow: bool`，没有第三态。本插件把 `ask` 编码成
`allow=False` + reason code `governance.approval_pending`，并在 message 里写清楚：

> 此操作需要人工审批，已提交审批单 APR-XXXX（风险等级：high，命中规则：xxx）。
> **在审批通过之前请不要重试本操作，也不要尝试用其他工具绕过它。**
> 你可以：先完成不需要审批的部分，或向用户说明正在等待审批结果。

最后那句是必需的。裸拒绝会让模型立刻换个工具去达成同样的效果——
`write_file` 被拦就改用 `bash: echo > file`。**审批系统的第一个失效模式不是被绕过，
而是模型不知道自己被审批了。**

---

## 2. 预算：挂 BudgetBreakerMiddleware

`build_middlewares` 的签名（`packages/harness/deerflow/agents/lead_agent/agent.py:260`）：

```python
def build_middlewares(
    config: RunnableConfig,
    model_name: str | None,
    agent_name: str | None = None,
    custom_middlewares: list[AgentMiddleware] | None = None,   # ← 官方注入点
    *,
    available_skills: set[str] | None = None,
    app_config: AppConfig | None = None,
    deferred_setup=None,
):
```

第 379-380 行：

```python
if custom_middlewares:
    middlewares.extend(custom_middlewares)
```

注入位置在 `SafetyFinishReasonMiddleware` / `ClarificationMiddleware` 这条尾巴之前，
正是 AGENTS.md 第 235 条描述的位置（"Custom middlewares … injected here, before the safety/clarification tail"）。

调用方式：

```python
from deerflow_governance.middleware import BudgetBreakerMiddleware

middlewares = build_middlewares(
    config,
    model_name,
    custom_middlewares=[BudgetBreakerMiddleware.from_config("/abs/path/to/governance.yaml")],
)
```

### 挂在哪个调用点

`build_middlewares` 有两个调用方（AGENTS.md 明确要求这个函数名保持稳定，
因为它跨模块被 `client.py` import）：

1. `make_lead_agent`（Gateway 服务路径）
2. `DeerFlowClient`（嵌入式客户端路径）

要全局生效就两处都传。**如果你不想动 DeerFlow 的文件**，可以走 SDK 层：
`create_deerflow_agent(extra_middleware=[...])` 支持 `@Next` / `@Prev` 锚点定位，
但那条路径的中间件链是精简子集，不等同于生产链路（`factory.py` 自己的 docstring
说"matches make_lead_agent (14 middlewares)"，而 AGENTS.md 描述的生产链路有 27 项——
**上游这三处描述互相不一致**，以 AGENTS.md 为准）。

### 中间件顺序的坑

LangChain 的钩子有两种派发方向，写自定义中间件前必须知道：

- `wrap_model_call` / `wrap_tool_call`：**洋葱模型**，按注册顺序从外向内包裹
- `after_model`：**反序**触发（DeerFlow 正是靠这一点，把 `SafetyFinishReasonMiddleware`
  注册在自定义中间件之后，好让它的 `after_model` 先跑）

`BudgetBreakerMiddleware` 同时用了这两类钩子：`after_model` 记账与硬停，
`wrap_model_call` 把预警作为 `<system-reminder>` 注入下一次请求。放在自定义区即可，
不需要争抢特定位置。

---

## 3. 审批操作

审批的人通常不是跑 agent 的人，所以给了一个不依赖 DeerFlow 的 CLI：

```bash
governance pending                                    # 待审批队列
governance show APR-XXXX                              # 单据详情（含完整命令）
governance approve APR-XXXX --by 张三 --note "已确认目标分支"
governance deny    APR-XXXX --by 张三 --note "禁止直推主干"
governance audit --thread <thread_id> -n 50           # 决策链
governance stats                                      # 治理概览
governance expire                                     # 清理过期批准
```

`--by` 是必填的：没有裁决人的审批记录在审计上没有意义。

---

## 4. 上线前的验证顺序

```bash
# 1. 策略配置能加载、规则合法（放进 CI）
governance validate

# 2. 干跑关键场景，确认判定符合预期
governance simulate --tool bash --arg command="rm -rf build" --explain
governance simulate --tool bash --arg command="pytest -q"
governance simulate --tool write_file --arg file_path="backend/.env"
governance simulate --tool bash --arg command="ls" --subagent

# 3. 核心层回归
make test

# 4. 端到端演示（不需要 DeerFlow）
make demo

# 5. 接进 DeerFlow 后做冒烟：跑一个会命中 ask 的任务，确认 governance pending 有单
```

前四步都不需要 DeerFlow 环境，可以进 CI。

---

## 5. `interrupt` 模式（实验，未实测）

`approval_mode: interrupt` 会让 provider 直接调 LangGraph 的 `interrupt()`。

**依据**（`packages/harness/deerflow/guardrails/middleware.py:75-77`）：

```python
except GraphBubbleUp:
    # Preserve LangGraph control-flow signals (interrupt/pause/resume).
    raise
```

DeerFlow 显式把 `GraphBubbleUp` 放行，注释直接写了 interrupt/pause/resume——
说明 provider 层就是官方为 HITL 预留的挂载点。

**但仍然不设为默认**，两个原因：

1. Gateway 侧的 resume 通路（怎么把人工决定回灌进 `Command(resume=...)`）**本人未实测**。
   DeerFlow 自己的中断做法是 `ClarificationMiddleware` 用 `Command(goto=END)` 结束本轮、
   靠用户下一条消息续上，而不是 `interrupt()`。
2. 子 agent 图是 `checkpointer=False` 编译的（AGENTS.md:343 原文
   "Subagent graphs are compiled with `checkpointer=False` … subagents are one-shot and never resume"），
   `interrupt()` 在子 agent 里不成立。而子 agent 恰恰最需要审批。

要试可以开，但请自己补上 resume 侧的验证，并把结果回写本节。

---

## 6. 锁定的上游事实

本插件依赖以下 DeerFlow 内部符号。上游变动时，**先核对这张表再改代码**：

| 依赖 | 位置 | 用法 |
|---|---|---|
| `GuardrailRequest` 字段 | `deerflow/guardrails/provider.py` | provider 逐字段搬运 |
| `GuardrailDecision` / `GuardrailReason` | 同上 | 返回值构造 |
| `GuardrailProvider` 协议（`name` / `evaluate` / `aevaluate`） | 同上 | 鸭子类型实现，无需继承 |
| `GraphBubbleUp` 放行 | `deerflow/guardrails/middleware.py:75` | interrupt 模式的前提 |
| `guardrails.provider.use` 反射加载 | `deerflow/config/guardrails_config.py` | 挂载方式 |
| `build_middlewares(custom_middlewares=...)` | `deerflow/agents/lead_agent/agent.py:264,379` | 中间件注入 |
| `AgentMiddleware` 钩子集 | `langchain/agents/middleware/types.py` | `after_model` / `wrap_model_call` |
| `ToolCallRequest.tool_call` / `.runtime.context` | `langgraph.prebuilt.tool_node` | 间接（经 GuardrailRequest） |

核对环境：本机 `deer-flow/backend`，Python 3.12，`.venv` 内的 langchain 已装。
**本插件的适配层未在真实 DeerFlow 运行时跑过**（我这边缺 API key 与可运行的 Gateway），
核心层的 47 个用例与端到端演示已全绿。接进去之后请补运行证据并回写本文件。
