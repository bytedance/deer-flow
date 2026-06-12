# DeerFlow Agent Router 统一调度层设计

**Date**: 2026-06-07
**Status**: Design (待评审)
**Scope**: 在 Gateway 之上引入统一的 Agent 路由层,收敛当前散落在 `acp_config` / `agents_config` / `app_config` / Dify 配置里的多套 agent 定义,让"为什么这个请求走到了这条路径"可被声明、可被回放、可被灰度。

---

我先用 CodeGraph 快速摸清当前架构,再给一个有依据的判断。

  Listed 3 directories, called codegraph 3 times, ran 1 shell command

我看了下当前架构:lead agent(18 个 middleware 的 LangGraph) + 两个 ACP 外部 agent(Claude/Pi)+ Dify workflow + IM 频道 + 自定义 AgentConfig 技能选择,五条路径已经在 config.yaml 里共存了,但没有统一调度层告诉一个进来的请求该走哪条路。

最需要的是一个 Agent Router(调度/意图分类层):在 Gateway 或 Lead Agent 上加一层"接到请求 → 选 agent → 落 ACP/原生/Dify"的分发器,把当前散在 acp_config.py / agents_config.py / app_config.py / Dify 配置里的 agent 定义收敛成一个可路由的注册表,并把每次"为什么选了这个 agent"留痕。

主要 tradeoff:放在 Gateway 层(路由规则可见、可灰度、易测试)还是放在 Lead Agent 里当成一个 tool(LLM 自主调度)——前者牺牲灵活性换可控,后者灵活但跨进程/跨 ACP 时调试和回放很难,且 auto_approve_permissions 那种策略会落在子 agent 自己身上,主流程管不住。

要往这个方向走,我建议下一步先在 config.yaml 加一个 agents.routing 段(声明式规则:关键词/正则/默认 fallback)而不是改代码——你看这个方向对吗,还是你心里有更优先的痛点(比如 ACP 子进程的可观测性、Dify 流的断点续传、还是先合并 m2 分支)?


## 1. 背景

DeerFlow 当前已存在多条 agent 路径,但没有任何"调度层"统一管理:

| 路径 | 入口 | 进程模型 | 配置位置 |
|------|------|----------|----------|
| Lead Agent(LangGraph) | `make dev` / LangGraph server | 同进程异步 | `config.yaml` + lead_agent 工厂 |
| Claude ACP | `invoke_acp_agent(agent="claude")` | 子进程 stdio JSON-RPC | `acp_agents.*` |
| Pi ACP | `invoke_acp_agent(agent="pi")` | 子进程 stdio JSON-RPC | `acp_agents.*` |
| Dify Workflow | `dify_workflow(workflow_name=...)` tool | HTTP 出站 | `dify.*` 块 |
| Custom AgentConfig | `agents_config.py` 里的命名 agent | 同进程 LangGraph 子图 | `agents.*` |

**问题**:

1. **路由是隐式的** —— 谁来选哪条路径完全靠 LLM 在 lead agent 里"自由发挥"(system prompt 里写一句"小任务走 pi"就完事了,见 `prompt.py:_build_acp_section`)。
2. **配置分散** —— `acp_agents.pi.command/args/env` 和 `dify.workflows.*.endpoint` 各自为政,没有"agent 注册表"统一视角。
3. **无可观测性** —— 一个用户请求到底走了哪条路径、为什么选、用了多少 token、ACP 子进程是否被 spawn 失败,全靠日志拼接,没有结构化 trace。
4. **灰度/策略缺位** —— 想让"图片识别类请求 10% 走 claude-acp 做 A/B"目前没有任何机制;`auto_approve_permissions` 是 per-agent 静态开关,不能按请求动态生效。
5. **权限/合规分散** —— ACP 子进程自己管 `auto_approve_permissions`,Dify 走 `dify_workflow` tool 自身审批,lead agent 由 `GuardrailMiddleware` 管,三套策略互不通气。

---

## 2. 目标与非目标

### 2.1 Goals

- G1. 把"agent 定义 + 路由规则 + 策略"统一收敛到一个**声明式注册表**,只放在 `config.yaml`。
- G2. 在请求进入 lead agent **之前**完成路由决策,路由结果随 thread state 一起传下去,lead agent 看到的是"已选定的 agent 上下文"而不是"自己挑"。
- G3. 每次路由决策产生一条结构化 **routing trace**(命中规则、备选、fallback 链、最终落点),落到 thread 日志和 LangGraph run metadata。
- G4. 路由决策支持**显式覆盖**:用户/IM 频道/前端入口可以在请求里带 `x-deerflow-agent: pi` 之类的 hint,直接跳过匹配。
- G5. 失败回退链可声明:agent X 不可用时,自动降级到 agent Y,而不是让 lead agent 自由决定。

### 2.2 Non-Goals

- N1. **不**实现跨 agent 的状态共享 / session 续接。每个 agent 仍是独立上下文,router 只决定"丢给谁",不管 agent 内部状态。
- N2. **不**做"LLM 自主选 agent"的能力保留;router 是显式规则的,不是让 LLM 调一个 `choose_agent` tool。如果后续要灵活选,是 router 内部用小模型做二阶段意图分类,**不**暴露给 lead agent。
- N3. **不**改 IM 频道、Uploads、Artifacts 这些边界协议;只动 Gateway 入口到 lead agent 这一段。
- N4. **不**做配额/计费,留到 `TokenUsageMiddleware` 之上做单独的 metering 层。

---

## 3. 架构

### 3.1 总图

```
                                HTTP / SSE / IM webhook
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  Gateway (FastAPI)   │
                              │  /api/agents/route   │◀────── config.yaml: agents.routing
                              └──────────┬───────────┘
                                         │  routing decision (trace + selected_agent)
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │  Agent Runtime (Lead Agent or Embedded)      │
                  │  ┌──────────────────────────────────────┐    │
                  │  │ RouterContextMiddleware (new)        │    │ ◀── 把 routing decision 注入
                  │  │  - 读 routing decision              │    │     到 messages 的 system 块
                  │  │  - 暴露到 thread_state               │    │
                  │  └──────────────────────────────────────┘    │
                  │  ...其他 17 个 middleware...                  │
                  │  ┌──────────────────────────────────────┐    │
                  │  │ SelectedAgentRunner (new)            │    │ ◀── 替换原"lead agent 自由挑
                  │  │  - 走 lead_agent / invoke_acp_agent  │    │     agent"的逻辑
                  │  │  - 失败按 fallback 链重试             │    │
                  │  └──────────────────────────────────────┘    │
                  └──────────────────────────────────────────────┘
                                         │
              ┌──────────┬───────────────┼────────────────┐
              ▼          ▼               ▼                ▼
        lead_agent   invoke_acp_     dify_workflow    custom_agent
        (LangGraph)  agent (subproc) (HTTP out)        (subgraph)
```

**关键决策**:Router 放在 **Gateway 层**,不是 Lead Agent 层。
- Gateway 是请求的统一入口,routing 在这层做完,lead agent 看到的是"已经决定好的"上下文。
- 这样 routing 规则可被 IM 频道 / 前端 / OpenAPI 调用方直接看到和覆盖(显式 hint)。
- Lead agent 内部不再有"我该调哪个 ACP"这种决策,降低 system prompt 复杂度和 LLM 自由度,减少误路由。

### 3.2 路由时机

Router 在 Gateway 接到请求后、构造 LangGraph run input 之前完成。Router 输出一个 `RoutingDecision`:

```python
@dataclass
class RoutingDecision:
    primary_agent: str           # "lead_agent" | "claude-acp" | "pi-acp" | "dify:ai-writing" | "custom:banking-advisor"
    fallback_chain: list[str]    # 失败时按顺序降级
    matched_rule: str            # 命中规则的 id,用于 trace
    hints: dict[str, Any]        # 透传给 agent 的 hint(模型名、permission policy 等)
    trace: list[RoutingStep]     # 每一步的评估记录
    decided_at: datetime
```

`RoutingDecision` 写进 `thread_state.routing`,既给 `RouterContextMiddleware` 读,也给前端 SSE 流推送时显示("已路由到: pi-acp")。

---

## 4. 配置形态

只新增一段 `agents.routing`,不动现有 `acp_agents` / `dify` / `agents` 块(那些变成"被引用的资源池")。

```yaml
# config.yaml
agents:
  routing:
    # 默认落点:不命中任何规则时走这个
    default: lead_agent

    # 显式 hint header → 强制选 agent(优先级最高)
    hints:
      x-deerflow-agent: true   # 允许 HTTP header 直接指定

    # 声明式规则,按顺序评估,首命中胜出
    rules:
      - id: code-task-to-pi
        description: 小型单轮代码生成任务 → pi-acp
        when:
          any:                       # 满足任一条件
            - keyword: ["写代码", "fix bug", "改函数", "implement"]
            - regex: "(?i)write (a|an)?\\s*(function|class|test)"
            - has_upload: { ext: [".py", ".ts", ".js", ".go"] }
        select: pi-acp
        fallback: [lead_agent]       # pi 不可用时降级到 lead_agent

      - id: image-ocr-to-dify
        description: 图片识别快捷入口
        when:
          quick_action: image-ocr    # 匹配前端 quickActions.imageOcr
        select: dify:image-ocr
        fallback: [lead_agent]

      - id: banking-domain-isolated
        description: 银行 ChatBI 走专用 agent,沙箱隔离
        when:
          channel: feishu             # 限定飞书渠道
          and:
            - regex: "(贷款|存款|利率|汇率)"
        select: custom:banking-advisor
        permissions: deny_all         # 强制关闭该 agent 的 tool 调用权限
        fallback: [lead_agent]

      - id: a-b-test-claude
        description: 10% 流量试投 claude-acp 做效果对比
        when:
          random: 0.1
          and:
            - keyword: ["深度研究", "research"]
        select: claude-acp
        fallback: [lead_agent]
        observe_only: true            # 不实际切流,只记录"如果切了会怎样"
```

**为什么是 YAML 而不是 Python**:

- 路由规则会随运营/产品/灰度频繁调整,Python 改一次需要重启 backend。
- YAML 配合 `make config-upgrade` 走 `config_version` 升级,跟现有 ACP/Dify 块一致。
- 规则可以被 `gateway/routers/agents.py:router` 直接 reload(后续可加 SIGHUP/watch)。

---

## 5. 关键模块

### 5.1 新增 `deerflow/agents/router/`

```
deerflow/agents/router/
├── __init__.py
├── decision.py          # RoutingDecision / RoutingStep dataclass
├── config.py            # RoutingConfig pydantic model,load from config.yaml
├── engine.py            # RuleEngine: 输入 RequestContext,输出 RoutingDecision
├── rules.py             # 各种 predicate: keyword / regex / channel / random / has_upload
├── fallback.py          # FallbackChainExecutor: 失败重试与降级
└── trace.py             # 路由 trace 序列化,落 thread_state + run metadata
```

### 5.2 Gateway 改造点

- `backend/app/gateway/routers/agents.py` 新增 `/api/agents/route` 端点(GET debug 用,POST 实际路由),便于 IM 频道或前端直接调。
- `backend/app/gateway/main.py` 的 request handler 在构造 LangGraph run input 前调用 `engine.decide(request_context)`,把 `RoutingDecision` 塞进 `config.configurable.routing`。
- `configurable.routing` 由 LangGraph 的 thread/config 机制自动持久化,跨 checkpoint 可恢复。

### 5.3 Lead Agent 改造点

- 新增 `RouterContextMiddleware`(插在 18 个 middleware 的**最前面**,早于 `ThreadDataMiddleware`)。职责:
  1. 从 `config.configurable.routing` 读 `RoutingDecision`。
  2. 把"你必须走 agent X"以 system message 形式注入(但不让 lead agent 看见 routing trace,避免它"反悔")。
  3. 暴露 `thread_state.routing` 供其他 middleware 引用(比如 `TokenUsageMiddleware` 按 agent 分桶)。
- `SelectedAgentRunner`(替换 `agents/factory.py:make_lead_agent` 里 ACP 调度部分):根据 `routing.primary_agent` 直接 dispatch 到对应 runner,不再让 LLM 决定。
- `prompt.py:_build_acp_section` 大幅简化:不再写"小任务走 pi",改为引用 `thread_state.routing.primary_agent` 即可。

### 5.4 可观测性

每次路由决策产出:

```json
{
  "request_id": "req-uuid",
  "decided_at": "2026-06-07T10:23:11Z",
  "matched_rule": "code-task-to-pi",
  "primary_agent": "pi-acp",
  "fallback_chain": ["lead_agent"],
  "evaluated_rules": [
    { "id": "code-task-to-pi", "matched": true, "duration_ms": 2 },
    { "id": "image-ocr-to-dify", "matched": false, "skipped_at": "quick_action_mismatch" }
  ],
  "hints": { "x-deerflow-agent": null },
  "outcome": { "agent_used": "pi-acp", "exit_code": 0, "duration_ms": 4230 }
}
```

- 写到 `thread_state.routing.trace`,前端 SSE 流推送 `event: routing` 事件,UI 可以画一条"路由轨迹"。
- 写到 LangGraph run metadata,可在 LangGraph Studio 看到。
- 失败时(`outcome.exit_code != 0`)记 warning,触发 fallback 时额外记一条。

---

## 6. 边界与权衡

### 6.1 为什么不在 Lead Agent 里做成 tool

| 维度 | Gateway 层 router | Lead Agent 里的 `choose_agent` tool |
|------|------------------|-------------------------------------|
| 规则可见性 | 配置文件 + 可 HTTP 查询 | 藏在 LLM 推理里,回放难 |
| 显式覆盖 | header / IM hint 直接生效 | 要看 LLM 是否听话调 tool |
| 灰度/可观测 | 结构化 trace 落 metadata | 依赖 tool_call 日志 |
| LLM 自由度 | 受控,降低误路由 | 灵活但容易选错 |
| 失败回退 | fallback 链显式声明 | 靠 LLM 自己重试 |
| 跨 agent 状态 | 无,符合 non-goal N1 | 容易引入隐式状态 |
| 实施成本 | 中(新增 router 模块) | 低(加一个 tool) |

**结论**:可控性 > 灵活性。LLM 的"自主选 agent"看起来聪明,实际生产中要么过度调 ACP 增加成本,要么该调时没调导致 lead agent 自己硬扛。可观测的规则 + 显式 fallback 链更可靠。

### 6.2 二阶段意图分类怎么办

如果未来出现"prompt 里没说清走哪个,但语义上是某类"的需求,在 `engine.py` 内部用一个小模型(比如 `gpt-4o-mini` / 本地 `qwen2.5-7b`)做二阶段分类,**不**暴露给 lead agent。这种分类结果当作 `rules` 里的一种特殊 predicate(`intent: coding`, `intent: writing`),失败时退回到 default。

### 6.3 性能

- 规则评估:首版本全是同步 predicate(关键字、正则、channel、random),单条规则 < 5ms,10 条规则 < 50ms,在 Gateway 可接受范围。
- 后续加 LLM 意图分类:用小模型 + prompt caching,预算 < 200ms,放异步预评估,不影响主链路 latency。

### 6.4 兼容性

- **向后兼容**:不开 `agents.routing` 段时,行为与现在完全一致(默认 `lead_agent`,不命中任何规则,`invoke_acp_agent` tool 仍由 lead agent 自由调)。
- **数据兼容**:`config_version` bump 一次,`make config-upgrade` 自动补 `agents.routing.default: lead_agent` 兜底段。
- **API 兼容**:Gateway 现有 `/api/thread/*` 接口不动,只是 run input 多一个 `configurable.routing` 字段。

---

## 7. 实施切片

按依赖关系切成 4 步,每步都可独立 ship:

1. **M1 - Router 数据模型 + 单元测试**(纯模块,不改 Gateway/Lead Agent)
   - `decision.py` / `config.py` / `engine.py` / `rules.py`
   - 覆盖所有 predicate 类型 + fallback 链 + 10 条规则以内的性能
   - **不依赖**任何运行时

2. **M2 - Gateway 接入 + 路由 trace 落 thread_state**
   - `gateway/main.py` 调用 `engine.decide()`
   - `configurable.routing` 写进 LangGraph run config
   - 新增 `/api/agents/route` debug 端点
   - 老的 `invoke_acp_agent` tool 路径保留,行为不变(向后兼容)

3. **M3 - `RouterContextMiddleware` + `SelectedAgentRunner`**
   - Lead Agent 顶部插入新 middleware
   - `make_lead_agent` 改为按 `routing.primary_agent` dispatch
   - `prompt.py:_build_acp_section` 简化
   - 跑回归测试集,确保现有 ACP/Dify 用例无回归

4. **M4 - 灰度规则 + 可观测性 + IM hint**
   - `random` / `observe_only` predicate 实现
   - 路由 trace SSE 推送给前端
   - IM 频道(Feishu/Slack/Telegram)支持 `x-deerflow-agent` header hint
   - 文档 + `make config-upgrade` 模板

每个 M 之间都可以停下来评估,不必一口气做完。

---

## 8. 风险与待确认

| 项 | 风险 | 缓解 |
|----|------|------|
| 配置膨胀 | 规则多了 YAML 难维护 | 提供 `rules: - import: ./routing/*.yaml` 支持拆分文件 |
| 灰度污染 | `observe_only` 和真切的灰度混在一起 | trace 里明确标记 `mode: observe_only` / `mode: enforce` |
| 权限绕过 | router 选错了 agent,绕过 lead agent 的 Guardrail | router 不替代 Guardrail,Guardrail 仍是最后一道 |
| IM hint 滥用 | 用户/频道乱传 `x-deerflow-agent` | 维护一个 `allowed_hints` 白名单,不在白名单的 hint 落到 default |
| 与现有 `invoke_acp_agent` tool 关系 | 是否废弃 | M3 之前保留,M4 后转为内部实现,API 隐藏 |

### 待确认

1. **路由规则是否需要支持热更新**?(影响 M2 是否引入 SIGHUP)
2. **`observe_only` 模式跑出来的 trace 怎么消费**?是只落日志,还是要再做一个对比报表?
3. **banking 那个 `permissions: deny_all` 是不是要 router 强制覆盖 agent 自带的 `auto_approve_permissions`?**(目前倾向是:router 的 policy 优先,agent 自身声明的是兜底)
4. **与 Dify 现有的"快捷入口提示词路由设计"(`docx/api/04-prompt-routing-design.md`)关系**:那个是 lead agent **内部**的 tool 路由,本设计是 lead agent **之外**的 runtime 路由,两者不冲突,但要在文档里点明"这是不同层"。

---

## 9. 不做的话会怎样

- ACP / Dify / Custom agent 继续各加各的,每加一个就要改 `prompt.py` 加一段引导文字,system prompt 越来越长,LLM 路由越来越不可控。
- 想做 A/B / 灰度时,只能改 lead agent prompt 加概率指令,既不准也无 trace。
- 故障定位继续靠 grep 日志,一个请求走哪条路只能猜。
- 权限策略继续三套并存,合规审查每次都要看三处配置。

引入 Agent Router 是把"agent 编排"从"prompt 工程"提升到"声明式配置 + 显式 trace"的必要一步,越晚做,后面要重构的成本越高。
