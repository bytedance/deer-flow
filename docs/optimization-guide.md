# DeerFlow: 分层上下文工程 Agent 框架

> 一句话：DeerFlow 用 middleware 链 + 四象限策略管理 Agent 的有限上下文窗口，是一个开源的、可配置的、通用的 Agent 上下文工程框架。

---

## 第一部分：DeerFlow 现有架构（已有优势）

### 核心设计理念

LLM Agent 的上下文就像一个有限大小的书桌——你同时要放课本（系统指令）、笔记本（记忆）、草稿纸（聊天历史）、工具箱（工具定义）、中间结果（工具输出）和当前作业（用户问题）。书桌不够大时，摆得越多，找东西越慢，做题越容易出错。

DeerFlow 的方案是：**用一条 middleware 流水线来管理书桌上的每样东西**。每个 middleware 负责一件事，串在一起形成完整的上下文管理策略。

### 现有 Middleware 链（11 层）

DeerFlow 已经有一条成熟的 middleware 链，每层各司其职：

```
用户消息进来
  │
  ├─ 1. ThreadDataMiddleware       → 初始化线程数据（workspace/uploads/outputs 路径）
  ├─ 2. UploadsMiddleware          → 处理用户上传的文件，注入到上下文
  ├─ 3. SandboxMiddleware          → 懒加载沙箱环境，tool 第一次用到时才初始化
  ├─ 4. DanglingToolCallMiddleware → 清理上一轮残留的无响应 tool_call
  ├─ 5. SummarizationMiddleware    → 对话太长时自动摘要，替换旧消息
  ├─ 6. TodoListMiddleware         → 管理任务列表（plan mode 下展示 todo）
  ├─ 7. TitleMiddleware            → 自动给对话生成标题
  ├─ 8. MemoryMiddleware           → 对话结束后提取 facts 存入长期记忆
  ├─ 9. ViewImageMiddleware        → 视觉模型才加载，处理图片 tool 输出
  ├─ 10. SubagentLimitMiddleware   → 限制并发子 Agent 数量（默认最多 3 个）
  └─ 11. ClarificationMiddleware   → 拦截追问 tool，中断执行返回给用户
  │
  ▼
  LLM 调用
```

**这条链的好处：**
- **关注点分离**：每个 middleware 只做一件事，互不干扰
- **顺序可控**：middleware 的执行顺序是精心设计的（比如 Sandbox 必须在 tool 之前初始化，Clarification 必须最后执行）
- **hook 机制灵活**：每个 middleware 可以选择在 `before_model`（LLM 调用前）或 `after_model`（LLM 调用后）介入
- **可插拔**：开关一个 middleware 不影响其他的（比如关掉 Summarization 不影响 Memory）

### 工具系统（三类来源，统一接口）

DeerFlow 的工具不是写死的，而是三类来源统一管理：

```
工具来源
├── 1. Config 定义的工具（config.yaml 里配 use: "src.sandbox.tools:bash_tool"）
│   └── bash, ls, read_file, write_file, str_replace
│
├── 2. 内置工具（代码里直接注册）
│   └── present_file, ask_clarification, view_image, task
│
└── 3. MCP 外部工具（extensions_config.json 里配，支持热更新）
    └── 比如飞书、浏览器、自定义 MCP server 的工具
```

**好处：**
- 用户加新工具不用改代码，配置文件加一行就行
- MCP 工具支持热更新——Gateway API 改了配置，LangGraph Server 自动重新加载
- `tool_groups` 分组机制让自定义 Agent 可以只拿一组工具
- 视觉工具（view_image）只在模型支持 vision 时才加载，不白占 token

### 记忆系统（写路径完整）

DeerFlow 的记忆系统已经有完整的写路径：

```
对话结束
  → MemoryMiddleware.after_agent 触发
  → MemoryUpdateQueue 排队
  → MemoryUpdater 用 LLM 提取 facts
  → 写入 memory.json（含 user_context, history, facts[]）

每条 fact 结构：
{
  "content": "用户偏好 pytest 做测试",
  "category": "preferences",
  "confidence": 0.9
}
```

**好处：**
- 用 LLM 提取结构化 facts，不是简单存原文
- 每条 fact 有 category 和 confidence，方便后续筛选
- 异步队列处理，不阻塞主对话流程
- `tiktoken` 精确计数 token，不会超出注入预算

### 子 Agent 隔离（context 隔离 + 资源共享）

DeerFlow 用 `task` tool 派出子 Agent 做独立任务：

```
主 Agent（完整上下文 80K tokens）
  │
  ├─ 调用 task("查看 git log", subagent_type="bash")
  │   └─ 子 Agent：独立上下文（只有 task prompt + 工具），共享沙箱
  │
  ├─ 调用 task("分析代码结构", subagent_type="general-purpose")
  │   └─ 子 Agent：独立上下文，共享沙箱和线程数据
  │
  └─ 主 Agent 继续（拿到子 Agent 结果，主上下文不膨胀）
```

**好处：**
- **上下文隔离**：子 Agent 有自己独立的上下文窗口，不污染主 Agent
- **资源共享**：沙箱、线程数据（workspace 路径）从主 Agent 传递，不重新创建
- **并发控制**：SubagentLimitMiddleware 限制最多 3 个并发，防止资源爆炸
- **防止嵌套**：子 Agent 的 disallowed_tools 里包含 `task`，不会递归创建子子 Agent

### 摘要机制（自动触发）

对话太长时 SummarizationMiddleware 自动触发：

```yaml
summarization:
  enabled: true
  trigger:
    max_tokens: 120000       # 超过 12 万 token 触发
    max_messages: 100        # 超过 100 条消息触发
    max_context_fraction: 0.6  # 上下文超过窗口 60% 触发
  keep:
    system_messages: true    # 保留系统消息
    recent_messages: 10      # 保留最近 10 条
```

**好处：**
- 三种触发条件任一满足就摘要，不会等到窗口溢出
- 保留最近 N 条消息，摘要只替换更早的，保证短期记忆完整
- 全参数可配置，不同场景可以调不同的阈值

### DeerFlow 架构用四象限来看

把上面这些对应到 Write-Select-Compress-Isolate 四象限：

| 象限 | DeerFlow 已有能力 | 对应组件 |
|------|-------------------|---------|
| **Write** | LLM 提取 facts 写入长期记忆 | MemoryUpdater → memory.json |
| **Select** | 工具按 groups 分组加载；视觉工具按模型能力加载 | get_available_tools + tool_groups |
| **Compress** | 对话超长自动摘要；保留最近消息 | SummarizationMiddleware |
| **Isolate** | 子 Agent 独立上下文；沙箱隔离执行环境 | task tool + SubagentLimitMW |
| **基础设施** | 线程数据管理、文件上传处理、悬挂调用清理 | ThreadData / Uploads / DanglingToolCall MW |

---

## 第二部分：新增优化（在好架构上做得更好）

DeerFlow 的 middleware 架构天然支持扩展——加一个新 middleware 不影响已有的。以下 6 个优化就是利用这个能力，在四个象限上进一步增强。

### 优化 1：激活记忆的「读」路径

DeerFlow 的记忆系统写路径很完整（LLM 提取 facts → 结构化存储），但读路径有断点：`format_memory_for_injection` 只注入了 user_context 和 history_summary，**没有注入 facts**。

**改法**：在 `format_memory_for_injection` 里加上 fact 选择逻辑。用 TF-IDF 算当前对话和每条 fact 的相关度，在 token 预算内挑最相关的注入。

**改哪里**：`backend/src/agents/memory/prompt.py`

```python
def format_memory_for_injection(
    memory_data, max_tokens=2000,
    current_context=None,  # 新增：拿当前对话做相关度计算
    alpha=0.6,             # 新增：相关度 vs 置信度的权重
):
    # ... 原有 user_context + history 逻辑不变 ...
    # 新增：从 facts 里选最相关的注入
    facts = memory_data.get("facts", [])
    selected = _select_facts_tfidf(facts, current_context, alpha, budget)
    # 拼接到输出
```

---

### 优化 2：记忆动态更新

现在记忆是 Agent 创建时注入一次。Turn 1 聊 Python，turn 10 聊 React，注入的还是 Python 相关记忆。

**改法**：在 MemoryMiddleware 里新增 `before_model` hook，每次 LLM 调用前根据最近几轮对话重新选择 facts。

**改哪里**：`backend/src/agents/middlewares/memory_middleware.py`

```python
class MemoryMiddleware:
    # 原有：after_agent hook（提取记忆并存储）
    # 新增：
    def before_model(self, state, runtime):
        context = _extract_recent_context(state["messages"], k=3)
        facts_text = format_memory_for_injection(memory, current_context=context)
        # 插入一条 SystemMessage 到 messages 里
```

---

### 优化 3：工具输出全生命周期管理（三层）

工具输出是上下文增长最快的部分。三层管理：

**3a 写入时截断**：tool 返回时立即截断到 3000 tokens。保留前 60% + 后 20%（错误信息通常在尾部），中间省略。

**3b 读取时压缩**：保留最近 3 个 tool 输出完整（hot tail），更早的压缩为一行摘要 `[bash | exit=0 | 234 行 | cmd=npm install]`。

**3c 去重**：同一个 tool + 同样的参数调用过一次，后续直接引用 `[同上次 read_file 结果]`。

**改哪里**：新建 `backend/src/agents/middlewares/tool_output_middleware.py`

三层叠加效果：50K tool 输出 → 约 8.5K，**省 83%**。

---

### 优化 4：摘要后恢复现场

摘要替换旧消息后，Agent 忘了当前在做什么。

**改法**：新建 RehydrationMiddleware，摘要触发后注入一条消息：当前已生成哪些文件、todo 到第几步了、请继续不要重新问。

**改哪里**：新建 `backend/src/agents/middlewares/rehydration_middleware.py`

---

### 优化 5：Token 预算看板

新建 ContextProfiler，在 middleware 链关键位置采集 token 快照（系统指令占多少、记忆占多少、工具定义占多少、工具输出占多少）。可导出 CSV 画图分析。

**改哪里**：新建 `backend/src/agents/middlewares/context_profiler.py`

---

### 优化 6：工具定义多层级管理（三层）

**6a 主 Agent 按需加载**：只加载核心工具 + 一个 `search_tools`，其余按需搜索。50 个工具的 15K tokens 降到 3.5K。

**6b 子 Agent 按任务裁剪**：派子 Agent 时根据 task 描述做 TF-IDF 匹配选工具，不再继承全部 47 个。

**6c 描述渐进缩减**：工具用过 2 次以上后，描述从完整版（~300 tokens）缩短为一句话（~50 tokens）。

**改哪里**：
- 新建 `backend/src/agents/middlewares/tool_schema_middleware.py`（6a + 6c）
- 改动 `backend/src/subagents/executor.py`（6b）

---

## 第三部分：完整 Middleware 链（优化后）

```
用户消息进来
  │
  ├─ ThreadDataMiddleware          → 初始化线程数据
  ├─ UploadsMiddleware             → 处理上传文件
  ├─ SandboxMiddleware             → 懒加载沙箱
  ├─ DanglingToolCallMiddleware    → 清理悬挂 tool call
  ├─ SummarizationMiddleware       → 对话超长自动摘要
  ├─ RehydrationMiddleware         → ★ 摘要后恢复工作现场
  ├─ MemoryMiddleware              → ★ 每次调用前动态注入相关 facts
  ├─ ToolOutputTruncationMW        → ★ tool 返回时截断大输出 (3a)
  ├─ MicroCompactionMiddleware     → ★ 压缩旧 tool 输出 + 去重 (3b+3c)
  ├─ ToolSearchMiddleware          → ★ 按需加载工具定义 + 描述缩减 (6a+6c)
  ├─ ContextProfiler               → ★ 采集 token 分布快照
  ├─ TodoListMiddleware            → 管理 todo 列表
  ├─ TitleMiddleware               → 生成对话标题
  ├─ ViewImageMiddleware           → 处理图片（仅 vision 模型）
  ├─ SubagentLimitMiddleware       → 限制并发子 Agent
  └─ ClarificationMiddleware       → 拦截追问（最后）
  │
  ▼
  LLM 调用（上下文已经过 17 层 middleware 处理）
```

---

## 第四部分：代码改动总览

| # | 改什么 | 文件 | 新建/改动 | 约多少行 |
|---|--------|------|----------|---------|
| 1 | Fact 选择逻辑 | `memory/prompt.py` | 改动 | ~100 |
| 2 | 动态记忆注入 | `middlewares/memory_middleware.py` | 改动 | ~60 |
| 3 | 工具输出三层管理 | `middlewares/tool_output_middleware.py` | **新建** | ~200 |
| 4 | 摘要后恢复现场 | `middlewares/rehydration_middleware.py` | **新建** | ~80 |
| 5 | Token 看板 | `middlewares/context_profiler.py` | **新建** | ~150 |
| 6 | 工具定义多层管理 | `middlewares/tool_schema_middleware.py` | **新建** | ~200 |
| 7 | 子 Agent 任务裁剪 | `subagents/executor.py` | 改动 | ~60 |
| 8 | 配置 | `config/tool_management_config.py` | **新建** | ~50 |
| 9 | Middleware 链串联 | `lead_agent/agent.py` | 改动 | ~30 |
| 10 | 依赖 | `pyproject.toml` | 改动 | ~1 |
| 11 | 评测脚本 | `eval/` 目录 | **新建** | ~700 |
| 12 | 单元测试 | `tests/` | **新建** | ~300 |
| | **合计** | | | **~1970** |

---

## 第五部分：实验设计（证明架构好用且通用）

核心思路：不是"证明我们省了多少 token"，而是**证明 DeerFlow 的分层架构是一个好的、通用的上下文管理方案**。

### 实验 1：架构消融实验 — 每层 middleware 的独立贡献

**目的**：证明 middleware 链里每一层都有用，不是堆砌，而是各层组合产生 1+1>2 的效果。

**方法**：固定 20 轮长对话任务（含文件操作、代码生成、调试），逐层打开/关闭 middleware，观察任务完成质量和 token 效率：

| 配置 | 说明 |
|------|------|
| Bare（只有 LLM + tools） | 无任何 middleware，纯裸跑 |
| + Sandbox + ThreadData | 加上基础设施层 |
| + Summarization | 加上摘要 |
| + Summarization + Rehydration | 加上摘要恢复 |
| + Memory | 加上记忆 |
| + Memory + Dynamic Injection | 加上动态记忆 |
| + ToolOutput (3a+3b+3c) | 加上工具输出管理 |
| + ToolSchema (6a+6b+6c) | 加上工具定义管理 |
| Full Pipeline | 全部开启 |

**指标**：
- 任务完成率（成功/部分/失败）
- 每轮平均 token 数
- 任务完成所需轮数
- 长对话质量衰减曲线（第 5 轮 vs 第 15 轮 vs 第 25 轮的回答质量）

**产出**：Table + 折线图，展示每加一层 middleware 带来的增量效果。

**成本**：~$15-20（用 gpt-4o-mini 跑 ~150 次）

---

### 实验 2：长对话质量保持实验 — 证明架构能扛住长对话

**目的**：大多数 Agent 在 20 轮后质量严重下降（context rot）。证明 DeerFlow 的全流水线能在 50 轮对话中保持稳定质量。

**方法**：构造 3 个 50 轮长对话场景，每 10 轮插入一个质量检测问题：

| 场景 | 内容 | 会触发什么 |
|------|------|-----------|
| 编程助手 | 从零搭建一个 Flask 项目，含 5 个功能模块 | 密集 tool 调用（bash/read/write），会触发 summarization |
| 研究分析 | 读 3 篇论文 PDF，做对比分析，写报告 | 大量 read_file 输出，会触发 MicroCompaction |
| 跨会话个性化 | Session 1 讨论 React，Session 2 讨论 Python，Session 3 混合问 | 测 Memory Injection 和 Fact Selection |

**质量检测点**（每 10 轮问一个需要回忆之前上下文的问题）：
- "我们之前创建的数据库 schema 有哪些字段？"
- "前面报的那个错误是什么原因？"
- "我们的项目结构是怎样的？"

**对比组**：

| 组 | 说明 |
|----|------|
| DeerFlow Full | 全部 middleware 开启 |
| DeerFlow Minimal | 只开基础 middleware（Sandbox + ThreadData + Summarization） |
| Naive（无 middleware） | 直接 LLM + tools，无任何 context 管理 |

**指标**：
- 每个检测点的回答准确率（人工评分 1-5）
- token 增长曲线
- 首次质量明显下降的轮数（"context rot 拐点"）

**产出**：三条质量曲线对比图 + token 增长曲线。核心结论：DeerFlow Full 在第 50 轮仍然保持 4/5 分质量，Naive 在第 15 轮就掉到 2/5。

**成本**：~$20-30

---

### 实验 3：跨任务通用性实验 — 证明架构不是只适合一类任务

**目的**：证明 DeerFlow 的 middleware 框架对不同类型的任务都有效，不是为某一类任务特化的。

**方法**：在 5 类不同任务上运行 DeerFlow，测任务完成质量和 context 效率：

| 任务类型 | 具体任务 | 主要用到哪些 middleware |
|---------|---------|----------------------|
| 代码开发 | 实现一个 TODO 应用（含后端 API + 前端页面） | Sandbox + ToolOutput + SubagentLimit |
| 数据分析 | 分析 CSV 数据集，生成可视化图表和分析报告 | Sandbox + ToolOutput + Memory |
| 文档写作 | 根据代码库生成 API 文档 | Memory + ToolOutput + Summarization |
| 多步调研 | 对比 3 个技术方案的优劣，写推荐报告 | Subagent Isolation + Memory |
| 调试修复 | 给定一个有 bug 的项目，找到并修复 3 个 bug | Sandbox + ToolOutput + Rehydration |

**指标**：
- 任务完成质量（人工评分 1-5）
- 总 token 消耗
- 任务完成轮数
- middleware 命中率（哪些 middleware 在哪些任务类型上实际触发了）

**产出**：雷达图（5 类任务 × 3 个指标）+ middleware 热力图（哪个 middleware 在哪类任务上贡献最大）。

**核心结论**：DeerFlow 的 middleware 链在所有 5 类任务上都能工作，不同任务自动激活不同的 middleware 组合。

**成本**：~$15-20

---

### 实验 4：Context 组成可视化 — 用 Profiler 透视架构效果

**目的**：用 Context Budget Profiler 直观展示"上下文里装了什么"以及"每层 middleware 怎么改变了上下文组成"。

**方法**：在实验 2 的长对话中同时开启 Profiler，记录每轮 LLM 调用前的 token 分布：

```
每轮记录：
{
  "turn": 15,
  "system_prompt": 1200,     # 系统指令
  "memory": 450,             # 注入的记忆
  "history": 8500,           # 聊天历史
  "tool_schemas": 3200,      # 工具定义
  "tool_outputs": 6800,      # 工具输出
  "query": 120,              # 当前用户问题
  "total": 20270
}
```

**产出**：
- 堆叠面积图：6 类 token 随轮数的变化趋势
- 瀑布图：展示每个新 middleware 开启后 token 组成的变化
- 饼图：在第 10 / 20 / 30 / 50 轮时的 token 组成比例

**核心结论**：展示 DeerFlow 如何在 50 轮对话后仍将 total token 控制在窗口的合理范围内。

**成本**：$0（Profiler 是纯本地统计，不调 API）

---

### 实验 5：配置灵活性实验 — 证明 YAML 可配置的价值

**目的**：证明同一套 DeerFlow 框架通过不同配置可以适配不同场景。

**方法**：对同一个任务（20 轮编程助手），测试 3 种预设配置的效果：

| 预设 | 配置重点 | 适用场景 |
|------|---------|---------|
| **省钱模式** | 激进压缩：hot_tail=1, max_cold=50, progressive=true, 按需加载 | 成本敏感、简单任务 |
| **均衡模式** | 默认配置：hot_tail=3, max_cold=100, core_tools 加载 | 日常使用 |
| **质量优先** | 保守压缩：hot_tail=5, max_cold=500, 全量加载工具 | 复杂任务、质量要求高 |

**指标**：任务完成质量 × token 消耗 × API 成本

**产出**：散点图（x=成本, y=质量），展示三种配置的 pareto 前沿。

**核心结论**：用户可以按需选择成本-质量的平衡点，一套框架适配多种需求。

**成本**：~$10

---

### 实验 6：与业界对比 — 定位 DeerFlow 的优势

**目的**：把 DeerFlow 和业界已知方案做对比，明确我们的位置。

**方法**：不需要自己复现 Claude Code / OpenAI（它们闭源），而是通过特征对比 + DeerFlow 自身数据来定位：

| 维度 | DeerFlow | Claude Code | OpenAI | 朴素 LLM+tools |
|------|----------|-------------|--------|----------------|
| 开源 | 是 | 否 | 否 | — |
| 可配置 | 全参数 YAML | 有限 | 阈值 | 无 |
| Tool 输出管理 | 三层 (截断+压缩+去重) | 一层 (MicroCompact) | 一层 (API Compaction) | 无 |
| Tool 定义管理 | 三层 (按需+裁剪+缩减) | 无 | 一层 (Tool Search) | 无 |
| 记忆 | TF-IDF fact selection + 动态注入 | 无 | 无 | 无 |
| Subagent 隔离 | 有 (context 隔离 + 资源共享) | 有 | 不透明 | 无 |
| 50 轮质量保持 | (我们的实验数据) | 不可知 | 不可知 | (我们的 baseline 数据) |
| 额外 LLM 成本 | $0 | $0 | 不透明 | $0 |
| 四象限覆盖 | W+S+C+I | Compress 为主 | Compress+Select | 无 |

**产出**：对比表 + DeerFlow 在各维度的实测数据填入。

**核心结论**：DeerFlow 是首个开源的、四象限全覆盖的、全参数可配置的 Agent 上下文管理框架。不跟闭源产品比绝对性能（没法测），而是强调**开源 + 可配置 + 通用性**这个独特定位。

**成本**：$0（纯数据整理）

---

### 实验成本汇总

| 实验 | 证明什么 | 成本 |
|------|---------|------|
| 1. 架构消融 | 每层 middleware 的独立贡献 | ~$15-20 |
| 2. 长对话质量 | 50 轮对话仍保持质量 | ~$20-30 |
| 3. 跨任务通用 | 5 类任务都好用 | ~$15-20 |
| 4. Context 可视化 | 直观展示架构效果 | $0 |
| 5. 配置灵活 | YAML 配置的 pareto 前沿 | ~$10 |
| 6. 业界对比 | 明确 DeerFlow 的定位 | $0 |
| **总计** | | **~$60-80** |

---

## 第六部分：配置示例

所有功能通过 YAML 配置开关，不改代码：

```yaml
# 记忆
memory:
  retrieval_method: "tfidf"
  similarity_weight: 0.6
  inject_frequency: "before_model"

# 工具输出管理
tool_output_management:
  enabled: true
  max_tokens_per_tool: 3000
  truncation_strategy: "head_tail"
  hot_tail_size: 3
  max_cold_tokens: 100
  deduplication_enabled: true

# 工具定义管理
tool_schema_management:
  enabled: true
  core_tools: ["task", "ask_clarification", "present_file"]
  max_search_results: 5
  subagent_task_aware: true
  subagent_max_tools: 15
  progressive_description: true

# 摘要
summarization:
  trigger:
    max_tokens: 120000
    max_messages: 100

# 摘要恢复
rehydration:
  enabled: true
  include_artifacts: true
  include_todos: true
```
