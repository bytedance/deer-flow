# Middleware 执行流程

## Middleware 列表

`create_deerflow_agent` 通过 `RuntimeFeatures` 组装的完整 middleware 链（默认全开时）：

| # | Middleware | `before_agent` | `before_model` | `after_model` | `after_agent` | `wrap_tool_call` | 主 Agent | Subagent | 来源 |
|---|-----------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|------|
| 0 | ThreadDataMiddleware | ✓ | | | | | ✓ | ✓ | `sandbox` |
| 1 | UploadsMiddleware | ✓ | | | | | ✓ | ✗ | `sandbox` |
| 2 | SandboxMiddleware | ✓ | | | ✓ | | ✓ | ✓ | `sandbox` |
| 3 | DanglingToolCallMiddleware | | | ✓ | | | ✓ | ✗ | 始终开启 |
| 4 | GuardrailMiddleware | | | | | ✓ | ✓ | ✓ | *Phase 2 纳入* |
| 5 | ToolErrorHandlingMiddleware | | | | | ✓ | ✓ | ✓ | 始终开启 |
| 6 | SummarizationMiddleware | | | ✓ | | | ✓ | ✗ | `summarization` |
| 7 | TodoMiddleware | | | ✓ | | | ✓ | ✗ | `plan_mode` 参数 |
| 8 | TitleMiddleware | | | ✓ | | | ✓ | ✗ | `auto_title` |
| 9 | MemoryMiddleware | | | | ✓ | | ✓ | ✗ | `memory` |
| 10 | ViewImageMiddleware | | ✓ | | | | ✓ | ✗ | `vision` |
| 11 | SubagentLimitMiddleware | | | ✓ | | | ✓ | ✗ | `subagent` |
| 12 | LoopDetectionMiddleware | | | ✓ | | | ✓ | ✗ | 始终开启 |
| 13 | ClarificationMiddleware | | | ✓ | | | ✓ | ✗ | 始终最后 |

主 agent **14 个** middleware（`make_lead_agent`），subagent **4 个**（ThreadData、Sandbox、Guardrail、ToolErrorHandling）。`create_deerflow_agent` Phase 1 实现 **13 个**（Guardrail 仅支持自定义实例，无内置默认）。

## 执行流程

LangChain `create_agent` 的规则：
- **`before_*` 正序执行**（列表位置 0 → N）
- **`after_*` 反序执行**（列表位置 N → 0）

```mermaid
graph TB
    START(["invoke"]) --> TD

    subgraph BA ["<b>before_agent</b> 正序 0→N"]
        direction TB
        TD["[0] ThreadData<br/>创建线程目录"] --> UL["[1] Uploads<br/>扫描上传文件"] --> SB["[2] Sandbox<br/>获取沙箱"]
    end

    subgraph BM ["<b>before_model</b> 正序 0→N"]
        direction TB
        VI["[10] ViewImage<br/>注入图片 base64"]
    end

    SB --> VI
    VI --> M["<b>MODEL</b>"]

    subgraph AM ["<b>after_model</b> 反序 N→0"]
        direction TB
        CL["[13] Clarification<br/>拦截 ask_clarification"] --> LD["[12] LoopDetection<br/>检测循环"] --> SL["[11] SubagentLimit<br/>截断多余 task"] --> TI["[8] Title<br/>生成标题"] --> SM["[6] Summarization<br/>上下文压缩"] --> DTC["[3] DanglingToolCall<br/>补缺失 ToolMessage"]
    end

    M --> CL

    subgraph AA ["<b>after_agent</b> 反序 N→0"]
        direction TB
        SBR["[2] Sandbox<br/>释放沙箱"] --> MEM["[9] Memory<br/>入队记忆"]
    end

    DTC --> SBR
    MEM --> END(["response"])

    classDef beforeNode fill:#a0a8b5,stroke:#636b7a,color:#2d3239
    classDef modelNode fill:#b5a8a0,stroke:#7a6b63,color:#2d3239
    classDef afterModelNode fill:#b5a0a8,stroke:#7a636b,color:#2d3239
    classDef afterAgentNode fill:#a0b5a8,stroke:#637a6b,color:#2d3239
    classDef terminalNode fill:#a8b5a0,stroke:#6b7a63,color:#2d3239

    class TD,UL,SB,VI beforeNode
    class M modelNode
    class CL,LD,SL,TI,SM,DTC afterModelNode
    class SBR,MEM afterAgentNode
    class START,END terminalNode
```

## 时序图

```mermaid
sequenceDiagram
    participant U as User
    participant TD as ThreadDataMiddleware
    participant UL as UploadsMiddleware
    participant SB as SandboxMiddleware
    participant VI as ViewImageMiddleware
    participant M as MODEL
    participant CL as ClarificationMiddleware
    participant SL as SubagentLimitMiddleware
    participant TI as TitleMiddleware
    participant SM as SummarizationMiddleware
    participant DTC as DanglingToolCallMiddleware
    participant MEM as MemoryMiddleware

    U ->> TD: invoke
    activate TD
    Note right of TD: before_agent 创建目录

    TD ->> UL: before_agent
    activate UL
    Note right of UL: before_agent 扫描上传文件

    UL ->> SB: before_agent
    activate SB
    Note right of SB: before_agent 获取沙箱

    SB ->> VI: before_model
    activate VI
    Note right of VI: before_model 注入图片 base64

    VI ->> M: messages + tools
    activate M
    M -->> CL: AI response
    deactivate M

    activate CL
    Note right of CL: after_model 拦截 ask_clarification
    CL -->> SL: after_model
    deactivate CL

    activate SL
    Note right of SL: after_model 截断多余 task
    SL -->> TI: after_model
    deactivate SL

    activate TI
    Note right of TI: after_model 生成标题
    TI -->> SM: after_model
    deactivate TI

    activate SM
    Note right of SM: after_model 上下文压缩
    SM -->> DTC: after_model
    deactivate SM

    activate DTC
    Note right of DTC: after_model 补缺失 ToolMessage
    DTC -->> VI: done
    deactivate DTC

    VI -->> SB: done
    deactivate VI

    Note right of SB: after_agent 释放沙箱
    SB -->> UL: done
    deactivate SB

    UL -->> TD: done
    deactivate UL

    Note right of MEM: after_agent 入队记忆

    TD -->> U: response
    deactivate TD
```

## 洋葱模型

列表位置决定在洋葱中的层级 — 位置 0 最外层，位置 N 最内层：

```
进入 before_*：   [0] → [1] → [2] → ... → [10] → MODEL
退出 after_*：    MODEL → [13] → [11] → ... → [6] → [3] → [2] → [0]
                          ↑ 最内层最先执行
```

> [!important] 核心规则
> 列表最后的 middleware，其 `after_model` **最先执行**。
> ClarificationMiddleware 在列表末尾，所以它第一个拦截 model 输出。

## 对比：真正的洋葱 vs DeerFlow 的实际情况

### 真正的洋葱（如 Koa/Express）

每个 middleware 同时负责 before 和 after，形成对称嵌套：

```mermaid
sequenceDiagram
    participant U as User
    participant A as AuthMiddleware
    participant L as LogMiddleware
    participant R as RateLimitMiddleware
    participant H as Handler

    U ->> A: request
    activate A
    Note right of A: before: 校验 token

    A ->> L: next()
    activate L
    Note right of L: before: 记录请求时间

    L ->> R: next()
    activate R
    Note right of R: before: 检查频率

    R ->> H: next()
    activate H
    H -->> R: result
    deactivate H

    Note right of R: after: 更新计数器
    R -->> L: result
    deactivate R

    Note right of L: after: 记录耗时
    L -->> A: result
    deactivate L

    Note right of A: after: 清理上下文
    A -->> U: response
    deactivate A
```

> [!tip] 洋葱特征
> 每个 middleware 都有 before/after 对称操作，`activate` 跨越整个内层执行，形成完美嵌套。

### DeerFlow 的实际情况

不是洋葱，是管道。大部分 middleware 只用一个钩子，不存在对称嵌套。多轮对话时 before_model / after_model 循环执行：

```mermaid
sequenceDiagram
    participant U as User
    participant TD as ThreadData
    participant UL as Uploads
    participant SB as Sandbox
    participant VI as ViewImage
    participant M as MODEL
    participant CL as Clarification
    participant SL as SubagentLimit
    participant TI as Title
    participant SM as Summarization
    participant MEM as Memory

    U ->> TD: invoke
    Note right of TD: before_agent 创建目录
    TD ->> UL: .
    Note right of UL: before_agent 扫描文件
    UL ->> SB: .
    Note right of SB: before_agent 获取沙箱

    loop 每轮对话（tool call 循环）
        SB ->> VI: .
        Note right of VI: before_model 注入图片
        VI ->> M: messages + tools
        M -->> CL: AI response
        Note right of CL: after_model 拦截 ask_clarification
        CL -->> SL: .
        Note right of SL: after_model 截断多余 task
        SL -->> TI: .
        Note right of TI: after_model 生成标题
        TI -->> SM: .
        Note right of SM: after_model 上下文压缩
    end

    Note right of SB: after_agent 释放沙箱
    SB -->> MEM: .
    Note right of MEM: after_agent 入队记忆
    MEM -->> U: response
```

> [!warning] 不是洋葱
> 14 个 middleware 中只有 SandboxMiddleware 有 before/after 对称（获取/释放）。其余都是单向的：要么只在 `before_*` 做事，要么只在 `after_*` 做事。`before_agent` / `after_agent` 只跑一次，`before_model` / `after_model` 每轮循环都跑。

硬依赖只有 2 处：

1. **ThreadData 在 Sandbox 之前** — sandbox 需要线程目录
2. **Clarification 在列表最后** — `after_model` 反序时最先执行，第一个拦截 `ask_clarification`

### 结论

| | 真正的洋葱 | DeerFlow 实际 |
|---|---|---|
| 每个 middleware | before + after 对称 | 大多只用一个钩子 |
| 激活条 | 嵌套（外长内短） | 不嵌套（串行） |
| 反序的意义 | 清理与初始化配对 | 仅影响 after_model 的执行优先级 |
| 典型例子 | Auth: 校验 token / 清理上下文 | ThreadData: 只创建目录，没有清理 |

## 关键设计点

### ClarificationMiddleware 为什么在列表最后？

位置最后 = `after_model` 最先执行。它需要**第一个**看到 model 输出，检查是否有 `ask_clarification` tool call。如果有，立即中断（`Command(goto=END)`），后续 middleware 的 `after_model` 不再执行。

### SandboxMiddleware 的对称性

`before_agent`（正序第 3 个）获取沙箱，`after_agent`（反序第 1 个）释放沙箱。外层进入 → 外层退出，天然的洋葱对称。

### 大部分 middleware 只用一个钩子

14 个 middleware 中，只有 SandboxMiddleware 同时用了 `before_agent` + `after_agent`（获取/释放）。其余都只在一个阶段执行。洋葱模型的反序特性主要影响 `after_model` 阶段的执行顺序。
