# DeerFlow 2.0: A Super Agent Harness with Layered Context Engineering

## 论文定位：发布 DeerFlow 2.0 整体架构 + 上下文工程增强

---

## 0. 总体思路

### 论文故事线：从 Deep Research 到 Super Agent Harness

**DeerFlow 1.0** 最初定位为深度研究框架——不是抓一把搜索结果做摘要的 Chatbot，而是让 AI 像研究员一样制定调研计划、分头搜集信息、交叉验证、交付有结构有引用的报告。为此设计了 5 个固定角色的 Research Agent Team（Coordinator → Planner → Researcher / Coder → Reporter），用 LangGraph 的 StateGraph + Handoffs 编排协作。

**社区的玩法迅速超出预期**：有人搭数据分析 pipeline，有人批量生成 PPT，有人做内容工厂，有人接内部系统做运维巡检。这些用法千差万别，但都指向同一件事——它们需要 Agent 持续规划、调度子任务、操作文件、执行代码，最终交付完整产出物。大家在用的不是 DeerFlow 的"Research"能力，而是它底下那套让 Agent 能真正做事的运行时基础设施。

**这让我们意识到**：Deep Research 只是 DeerFlow 的第一个技能（Skill），不是它的全部。

于是我们做了一个大胆的决定：**从头重写**。DeerFlow 2.0 与 1.0 不共享任何一行代码，完全重新设计架构。不再定位为 Deep Research 框架，而是一个 **Super Agent Harness**——开箱即用、完全可扩展的超级智能体运行时。

### 什么是 Harness

Harness 是一个相对较新的概念（对做过 SWE-bench 评测的人不陌生），可以理解为 "batteries included" 的 Agent 运行时环境。与 Framework（如 LangChain、LangGraph）相比，Harness 更加 opinionated——不仅提供抽象，还内置最佳实践。

一个典型的 Harness 包含（参考 LangChain Deep Agents）：
1. 内置 Planning Tool
2. Compaction 机制（上下文压缩）
3. File System 工具
4. Starter Prompts
5. Memory 系统
6. Sub-agents 机制

DeerFlow 2.0、LangChain DeepAgents 属于 Harness；LangChain、LangGraph 属于 Framework。DeerFlow 2.0、OpenClaw、Claude Code 以及所有 Coding Agent 都是 Long-horizon Agent（长程智能体）。

### 论文核心贡献

本文的贡献不是"发现了缺口然后修补"，而是：

1. **发布 DeerFlow 2.0 架构**（第一贡献）：展示从 1.0 Multi-Agent StateGraph 到 2.0 Single Lead Agent + Middleware + Sub-agent + Skills 的架构演进，阐述每个设计决策的原因和优势
2. **形式化为 LayeredContext 框架**：将 DeerFlow 2.0 的 middleware 链形式化为 Write-Select-Compress-Isolate 四象限分类法，证明其天然覆盖全部四象限
3. **系统性验证**：通过四个标准 benchmark（GAIA / SWE-bench Verified / HumanEval / DeepPlanning）通用性评测、长对话质量保持、消融实验等，证明 DeerFlow 2.0 是一个好用且通用的 Agent Harness

### 论文框架：Write-Select-Compress-Isolate 四象限

借鉴 LangChain 的上下文工程分类和业界主流产品实践：

```
            ┌─────────────────────────────────────────┐
            │      Agent Context Engineering          │
            ├────────────────┬────────────────────────┤
            │                │                        │
  ┌─────────┴──────┐  ┌─────┴──────────┐             │
  │  Write         │  │  Select        │             │
  │ 写到外部存储   │  │  选进上下文     │                │
  │                │  │                │             │
  │ - Scratchpad   │  │ - Memory recall│             │
  │ - Long-term    │  │ - Tool RAG     │             │
  │   memory       │  │ - Knowledge    │             │
  └────────────────┘  └────────────────┘             │
  ┌─────────────────┐  ┌────────────────┐            │
  │  Compress       │  │  Isolate       │            │
  │ 压缩上下文     │  │  隔离上下文     │            │
  │                │  │                │             │
  │ - Summarization│  │ - Multi-agent  │             │
  │ - MicroCompact │  │ - Sandbox      │             │
  │ - Trimming     │  │ - State schema │             │
  └────────────────┘  └────────────────┘             │
            └─────────────────────────────────────────┘
```

### 投稿目标

| 会议/Track | 适配度 | 说明 |
|-----------|--------|------|
| AAAI IAAI | 高 | 应用驱动，强调工程实践，接受系统描述+优化 |
| AAAI Demo | 高 | 4 页，强调系统演示和工程质量 |
| ICSE SEIP / FSE Industry | 高 | 软件工程实践 track，非常适合 |

---

## 1. DeerFlow 架构：从 1.0 到 2.0

### 1.1 DeerFlow 1.0：Multi-Agent StateGraph

1.0 是一个典型的 Multi-Agent Supervisor 架构，用 LangGraph StateGraph 把 5 个固定角色串联：

```
Coordinator → Planner → Researcher / Coder (并行) → Reporter
```

- **Coordinator**：接待用户、处理闲聊、判断意图后 Handoff 给 Planner
- **Planner**：分解研究课题、制定计划、经用户确认后派发
- **Researcher**：核心 ReAct Agent，联网搜索和爬取网页
- **Coder**：Python REPL 执行代码，做数据分析
- **Reporter**：汇总所有上下文，撰写最终报告

**1.0 的局限**（随着社区场景扩展暴露）：
1. **角色固化**：5 个 Agent 职责写死。想加"设计师 Agent"或"运维 Agent"？得改图、加节点、调边——本质上是改框架
2. **上下文浪费**：所有 Agent 共享同一份 State，Researcher 搜回来的大段网页内容 Reporter 不需要但就在那里占 token
3. **扩展性差**：想做 Deep Research 以外的事，要么往图里硬塞节点，要么另起炉灶

这些不是 bug，而是架构选型带来的天花板。

### 1.2 DeerFlow 2.0：Lead Agent + Middleware + Sub-agent + Skills

2.0 做了根本性转变：从固定角色的 Multi-Agent 图，变为 **Single Lead Agent + 中间件链（ Layered Context Engineering） + 动态 Sub-agent + 可插拔 Skills**。

#### ① Lead Agent：唯一的入口

只有一个 Agent——Lead Agent。通过 `create_agent()` 创建：

```python
# langgraph.json
{ "graphs": { "lead_agent": "src.agents:make_lead_agent" } }

# src/agents/lead_agent/agent.py
def make_lead_agent(config: RunnableConfig):
    return create_agent(
        model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
        tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled),
        middleware=_build_middlewares(config),
        system_prompt=apply_prompt_template(...),
        state_schema=ThreadState,
    )
```

四个参数决定 Agent 的一切：
- **model**：动态选择的 LLM，支持 Thinking 模式和视觉能力
- **tools**：动态组装——沙箱工具 + 内置工具 + MCP 工具 + 社区工具 + Sub-agent 工具
- **middleware**：11 层中间件链
- **system_prompt**：动态生成，按需注入 Skill 列表、Sub-agent 指令和用户记忆

**1.0 的能力分散在 5 个 Agent 节点和边上；2.0 的能力集中在一个 Agent 的工具集和中间件链上。** 想扩展能力？加一个 Tool 或 Skill 就行，不用动图。Agent 和 Tools 全部可以在 `config.yaml` 中"增删改替"。

#### ② 11 层 Middleware 链：Agent 的神经系统

每次 Agent 调用都经过精心编排的 Middleware 链，负责上下文管理、状态同步、资源分配：

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

```python
def _build_middlewares(config: RunnableConfig):
    middlewares = [
        ThreadDataMiddleware(),        # 1. 创建线程目录结构
        UploadsMiddleware(),           # 2. 注入新上传的文件
        SandboxMiddleware(),           # 3. 分配沙箱
        DanglingToolCallMiddleware(),  # 4. 修补中断的工具调用
    ]
    # 5. 上下文摘要（可选）
    # 6. TodoList 计划模式（可选）
    # 7. 自动生成会话标题
    # 8. 异步记忆更新
    # 9. 图像注入（视觉模型）
    # 10. Sub-agent 并发限流
    # 11. 用户澄清拦截（必须最后）
    middlewares.append(ClarificationMiddleware())
    return middlewares
```

**顺序不是随意的**：ThreadDataMiddleware 必须在 SandboxMiddleware 之前（沙箱需要线程 ID）；ClarificationMiddleware 必须在最后（通过 `Command(goto=END)` 中断执行流）。

**为什么好**：
- **可插拔**：任何一层通过 YAML 配置开关，不影响其他层
- **关注点分离**：横切关注点（上传、沙箱、记忆、摘要、限流）与 Agent 核心逻辑完全解耦
- **执行顺序保障**：before_model 按链序正向执行，after_model 反向执行
- **天然覆盖四象限**：Write（MemoryMiddleware 写路径）、Select（MemoryMiddleware 读注入）、Compress（SummarizationMiddleware）、Isolate（SubagentLimitMiddleware）

#### ③ 三类工具统一管理：Config + MCP + Built-in

```
Tool 来源:
├── Config-defined tools  ─ YAML 声明，运行时动态实例化（web_search, crawl 等）
├── MCP tools             ─ Model Context Protocol，外部服务注册（browser, 搜索引擎等）
└── Built-in tools        ─ task (子agent), ask_clarification, present_file, view_image
```

加上沙箱内置的 5 个工具：`bash`、`ls`、`read_file`、`write_file`、`str_replace`。

**为什么好**：
- **统一接口**：三类工具对 LLM 暴露相同的 schema 格式，模型不感知来源差异
- **分组管理**：`tool_groups` 机制按场景分组，一个 group 可整体启用/禁用
- **MCP 协议扩展**：支持任意外部工具接入，不需要修改核心代码
- **config 驱动**：`config.yaml` 中增删改替，不改代码

#### ④ 可插拔 Skill 体系：渐进式加载

Skills 是 Agent 能力的核心扩展单元。一个 Skill 就是一个目录，里面放一个 SKILL.md：

```
/mnt/skills/
├── public/                          ← 内置 Skills
│   ├── deep-research/SKILL.md       ← DeerFlow 的老本行
│   ├── data-analysis/SKILL.md       ← DuckDB + SQL/Python
│   ├── chart-visualization/SKILL.md
│   ├── web-design-guidelines/SKILL.md
│   ├── image-generation/SKILL.md
│   ├── video-generation/SKILL.md
│   ├── podcast-generation/SKILL.md
│   ├── ppt-generation/SKILL.md
│   ├── github-deep-research/SKILL.md
│   └── skill-creator/SKILL.md       ← 用 AI 创建新 Skill
└── custom/                          ← 用户自定义 Skills
    └── your-custom-skill/SKILL.md
```

**渐进式加载**：只有当任务需要时才加载对应 Skill，不一股脑全塞进上下文。一个 Skill 通常由若干 Markdown + Python/Node.js/Shell 脚本 + 模板组成，模型按需加载，拒绝 Token 爆炸。

**为什么好**：
- **不是写死的 Agent 角色**：1.0 的 Researcher/Coder/Reporter 是固定的；2.0 的 deep-research/data-analysis/web-design 是可插拔的
- **社区可扩展**：放进 `skills/custom/` 目录即可使用
- **Token 友好**：渐进式加载，即使在 token 敏感的模型上也高效

#### ⑤ 沙箱化执行环境

每个任务运行在隔离沙箱中，拥有完整文件系统和 Bash 执行能力：

```
/mnt/user-data/
├── uploads/          ← 用户上传的文件
├── workspace/        ← Agent 的工作目录
└── outputs/          ← 最终交付物
```

三种运行模式：
- **Local**：直接宿主机执行，适合开发调试
- **Docker**（推荐）：独立容器，完全隔离（使用字节跳动开源 AIO Sandbox）
- **Kubernetes**：Provisioner 服务在 K8s Pod 中执行，适合生产环境

Agent 看到的路径始终是 `/mnt/user-data/...` 和 `/mnt/skills/...`，底层自动完成虚拟路径到物理路径的双向映射。同一套 Skill/代码在本地开发和容器部署中无需修改。

**为什么好**：
- **Agent 有自己的"计算机"**：不只"会说话"，能读写文件、执行命令、运行脚本、安装依赖
- **隔离安全**：会话之间零污染
- **文件系统即外部存储**：上下文窗口是内存，文件系统是磁盘——需要时换入换出

#### ⑥ Sub-agent 执行引擎

Lead Agent 通过 `task` 工具委派子任务给 Sub-agent。`SubagentExecutor` 采用双线程池架构：

```python
_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")
_execution_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-exec-")
```

内置两种 Sub-agent：
- **general-purpose**：通用型，继承父 Agent 工具（除 task 本身），最多 50 轮
- **bash**：命令行专家，只配备沙箱工具，最多 30 轮

最多 3 个并行执行，15 分钟超时。

**为什么好**：
- **上下文隔离**：Sub-agent 看不到主 Agent 对话历史，只拿到 task prompt——子 Agent 越专注结果越好
- **资源共享**：通过 `thread_data` 共享沙箱和文件路径（`lazy_init=True` 避免重复分配）
- **精简 Middleware**：Sub-agent 只配备 2 个 Middleware（ThreadData + Sandbox），不需要 Lead Agent 的完整基础设施
- **并发控制**：`SubagentLimitMiddleware` 限制同时运行数量
- **分布式追踪**：每个 Sub-agent 通过 `trace_id` 串联

#### ⑦ ThreadState：Agent 的"内存"

不再是 1.0 只有 `messages` 的简单字典：

```python
class ThreadState(AgentState):
    sandbox: SandboxState          # 沙箱 ID
    thread_data: ThreadDataState   # 工作目录路径
    title: str                     # 会话标题
    artifacts: list[str]           # 产出物路径（自动去重 Reducer）
    todos: list                    # 计划模式任务列表
    uploaded_files: list[dict]     # 上传的文件
    viewed_images: dict            # 已查看的图像（base64，空字典清空 Reducer）
```

`artifacts` 和 `viewed_images` 使用自定义 Reducer 处理合并——前者自动去重，后者支持清空已处理图像。在 long-horizon 任务中保证状态一致性。

#### ⑧ 长期记忆：LLM 提取 → 结构化存储

```
对话结束 → MemoryMiddleware.after_agent
         → MemoryUpdateQueue (异步, 去重, 防抖)
         → MemoryUpdater (LLM 调用)
         → 提取 facts: { content, category, confidence }
         → 原子写入 memory.json
```

记忆分三个区块：
- **用户画像**：工作背景、偏好、关注点
- **时间线**：近期互动摘要、历史背景
- **事实库**：具体知识点，含置信度评分（0.7-1.0）和分类标签

**为什么好**：
- **LLM 做提取**：不是保存对话原文，而是提取结构化 facts
- **异步不阻塞**：queue + 去重 + 防抖，不影响响应延迟
- **原子写入**：不因意外中断损坏数据
- **token 预算**：`max_injection_tokens` 配置上限，`tiktoken` 精确计数
- **"用得越多越懂你"**：跨会话记住偏好、风格、知识

#### ⑨ 参数化摘要机制

```yaml
summarization:
  enabled: true
  token_threshold: 120000      # 超 120K tokens 触发
  max_messages_threshold: 30   # 或超 30 条消息触发
  keep_n_recent: 5             # 保留最近 5 条
  keep_system: true            # 始终保留 system prompt
```

三种触发条件（token/message/fraction），任一满足即触发。保留 system prompt + 最近 N 条 + LLM 摘要。全参数 YAML 可配。

### 1.3 DeerFlow 1.0 vs 2.0 对比

| 维度 | 1.0 | 2.0 |
|------|-----|-----|
| **架构模式** | Multi-Agent StateGraph（Supervisor） | Single Lead Agent + Middleware + Sub-agent with Skills |
| **Agent 数量** | 5 个固定角色 | 1 个 Lead Agent + N 个动态 Sub-agent |
| **能力扩展** | 改图、加节点 | 加 Skill 或 Tool，无需改架构 |
| **上下文管理** | 全局共享 State | Sub-agent 隔离 + 11 层 Middleware 管理 |
| **执行环境** | Python REPL（仅 Coder） | 完整沙箱（所有 Agent 共享） |
| **记忆** | 无 | 跨会话长期记忆（LLM 提取 + 结构化存储） |
| **并发模型** | 图节点顺序/并行执行 | 双线程池 + 异步调度 |
| **Skill 体系** | 无（能力写死在 Agent 角色里） | 可插拔 Skills，渐进式加载 |
| **配置化** | 有限 | 全参数 YAML（Agent/Tools/Middleware 均可配） |

### 1.4 DeerFlow 2.0 的四象限覆盖

| 象限 | 2.0 已有实现 | 机制 |
|------|-------------|------|
| **Write** | MemoryMiddleware → MemoryUpdater → memory.json | LLM 提取 facts + 异步写入 + 原子存储 |
| **Select** | MemoryMiddleware → format_memory_for_injection | token 预算内注入 memory |
| **Compress** | SummarizationMiddleware | 三种触发条件 + keep 策略 |
| **Isolate** | SubagentLimitMiddleware + task_tool + 沙箱隔离 | 隔离历史 + 过滤工具 + 并发控制 + 文件系统隔离 |

DeerFlow 2.0 不是一个需要"修补"的系统，而是一个**架构设计已经到位的分层 Harness**。下面的 4 个增强模块是在这个好架构上做得**更好**。

---

## 2. 业界上下文策略调研

### 上下文策略全景

| 产品/论文 | 策略 | 核心机制 | 象限 | 开源 | 额外LLM成本 |
|----------|------|---------|------|------|------------|
| **Claude Code** — MicroCompact | Tool 输出 hot/cold 分离 | 最近 K 个工具输出完整保留（hot tail），更早的写入磁盘只留路径引用（cold）。轻量级，不需要额外 LLM 调用，零成本。被社区逆向工程发现（Decode Claude 项目） | Compress | 否 | $0 |
| **Claude Code** — Auto-Compact | 全局 LLM 摘要 + 状态恢复 | 上下文接近上限时触发 LLM 做全局摘要，然后重读最近 5 文件 + 恢复 todo + 注入"继续执行"指令（Rehydration）。比 MicroCompact 更重，需要额外 LLM 调用 | Compress | 否 | 中 |
| **Anthropic API** — Tool Result Clearing | API 级 tool 输出清理 | 超阈值后按时间序清理旧 tool 结果，替换为占位符 | Compress | 否(API) | $0 |
| **OpenAI Responses API** — Compaction | 服务端压缩 | 生成加密 compaction item，下轮只带此 item 继续 | Compress | 否(API) | 不透明 |
| **OpenAI** — Tool Search | 动态工具发现 | `defer_loading: true` + tool_search 按需加载 tool 定义 | Select | 否(API) | $0 |
| **Devin (Cognition)** | 上下文焦虑管理 | "1M token trick" 消除焦虑；增量式 delta 摘要 | Compress | 否 | 高 |
| **ACON** (Microsoft, ICLR'26 under review) | 压缩指导语优化 | LLM 分析成功/失败轨迹对，迭代优化压缩 guidelines；蒸馏到小模型 | Compress | 是 | 高(训练) |
| **CAT / SWE-Compressor** | 上下文即工具 | 将压缩暴露为 agent 可调用的 tool（主动压缩）；57.6% SWE-Bench | Compress | 是 | 高(训练) |
| **Active Context Compression** (Focus Agent) | 自主压缩决策 | Agent 自主决定何时整合知识到 Knowledge block + 裁剪历史；22.7% token 减少 | Compress | 是 | 中 |
| **MemTool** (2025) | 工具短期记忆管理 | 3 种模式（Autonomous/Workflow/Hybrid）动态移除不再需要的 tool 定义 | Select | 是 | $0 |
| **MEM1** (MIT, ICLR 2026 poster) | RL 恒定大小记忆 | 强化学习学习维护固定大小内部状态；3.5× 性能提升 + 3.7× 内存减少 | Compress | 是 | 高(训练) |
| **SWE-Pruner** (2025) | 神经网络代码裁剪 | 0.6B skimmer 按任务目标选择相关代码行；23-54% token 减少 | Select | 是 | 低 |
| **ACE** (ICLR 2026) | 可演化 playbook | 将 context 视为可演化的 playbook，offline+online 优化 | Select | 是 | 中 |
| **Windsurf — SWE-grep** | 训练模型快速检索 | 替代 60%+ 的首轮搜索时间 | Select | 部分 | 低 |
| **Spring AI** — Dynamic Tool Discovery | Tool RAG | TF-IDF/embedding/关键词搜索 tool 描述；34-64% token 减少 | Select | 是 | $0 |
| **AgeMem** (2025) | 统一记忆管理 | 长短期记忆为 tool 动作 + 渐进式 RL | Write+Select | 是 | 中 |
| **Agent Focus** (agentfocus.dev) | Relay-race 持久知识 | 保持 50-150K token 甜蜜区；每次 session 渐进精炼知识 | Write+Compress | 部分 | 中 |
| **LangChain** | 四象限框架 | Write-Select-Compress-Isolate 分类法 | 框架 | 是 | — |
| **Anthropic Blog** (Sep 2025) | 上下文工程指南 | Compaction + 结构化笔记 + Sub-agent；"有限注意力预算"概念 | 框架 | — | — |

### DeerFlow 2.0 四象限覆盖情况

| 象限 | 2.0 已有能力 | 当前状态 |
|------|-------------|---------|
| **Write → Select** | MemoryUpdater 提取 facts 存入 memory.json | facts 已存储，注入逻辑依赖 `format_memory_for_injection` |
| **Select (Tools)** | tool_groups 分组管理 + 三类工具统一接口 | 静态加载，tool schema 为固定 token 成本 |
| **Compress (输出)** | SummarizationMiddleware 参数化摘要 | 对话级摘要，tool 输出无专项压缩 |
| **Isolate** | SubagentLimitMiddleware + task_tool（隔离 + 黑名单） | subagent 上下文已隔离，工具按静态黑名单过滤 |

---

## 3. 论文标题与摘要

### Title

**DeerFlow 2.0: From Deep Research to Long-Horizon Super Agent Harness with Layered Context Engineering**

备选：**LayeredContext: Systematic Context Engineering for an Open-Source Long-Horizon Agent Harness**

### Abstract (~250 词)

> Long-horizon LLM agents—those that plan, delegate sub-tasks, execute
> code, and deliver structured artifacts over extended sessions—demand
> systematic management of finite context windows. We present DeerFlow
> 2.0, an open-source Super Agent Harness that evolved from a
> multi-agent deep research framework (DeerFlow 1.0) into a
> general-purpose long-horizon agent runtime. The architectural
> evolution—from a fixed 5-agent StateGraph to a single Lead Agent with
> an 11-layer middleware pipeline, dynamic sub-agents, pluggable Skills,
> sandboxed execution, and cross-session memory—addresses the
> extensibility, context isolation, and scalability limitations of the
> multi-agent paradigm. We formalize DeerFlow 2.0's middleware
> architecture as the LayeredContext framework, organized around the
> Write-Select-Compress-Isolate taxonomy, and show that its existing
> design natively covers all four quadrants: LLM-based fact extraction
> (Write), token-budgeted memory injection (Select), parameterized
> multi-trigger summarization (Compress), and sub-agent context
> isolation with resource sharing (Isolate). Building on this
> Through experiments on four standard benchmarks
> (GAIA, SWE-bench Verified, HumanEval, and DeepPlanning), long-dialogue
> quality preservation over 50+ turns, middleware ablation, and
> configuration flexibility analysis, we demonstrate that DeerFlow 2.0
> serves as an effective, configurable, and general harness for agent
> context management. All code is
> open-sourced.

---

## 4. 论文结构（8+1 页）

```
1. Introduction                                               (1.0p)
   - Long-horizon Agent 的兴起与上下文挑战
   - DeerFlow 的演进故事：1.0 → 2.0
   - Harness vs Framework
   - 贡献列表
2. DeerFlow Architecture (★ 第一贡献)                         (2.0p)
   2.1 DeerFlow 1.0: Multi-Agent StateGraph 及其局限
   2.2 DeerFlow 2.0: Lead Agent + Middleware + Sub-agent + Skills
       2.2.1 Single Entry Point: Lead Agent
       2.2.2 11-Layer Middleware Pipeline
       2.2.3 Unified Tool System (Config + MCP + Built-in)
       2.2.4 Pluggable Skill System with Progressive Loading
       2.2.5 Sandboxed Execution Environment
       2.2.6 Sub-agent Execution Engine (Dual Thread Pool)
       2.2.7 ThreadState Design
       2.2.8 Long-term Memory (LLM Extraction → Structured Storage)
       2.2.9 Parameterized Summarization
   2.3 Architecture Comparison: 1.0 vs 2.0
   2.4 Four-Quadrant Coverage Analysis
3. Industry Survey                                            (0.8p)
   3.1 Industry Context Strategies (18 strategies)
   3.2 Write-Select-Compress-Isolate Framework
   3.3 DeerFlow 2.0 四象限覆盖分析
4. Evaluation (★ 证明 Harness 好用且通用)                     (2.0p)
   4.1 Exp 1: 标准 Benchmark 评测（GAIA / SWE-bench Verified / HumanEval / DeepPlanning）
   4.2 Exp 2: 长对话质量保持（3 场景 × 50 轮抽取式问答）
   4.3 Exp 3: Middleware 消融实验
   4.4 Exp 4: 与业界方案对比（Feature Matrix + 策略量化）
5. Related Work                                               (0.8p)
6. Conclusion                                                 (0.2p)
References                                                    (1.0p)
```

---

## 5. 各 Section 详细内容

### Section 1: Introduction (1.0p)

**Para 1 — Long-horizon Agent 的兴起**:
LLM Agent 正在从"一问一答"走向"持续规划、调度子任务、操作文件、执行代码、交付完整产出物"的 long-horizon 模式。无论是 Claude Code、Codex CLI、OpenClaw 还是 DeerFlow，它们面临的共同挑战是：上下文窗口是有限资源，Agent 需同时承载系统指令、长期记忆、对话历史、工具定义、工具输出、当前查询六类信息。Anthropic 指出 LLM 存在"有限注意力预算"——context rot 让长时程任务质量不断衰减。

**Para 2 — Harness：不止于 Framework**:
LangChain 作者 Harrison 在红杉播客中说："模型变强了，我们也积累了更多关于如何构建 harness 的经验。这就是为什么 Long-horizon Agent 开始真正 work 了。"Harness 与 Framework 的区别：Framework 提供抽象，Harness 内置最佳实践。当前缺少一个**开源的、系统描述并验证的** Agent Harness 架构。学术界聚焦单一上下文优化（ACON、CAT、MEM1），工业界有丰富实践但多闭源。

**Para 3 — DeerFlow 的演进故事**:
DeerFlow 1.0 作为 Deep Research 框架，用 5 个固定角色的 Multi-Agent StateGraph 服务深度研究场景。社区将其推向数据分析、PPT 生成、运维巡检等远超预期的用途后，我们意识到 Deep Research 只是第一个 Skill。DeerFlow 2.0 从头重写，架构从固定角色图变为 Single Lead Agent + 11 层 Middleware + 动态 Sub-agent + 可插拔 Skills + 沙箱执行 + 跨会话记忆——一个完整的 Super Agent Harness。

**Para 4 — 贡献**:
- DeerFlow 2.0 的完整架构描述：从 1.0 到 2.0 的演进动机、设计决策和优势分析
- LayeredContext 框架：将 Middleware 链形式化为 Write-Select-Compress-Isolate 四象限，证明天然全覆盖
- 系统性验证：四个标准 benchmark（GAIA / SWE-bench Verified / HumanEval / DeepPlanning）通用性评测、长对话质量保持、消融、配置灵活性
- 全部开源，全参数 YAML 可配置

### Section 2: DeerFlow Architecture (2.0p) ★ 第一贡献

**2.1 DeerFlow 1.0** (0.3p):
- StateGraph 架构图：5 个固定角色、Handoffs 模式
- 社区扩展场景（数据分析/PPT/运维巡检）暴露的三个局限

**2.2 DeerFlow 2.0** (1.2p):
- Lead Agent 唯一入口：`create_agent()` 的 4 个参数（model/tools/middleware/prompt）
- 11 层 Middleware 逐层说明（含顺序依赖分析）
- 三类工具统一管理 + tool_groups 分组
- Skill 体系：渐进式加载、目录结构、出厂 Skills 列表
- 沙箱化执行环境：3 种模式、虚拟路径映射、5 个内置工具
- Sub-agent 执行引擎：双线程池、2 种 Sub-agent 类型、精简 Middleware
- ThreadState 设计：自定义 Reducer
- 长期记忆：三区块、异步队列、原子写入
- 参数化摘要

**2.3 Architecture Comparison** (0.3p):
- 1.0 vs 2.0 对比表（9 个维度）
- 关键设计决策的原因阐述

**2.4 Four-Quadrant Coverage** (0.2p):
- 分析 2.0 如何天然覆盖 Write-Select-Compress-Isolate
- 与 LangChain DeepAgents、Claude Code 的覆盖度对比

### Section 3: Industry Survey (0.8p)

- 18 种上下文策略全景调研表（Write-Select-Compress-Isolate 分类）
- DeerFlow 2.0 四象限覆盖分析：天然覆盖的机制与当前边界

---

## 6. Evaluation (2.0p) — 证明 Harness 好用且通用

**核心原则**：不是只证明"省了多少 token"，而是从多个维度证明 DeerFlow 2.0 作为 Agent Harness 的**架构优势、通用性和可配置性**。

### 6.1 Exp 1: 标准 Benchmark 评测

**目的**：在四个广泛认可的标准 benchmark 上评测 DeerFlow 2.0，证明同一套配置能在工具使用、软件工程、代码生成、多步规划等截然不同的任务类型上均保持竞争力——这是"通用 Harness"最有说服力的证据。

**公平性设计**：
- **同一份 YAML**：四个 benchmark 使用完全相同的 `config.yaml`（balanced 预设），不针对特定 benchmark 单独调参
- **同一个模型**：统一使用同一 LLM（如 Claude Sonnet 4），`temperature=0`（确保可复现）
- **多次运行**：每个 benchmark 运行 **3 次**，报告 mean ± std，消除随机性
- **对比配置**：Full Pipeline vs Bare（关掉所有 Middleware 增强），量化 Harness 的贡献

#### 四个 Benchmark 的具体定义

| Benchmark | 测试能力 | 规模 | 指标 | 与 DeerFlow 的关联 |
|-----------|---------|------|------|-------------------|
| **GAIA** (General AI Assistants) | 工具使用 + 网络浏览 + 多步推理 | validation split，约 165 题，分 Level 1/2/3 | Exact Match (%) | 直接考察 Web Search / MCP 工具 + Sub-agent 规划能力 |
| **SWE-bench Verified** | 真实 GitHub issue 修复 | 500 个人工验证实例 | Resolve Rate (%) | 考察沙箱执行（bash/read/write） + 代码推理 + Tool Output 管理 |
| **HumanEval** | 代码生成 | 164 个函数级编程题 | pass@1 (%) | 考察基础 Coding 能力 + 沙箱执行 + 测试验证 |
| **DeepPlanning** | 长程多步规划 | 标准测试集 | Task Success Rate (%) | 直接考察 Lead Agent 的规划能力 + Sub-agent 任务分解 |

**为什么选这四个**：

- **GAIA**：覆盖 web + tool use + 多步推理，是衡量 Harness 通用工具使用能力的标准；Level 1-3 梯度恰好对应 DeerFlow 的轻量/中等/复杂任务路径
- **SWE-bench Verified**：最权威的软件工程 Agent benchmark，直接考验 DeerFlow 最核心的沙箱执行 + 代码修复能力；Verified 子集 500 例，去除了原始数据集中测试不可靠的样本，结果更可信
- **HumanEval**：基础代码生成的标准衡量，与 SWE-bench 形成互补（HumanEval 测函数级生成，SWE-bench 测系统级修复）
- **DeepPlanning**：专为 Long-horizon Agent 设计的规划 benchmark，与 DeerFlow 2.0 的 Sub-agent + Todo 规划体系高度契合

#### 指标定义

**主指标：benchmark 原生指标（零人工，100% 可复现）**

```python
# GAIA: Exact Match
def score_gaia(response: str, ground_truth: str) -> int:
    return 1 if response.strip().lower() == ground_truth.strip().lower() else 0
# 报告: Level1 EM% / Level2 EM% / Level3 EM% / Overall EM%

# SWE-bench Verified: Resolve Rate
# 使用官方 harness 评测（docker 运行 pytest，检查 patch 是否通过测试套件）
# 报告: resolve_rate = resolved_count / total_instances

# HumanEval: pass@1
# 每题生成 1 个解，检查所有测试用例是否全部通过
def pass_at_1(problem: dict, completion: str) -> bool:
    return run_tests(problem["test"], completion, timeout=10)
# 报告: pass@1 = passed / 164

# DeepPlanning: Task Success Rate
# 使用 benchmark 官方评测脚本，检查最终状态是否满足目标条件
# 报告: success_rate = success / total_tasks
```

**辅助指标：Token 消耗与 Middleware 激活（量化 Harness 的 overhead）**

```python
# 每次 benchmark 运行同时记录
metrics = {
    "avg_prompt_tokens_per_task": ...,   # 平均每题 prompt tokens
    "total_cost_usd": ...,               # 总费用（按模型定价）
    "summarization_triggered": ...,      # Summarization MW 触发次数
    "tool_output_truncated": ...,        # 被截断的 tool 输出数
    "subagents_launched": ...,           # 启动的 Sub-agent 数
}
# 对比 Full vs Bare：Harness 是否在不降质量的前提下节省了 token
```

#### 对比配置

| 配置 | 描述 | 目的 |
|------|------|------|
| **Full** | 完整 Middleware + 增强模块（balanced 预设） | 主实验组 |
| **Bare** | 只有 LLM + Tools，无 Middleware | 基线，量化 Middleware 整体贡献 |
| **−ToolOutput** | 关掉 Tool 输出管理（优化 2） | 消融：Tool 输出压缩对代码类任务的影响 |
| **−Memory** | 关掉 MemoryMiddleware | 消融：记忆注入对多步任务的影响 |

#### 与已有 Agent 系统的对比

对于 SWE-bench Verified，可直接引用公开排行榜数据，将 DeerFlow 2.0 的 resolve rate 与以下系统对比（均来自 SWE-bench 官方 leaderboard，结果可复现）：

| 系统 | SWE-bench Verified Resolve Rate | 是否开源 |
|------|--------------------------------|---------|
| Claude Code (Anthropic) | ~49% (2025Q4) | 否 |
| Codex CLI (OpenAI) | ~43% (2025Q4) | 是 |
| **DeerFlow 2.0 Full** | *待测* | **是** |
| **DeerFlow 2.0 Bare** | *待测* | 是 |

**注**：GAIA 和 DeepPlanning 同样有公开排行榜，可按同样方式引用已发表结果做定位对比。

#### 产出

| 编号 | 类型 | 内容 |
|------|------|------|
| Table 2 | 数据表 | 4 benchmark × 4 配置 × (主指标 mean±std, Avg Prompt Tokens, Cost) |
| Figure 2 | 热力图 | 4 benchmark × Middleware/Skill 激活强度（各组件在不同 benchmark 上的触发频率） |
| 附录 | 详细结果 | 每道题/每个实例的原始输出 + 评测日志 |

**要证明的结论**：DeerFlow 2.0 Full 在四个 benchmark 上均优于 Bare，证明 Middleware 链对不同类型任务均有稳定贡献；在 SWE-bench Verified 上达到开源系统的竞争水平，证明 Harness 的工程质量；四个 benchmark 自动激活不同 Skill/Middleware 子集（GAIA 激活 Web Search + Memory，SWE-bench 激活 Sandbox + ToolOutput 压缩，DeepPlanning 激活 Sub-agent + TodoList），这就是通用 Harness 的核心价值。

---

### 6.2 Exp 2: 长对话质量保持（抽取式问答）

**目的**：证明 DeerFlow 2.0 的上下文工程能在 50+ 轮长对话中对抗 context rot。

**公平性设计**：
- **固定脚本化对话**：50 轮的 user 消息全部预先编写好（不是人随机打字），作为附录公开
- **统一模型/温度**：与 Exp 1 相同
- **多次运行**：每个场景 × 每个配置运行 3 次
- **Checkpoint 答案预设**：每个 checkpoint 的 ground truth 在脚本中预定义

#### 3 个长对话场景（从 5 个精简到 3 个，减少成本）

| 场景 | 50 轮脚本设计 | 主要测试的能力 |
|------|-------------|-------------|
| **代码重构** | 用户上传一个 300 行 Python 文件，逐步要求：分析 → 拆函数 → 加类型 → 加测试 → 运行 → 修 bug → 重构 → 格式化 → 生成文档。每步涉及 bash/read/write 调用 | Tool Output Lifecycle（大量工具输出） |
| **研究报告** | 用户要求调研一个技术话题，逐步深入：概述 → 搜索 5 个来源 → 逐个总结 → 交叉对比 → 发现矛盾 → 补充搜索 → 写大纲 → 写各节 → 汇总 → 审校 | Summarization + MicroCompaction（大量搜索/爬取输出） |
| **多文件项目** | 用户逐步构建一个 5 文件的小项目：创建 → 编辑 → 反复修改同一文件 → 文件间重构 → 测试 → 部署脚本 | Deduplication + Subagent 隔离 |

#### 脚本设计原则

每个场景的 50 轮 user 消息不是随机的，而是按照**阶段递进**设计的：

```
通用结构（每个场景都遵循）：

  Phase 1 (Turn 1-10):   初始化 — 提出需求、确定方案、开始第一步操作
  Phase 2 (Turn 11-20):  深入 — 核心工作推进，产生大量工具调用
  Phase 3 (Turn 21-30):  转折 — 引入变更/新需求，测试 Agent 能否适应
  Phase 4 (Turn 31-40):  压力 — 高频操作，工具输出堆积，上下文接近极限
  Phase 5 (Turn 41-50):  收尾 — 整合、校验、生成最终产出

  Checkpoint 插在 Turn 10/20/30/40/50（每个 Phase 结束时）
```

关键设计要求：
- 每轮 user 消息中**自然地产生事实**（Agent 必须记住的信息），不刻意强调
- Checkpoint 问的是**Agent 做过什么 / 对话中确定过什么**，不是考通用知识
- 越晚的 Checkpoint 问越早的信息（Turn 50 问 Turn 5 的事），测**远距离记忆**

---

#### 场景 A: 代码重构（测 Tool Output Lifecycle）

**初始素材**：一个 300 行的 `data_processor.py`（预先写好放在 `eval/fixtures/` 中），包含 5 个函数，有明显的代码异味（长函数、重复代码、无类型注解、无测试）。

| Turn | User 消息 | Agent 预期行为 | 产生的关键事实 |
|------|----------|--------------|-------------|
| 1 | "我上传了一个 Python 文件 data_processor.py，先帮我读一下看看有什么问题" | `read_file` 读取文件 | 文件名: data_processor.py |
| 2 | "分析一下代码质量，告诉我主要问题" | 分析并列出问题 | — |
| 3 | "先处理最大的那个函数 process_data，它太长了，拆成 3 个小函数" | 拆分函数，`write_file` | 被拆的函数: process_data |
| 4 | "拆出来的 3 个函数分别叫什么？确认一下" | 回答函数名 | 3 个新函数名（如 validate_input, transform_data, save_output） |
| 5 | "好的，接下来给所有函数加上 type hints" | `str_replace` 多次 | — |
| 6 | "main 函数的参数类型和返回类型分别设成什么了？" | 回答类型信息 | main 的签名: (config: dict) -> int |
| 7 | "现在写 pytest 测试，先覆盖 validate_input" | `write_file` 创建 test 文件 | — |
| 8 | "再加 transform_data 和 save_output 的测试" | 追加测试 | — |
| 9 | "运行一下 pytest 看看结果" | `bash pytest` | 测试结果（如 6 passed, 2 failed） |
| **10** | **Checkpoint: "我们最开始拆分的是哪个函数？拆成了几个？"** | | **GT: "process_data，拆成 3 个"** |
| | | | **Keywords: ["process_data", "3"]** |
| 11 | "失败的那 2 个测试，具体是什么错误？" | `bash pytest -v` 查看详情 | 失败测试名: test_edge_case, test_empty_input |
| 12 | "修一下 test_edge_case 的问题" | 修改代码 | — |
| 13 | "修一下 test_empty_input" | 修改代码 | — |
| 14 | "重新跑 pytest 确认全部通过" | `bash pytest` | 8 passed, 0 failed |
| 15 | "很好，现在把 validate_input 和 format_output 这两个通用函数移到一个新文件 utils.py" | 创建 utils.py + 修改 import | 移动的函数: validate_input, format_output → utils.py |
| 16 | "确认一下移完之后 import 没有问题，跑一下 python -c 'import data_processor'" | `bash` 测试 | — |
| 17 | "给 utils.py 里的两个函数加上 docstring" | `str_replace` | — |
| 18 | "data_processor.py 里的 save_output 也加上 docstring" | `str_replace` | — |
| 19 | "现在文件结构是怎样的？ls 看一下" | `bash ls` | 当前文件列表 |
| **20** | **Checkpoint: "我们把哪些函数移到了 utils.py？"** | | **GT: "validate_input 和 format_output"** |
| | | | **Keywords: ["validate_input", "format_output", "utils.py"]** |
| 21 | "需求变更：客户要求加一个 CSV 导出功能，在 data_processor.py 里加一个 export_csv 函数" | 新增功能 | 新函数: export_csv |
| 22 | "export_csv 的参数设计成 (data: list[dict], output_path: str) -> None" | 实现函数 | export_csv 签名 |
| 23 | "给 export_csv 写测试" | 追加测试 | — |
| 24 | "运行全部测试" | `bash pytest` | — |
| 25 | "再加一个 JSON 导出的功能 export_json，放在同一个文件里" | 新增功能 | 新函数: export_json |
| 26 | "测试也加上" | 追加测试 | — |
| 27 | "全部跑一遍 pytest" | `bash pytest` | 总测试数（如 12 passed） |
| 28 | "export_csv 和 export_json 有很多重复代码，提取一个公共的 _write_output 辅助函数" | 重构提取 | 辅助函数: _write_output |
| 29 | "跑测试确认没 break" | `bash pytest` | — |
| **30** | **Checkpoint: "Turn 21 的需求变更是什么？我们后来又加了什么功能？"** | | **GT: "加 CSV 导出 (export_csv)，后来又加了 JSON 导出 (export_json)"** |
| | | | **Keywords: ["csv", "export_csv", "json", "export_json"]** |
| 31 | "用 black 格式化所有 Python 文件" | `bash black *.py` | — |
| 32 | "用 ruff 做 lint 检查" | `bash ruff check` | lint 结果 |
| 33 | "修复 ruff 报的问题" | 多次 `str_replace` | — |
| 34 | "再检查一遍" | `bash ruff check` | — |
| 35 | "生成一份 requirements.txt" | `write_file` | — |
| 36 | "加一个 Makefile，包含 test/lint/format 三个 target" | `write_file` | — |
| 37 | "跑一下 make test 确认能用" | `bash make test` | — |
| 38 | "跑 make lint" | `bash make lint` | — |
| 39 | "跑 make format" | `bash make format` | — |
| **40** | **Checkpoint: "main 函数的返回类型是什么？我们最早在第几步加的 type hints？"** | | **GT: "返回类型是 int，在 Turn 5-6 加的"** |
| | | | **Keywords: ["int"]** |
| 41 | "现在写一份重构总结报告 refactor_report.md" | `write_file` | — |
| 42 | "报告里要列出：原始问题、重构步骤、最终文件结构" | 补充报告内容 | — |
| 43 | "加上代码量变化的统计：原来几行，现在几行" | `bash wc -l *.py` + 更新报告 | 代码行数统计 |
| 44 | "加上测试覆盖率" | `bash pytest --cov` + 更新报告 | 覆盖率数字（如 87%） |
| 45 | "最后做一次全量检查：pytest + ruff + black --check" | `bash` 多个命令 | — |
| 46 | "把所有最终文件列表打印出来" | `bash ls -la` | — |
| 47 | "检查一下 refactor_report.md 的内容是否完整" | `read_file` | — |
| 48 | "补充一下报告开头的项目名称：DataPipeline Refactoring" | `str_replace` | 项目名: DataPipeline Refactoring |
| 49 | "最终确认：运行 python data_processor.py --help 看看" | `bash` | — |
| **50** | **Checkpoint: "回顾一下：原始文件叫什么？最终拆成了几个 Python 文件？测试覆盖率是多少？"** | | **GT: "原始文件 data_processor.py，最终有 data_processor.py + utils.py + test_*.py (3个文件)，覆盖率 87%"** |
| | | | **Keywords: ["data_processor.py", "utils.py", "87"]** |

---

#### 场景 B: 研究报告（测 Summarization + MicroCompaction）

**特点**：大量 `web_search` + `web_fetch` 产生海量外部内容，上下文膨胀最快。

| Turn | User 消息 | 产生的关键事实 |
|------|----------|-------------|
| 1 | "帮我调研一下 2026 年主流的 AI Agent 框架，先给我一个初步概述" | — |
| 2 | "重点看 LangChain、CrewAI、AutoGen 这三个框架" | 三个目标框架名 |
| 3 | "先搜索 LangChain 最新版本的变化" | `web_search` 产生搜索结果 |
| 4 | "打开第一个搜索结果的链接，仔细读一下" | `web_fetch` 产生大量网页内容（5000+ tokens） |
| 5 | "总结一下 LangChain 的核心特性" | Agent 总结 |
| 6 | "搜索 CrewAI" | `web_search` |
| 7 | "读一下 CrewAI 的官方文档" | `web_fetch`（又一大段内容） |
| 8 | "CrewAI 的核心理念是什么？跟 LangChain 有什么区别？" | Agent 分析差异 |
| 9 | "搜索 AutoGen" | `web_search` |
| **10** | **Checkpoint: "我们在调研哪三个框架？LangChain 的核心特性你总结了什么？"** | **GT: "LangChain、CrewAI、AutoGen；LangChain 核心特性包括 [Turn 5 的总结要点]"** |
| | | **Keywords: ["LangChain", "CrewAI", "AutoGen"]** |
| 11 | "读 AutoGen 的 GitHub README" | `web_fetch` |
| 12 | "AutoGen 的多 Agent 协作模式是怎样的？" | Agent 分析 |
| 13 | "搜索一下这三个框架的 GitHub star 数和最近更新时间" | `web_search` |
| 14 | "整理成一个对比表格" | Agent 生成表格 |
| 15 | "我发现 CrewAI 和 AutoGen 对 tool calling 的支持方式不同，能详细比较一下吗？" | — |
| 16 | "搜索一下 CrewAI 的 tool calling 文档" | `web_fetch` |
| 17 | "再搜索 AutoGen 的 tool calling" | `web_fetch` |
| 18 | "这两个在 tool calling 上到底有什么区别？" | Agent 对比分析 |
| 19 | "现在开始写报告大纲" | Agent 生成大纲 |
| **20** | **Checkpoint: "三个框架的 GitHub star 数分别大概是多少？你在 Turn 14 整理的表格里写的"** | **GT: [Turn 14 表格中的数字]** |
| | | **Keywords: [具体 star 数字]** |
| 21 | "开始写第一节：框架背景介绍" | `write_file` report.md |
| 22 | "写第二节：架构对比" | 追加内容 |
| 23 | "等一下，我想再搜索一下 Anthropic 有没有自己的 Agent 框架" | `web_search`（中途插入新需求） |
| 24 | "好像有 claude-agent-sdk，搜一下详细信息" | `web_fetch` |
| 25 | "把 claude-agent-sdk 也加到报告里作为第四个框架" | 修改报告 | 第四个框架: claude-agent-sdk |
| 26 | "调整大纲，加入第四个框架的对比" | — |
| 27 | "写第三节：Tool calling 对比" | 追加内容 |
| 28 | "写第四节：适用场景推荐" | 追加内容 |
| 29 | "搜索一下有没有性能基准测试（benchmark）对比这些框架的" | `web_search` + `web_fetch` |
| **30** | **Checkpoint: "我们中途加了哪个框架？是在第几轮加的？"** | **GT: "claude-agent-sdk，在 Turn 23-25 加的"** |
| | | **Keywords: ["claude-agent-sdk"]** |
| 31 | "把 benchmark 数据加到报告里" | — |
| 32-38 | （继续完善各节内容、补充引用来源、交叉验证信息） | 持续 `web_search`/`web_fetch` |
| 39 | "加一个结论节，给出最终推荐" | — |
| **40** | **Checkpoint: "CrewAI 和 AutoGen 在 tool calling 上的核心区别是什么？你在 Turn 18 分析过"** | **GT: [Turn 18 的分析要点]** |
| | | **Keywords: [具体技术差异关键词]** |
| 41-48 | （审校报告、修改格式、添加引用列表、生成摘要） | — |
| 49 | "最终确认：报告一共几节？引用了多少个来源？" | — |
| **50** | **Checkpoint: "回顾全过程：最初的三个框架是哪三个？后来加了什么？报告最终有几个引用来源？"** | **GT: "LangChain/CrewAI/AutoGen + claude-agent-sdk，[X] 个引用"** |
| | | **Keywords: ["LangChain", "CrewAI", "AutoGen", "claude-agent-sdk"]** |

---

#### 场景 C: 多文件项目（测 Deduplication + Subagent 隔离）

**特点**：反复读写同一文件 + 用 Sub-agent 并行执行子任务。

| Turn | User 消息 | 产生的关键事实 |
|------|----------|-------------|
| 1 | "我们从零开始创建一个 Python CLI 工具，项目名叫 taskflow" | 项目名: taskflow |
| 2 | "先创建项目结构：taskflow/main.py, taskflow/models.py, taskflow/utils.py" | 3 个文件 |
| 3 | "在 models.py 里定义一个 Task 数据类，包含 id, title, status, created_at" | Task 类字段 |
| 4 | "在 main.py 里写 CLI 入口，用 argparse，支持 add/list/done 三个子命令" | 三个命令: add, list, done |
| 5 | "在 utils.py 里写一个 load_tasks 和 save_tasks 函数，用 JSON 文件存储" | 存储方式: JSON 文件 |
| 6 | "把 main.py 和 models.py 的代码读给我看一下" | `read_file` × 2 |
| 7 | "main.py 里的 add 命令有个 bug，status 应该默认是 'pending' 不是 'todo'" | 修改 main.py | 默认 status: pending |
| 8 | "再读一遍 main.py 确认改好了" | `read_file`（第 2 次读 main.py → 测去重） |
| 9 | "加一个 delete 子命令" | 修改 main.py | 第四个命令: delete |
| **10** | **Checkpoint: "项目叫什么名字？Task 类有哪些字段？"** | **GT: "taskflow；id, title, status, created_at"** |
| | | **Keywords: ["taskflow", "id", "title", "status", "created_at"]** |
| 11 | "读 main.py 看一下现在的全貌" | `read_file`（第 3 次读 main.py） |
| 12 | "加一个 priority 字段到 Task 类，高/中/低三级" | 修改 models.py | 新字段: priority (high/medium/low) |
| 13 | "main.py 的 add 命令也要支持 --priority 参数" | 修改 main.py |
| 14 | "utils.py 的 save_tasks 需要处理 priority 字段的序列化" | 修改 utils.py |
| 15 | "试跑一下：python main.py add --title '测试' --priority high" | `bash` |
| 16 | "再跑 python main.py list 看看" | `bash` |
| 17 | "输出格式不好看，改成表格形式" | 修改 main.py |
| 18 | "再读一遍 main.py" | `read_file`（第 4 次读 main.py → 重复去重的关键测试点） |
| 19 | "现在给整个项目写测试" | — |
| **20** | **Checkpoint: "Task 类后来加了什么字段？默认 status 是什么？"** | **GT: "加了 priority 字段(high/medium/low)；默认 status 是 pending"** |
| | | **Keywords: ["priority", "pending"]** |
| 21 | "测试文件太多事了，拆成 3 个子任务并行做：(1) 测试 add 命令 (2) 测试 list+done 命令 (3) 测试 delete 命令" | 调用 3 个 `task` tool → Sub-agent 并行 | 使用了 3 个 Sub-agent |
| 22 | "Sub-agent 结果怎么样？通过了吗？" | 查看结果 |
| 23 | "有失败的测试，读一下 test_delete.py 看看哪里错了" | `read_file` |
| 24 | "修 delete 的逻辑，它应该按 id 删除不是按 title" | 修改 main.py | 删除逻辑: 按 id 删除 |
| 25 | "重跑全部测试" | `bash pytest` |
| 26 | "加一个新功能：export 子命令，把任务导出为 CSV" | 修改 main.py | 第五个命令: export |
| 27 | "再加一个 import 子命令，从 CSV 导入" | 修改 main.py | 第六个命令: import |
| 28 | "读 main.py 看看现在有多大了" | `read_file`（第 5 次读 main.py） |
| 29 | "main.py 太长了，把 export/import 逻辑移到一个新文件 io_handlers.py" | 创建新文件 + 重构 | 新文件: io_handlers.py |
| **30** | **Checkpoint: "Turn 21 我们用 Sub-agent 做了什么？分了几个子任务？"** | **GT: "并行写 3 组测试：add、list+done、delete，用了 3 个 Sub-agent"** |
| | | **Keywords: ["3", "sub-agent" 或 "子任务"]** |
| 31-38 | （继续完善项目：加 README.md、Makefile、.gitignore、setup.py、修 bug、优化性能） | 持续读写文件 |
| 39 | "最终文件结构 ls 一下" | `bash ls` |
| **40** | **Checkpoint: "delete 命令是按什么删除的？这个 bug 我们在第几轮修的？"** | **GT: "按 id 删除，在 Turn 24 修的"** |
| | | **Keywords: ["id"]** |
| 41-48 | （生成文档、运行最终测试、打包、清理临时文件） | — |
| 49 | "我们的 main.py 一共被读了几次？被改了几次？" | Agent 回顾 |
| **50** | **Checkpoint: "整个项目从 3 个文件变成了几个？最后加的那个文件叫什么？所有子命令列一下"** | **GT: "变成 5+ 个文件；最后加的是 io_handlers.py；子命令：add, list, done, delete, export, import"** |
| | | **Keywords: ["io_handlers.py", "add", "list", "done", "delete", "export", "import"]** |

---

#### Checkpoint 统计

| | 场景 A (代码重构) | 场景 B (研究报告) | 场景 C (多文件项目) | 合计 |
|---|---|---|---|---|
| Checkpoint 数 | 5 | 5 | 5 | **15** |
| 涉及的关键词数 | 13 | 12 | 14 | **39** |
| 远距离回忆（间隔 >20 轮） | 2 | 2 | 2 | **6** |
| 中距离回忆（间隔 10-20 轮） | 2 | 2 | 2 | **6** |
| 近距离回忆（间隔 <10 轮） | 1 | 1 | 1 | **3** |

每个 Checkpoint 的关键词都是**对话中 Agent 自己生成或确认过的具体信息**（函数名、文件名、数字、工具名），不是模糊的概念。这保证了关键词匹配的可靠性。

**总数据点**：15 checkpoint × 4 配置 × 3 次运行 = **180 个打分数据点**，足够做 paired t-test 或 Wilcoxon 显著性检验。

#### 指标定义

**指标 1: Checkpoint Recall Accuracy（检查点回忆准确率）—— 半自动**

```python
# ======== 打分方法：关键词匹配 + LLM 兜底 ========

def score_checkpoint(agent_response: str, ground_truth: str, keywords: list[str]) -> int:
    """
    先用关键词匹配（零成本、可复现），匹配失败再用 LLM 兜底。
    返回：2（完全正确）、1（部分正确）、0（错误）
    """
    # 第一步：关键词精确匹配（大部分 case 在这里就能判断）
    response_lower = agent_response.lower()
    matched = sum(1 for kw in keywords if kw.lower() in response_lower)

    if matched == len(keywords):
        return 2  # 全部关键词命中 → 完全正确
    if matched == 0:
        # 可能 Agent 换了说法，用 LLM 做语义判断
        return llm_judge_checkpoint(agent_response, ground_truth)
    return 1  # 部分命中

# 示例：
# Ground Truth: "process_data 函数"
# Keywords: ["process_data"]
# Agent 说 "我们拆分的是 process_data()" → 关键词命中 → 2 分
# Agent 说 "那个数据处理的主函数" → 关键词未命中 → 走 LLM 判断 → 可能 1 分
# Agent 说 "我不记得了" → 关键词未命中 → LLM 判断 → 0 分

# Checkpoint Recall Accuracy = Σ 所有 checkpoint 得分 / (checkpoint 数 × 2) × 100%
# 例如 5 个 checkpoint 满分 10 分，得 8 分 → 80%
```

**为什么这样比纯 LLM-as-Judge 好**：
- 大部分 checkpoint 有明确的关键词（函数名、文件名、数字），关键词匹配就能判断 → **审稿人无法质疑**
- 只有关键词匹配失败的边缘 case 才走 LLM → LLM 判断量小，偏差影响有限
- 论文中报告"X% 的 checkpoint 由关键词匹配判定，Y% 由 LLM 兜底判定"

**指标 2: Turn-level Task Progress（逐轮任务进度）—— 自动化**

```python
# 不仅在 checkpoint 评估，还在每一轮记录"任务完成了多少"
# 方法：每个场景预定义 10 个里程碑事件，自动检测

MILESTONES_CODE_REFACTOR = [
    ("read_original", lambda s: s.tool_called("read_file", "data_processor.py")),
    ("first_split", lambda s: s.file_count("/mnt/user-data/workspace/") >= 2),
    ("type_hints", lambda s: s.grep("main.py", r"-> \w+") > 0),
    ("tests_created", lambda s: s.file_exists("test_*.py")),
    ("tests_pass", lambda s: s.last_exit_code("pytest") == 0),
    ("utils_extracted", lambda s: s.file_exists("utils.py")),
    ("all_tests_pass", lambda s: s.grep_output("passed") >= 6),
    ("docstrings_added", lambda s: s.grep("main.py", r'"""') >= 3),
    ("formatted", lambda s: s.tool_called("bash", "black") or s.tool_called("bash", "ruff")),
    ("report_generated", lambda s: s.file_exists("refactor_report.md")),
]

# 每轮结束后扫描一次，记录当前完成的里程碑数
# 画出 "Turn vs Milestones Completed" 曲线
# Full Pipeline 应该是平稳上升到 10/10
# Bare 应该在中后期停滞或回退（Agent 迷失方向重复操作）
```

**指标 3: Token Consumption Curve（Token 消耗曲线）—— 精确记录**

```python
# 每轮记录 prompt_tokens
# 画出 Turn vs Cumulative Prompt Tokens 曲线
# Full Pipeline 由于 Summarization + Tool 压缩，曲线增长应该更缓慢
# Bare 曲线应该线性/超线性增长，最终可能撞到模型上限
```

#### 对比配置

| 配置 | 描述 | 目的 |
|------|------|------|
| **Full** | 完整 Middleware + 增强模块 | 主实验组 |
| **−Summarization** | 关掉摘要 | 验证摘要对长对话的必要性 |
| **−ToolOutput** | 关掉 Tool 输出管理 | 验证工具输出压缩的必要性 |
| **Bare** | 只有 LLM + Tools，无 Middleware | 基线，证明 Middleware 链的整体价值 |

（精简到 4 个配置 × 3 场景 × 3 次 = 36 次运行，控制成本）

#### 应对"LLM-as-Judge 被质疑"的完整策略

| 质疑点 | 应对 |
|--------|------|
| "LLM Judge 有偏好" | 三模型交叉评审（Claude + GPT + Gemini），报告 Judge 间一致性 |
| "LLM 给自己打高分" | 生成用 Claude，评审用 GPT（不同厂商），论文注明 |
| "评分不可复现" | 所有 Judge prompt 和打分结果作为附录公开 |
| "主观指标不可信" | **Checklist Pass Rate 和 Checkpoint Keywords 是客观指标，占权重大于 Quality Score** |
| "样本量太小" | 3 场景 × 4 配置 × 3 次 × 5 checkpoint = 180 个 checkpoint 数据点，足够做显著性检验 |
| "没有人工验证" | 随机抽取 20% 样本人工打分，报告 Spearman ρ |

#### 产出

| 编号 | 类型 | 内容 |
|------|------|------|
| Table 3 | 数据表 | 3 场景 × 4 配置 × (Checkpoint Recall%, Milestone 完成数, 总 Token, 最终 Token/轮) |
| Figure 3 | 折线图 | Checkpoint Recall 随轮数衰减曲线（4 条线 × 3 场景 = 12 条） |
| Figure 4 | 折线图 | Milestone 进度曲线（Turn vs Milestones Completed） |
| 附录 | 脚本 | 完整的 50 轮 user prompt 脚本 + checkpoint ground truth + keywords |

**要证明的结论**：
- Full Pipeline 在 50 轮后 Checkpoint Recall ≥ 85%，Bare ≤ 50%
- Full Pipeline 的 10 个里程碑全部完成，Bare 在中后期停滞
- Full Pipeline 的 token 增长曲线显著低于 Bare（Summarization + ToolOutput 的效果可量化）

### 6.3 Exp 3: Middleware 消融实验

**目的**：证明 11 层 Middleware 链中各层的独立贡献，识别对不同任务类型最关键的 Middleware，建立"去掉某层 → 哪类任务下降多少"的因果关系。

#### 消融目标选取原则

11 层 Middleware 中，并非每层都适合做消融——基础设施层去掉会直接崩溃，UI 层去掉对任务质量无影响，条件加载层在大部分 benchmark 任务中根本不触发。以下为分类：

| 分类 | Middleware | 消融决策 | 原因 |
|------|-----------|---------|------|
| ✅ 有消融价值 | SummarizationMiddleware | **消融** | 控制长对话 token 增长；在多步任务中直接影响完成率 |
| ✅ 有消融价值 | SubagentLimitMiddleware（隔离侧） | **消融** | 子任务上下文隔离直接影响并行执行质量 |
| ✅ 有消融价值 | MemoryMiddleware | **消融（仅 Exp 3B）** | 跨轮 facts 注入只在长对话中体现价值，单次 benchmark 无差异 |
| ✅ 有消融价值 | DanglingToolCallMiddleware | **消融** | 工具调用中断修补影响系统鲁棒性，在代码执行类任务中最明显 |
| ❌ 基础设施 | ThreadDataMiddleware | 不消融 | 去掉则 workspace/uploads/outputs 路径未初始化，直接崩溃 |
| ❌ 基础设施 | SandboxMiddleware | 不消融 | 去掉则代码无法执行，SWE-bench / HumanEval 完全失效 |
| ❌ 纯 UI | TitleMiddleware | 不消融 | 仅生成对话标题，对任务质量零影响 |
| ❌ 纯 UI | TodoListMiddleware | 不消融 | plan mode 下的状态展示，不影响 Agent 决策 |
| ❌ 条件加载 | ViewImageMiddleware | 不消融 | 仅视觉模型加载；benchmark 任务基本不触发 |
| ❌ 条件加载 | ClarificationMiddleware | 不消融 | benchmark 全自动运行，无用户打断，永远不触发 |
| ❌ 条件加载 | UploadsMiddleware | 不消融 | benchmark 无用户上传文件场景 |

消融实验分两个子实验：**Exp 3A** 针对 Exp 1 的四个标准 benchmark（单次运行），**Exp 3B** 针对 Exp 2 的长对话场景（50 轮）。

---

#### Exp 3A：标准 Benchmark 上的消融（基于 Exp 1 任务集）

**方法**：在 Exp 1 的四个 benchmark 上额外跑以下配置（每个跑 3 次，与 Exp 1 保持相同随机种子）。Bare 配置已在 Exp 1 跑过，直接复用。

| 配置 | 描述 | 消融目标 | 预期影响 benchmark |
|------|------|---------|-----------------|
| **Full** | 完整 11 层 MW | 上界 | — |
| **−Summarization** | 去掉 SummarizationMiddleware | 验证参数化摘要对长任务的必要性 | DeepPlanning ↓（多步规划 token 超限）、GAIA Level 3 ↓；Avg Prompt Tokens ↑ 最显著 |
| **−SubagentIsolation** | SubagentLimitMiddleware 保留（限制并发数），但 subagent 继承主 Agent 完整上下文，不隔离 | 验证上下文隔离对并行子任务的价值 | DeepPlanning ↓（子任务互相污染上下文）；GAIA / SWE / HumanEval 影响有限 |
| **−DanglingToolCall** | 去掉 DanglingToolCallMiddleware | 验证中断 tool call 修补对鲁棒性的影响 | SWE-bench ↓（代码修复多轮调用中途中断）；其他 benchmark 影响较小 |
| **Bare** | 只有 LLM + Tools，无任何 Middleware | 下界 | 全面下降（复用 Exp 1 数据）|

**层次结构**：

```
Bare（无 MW）
  ↓
−DanglingToolCall（仅修补容错缺失）
  ↓
−Summarization（无长对话压缩）
  ↓
−SubagentIsolation（子任务上下文不隔离）
  ↓
Full（11 层完整系统）
```

**指标**（与 Exp 1 保持一致）：

| 指标 | 说明 |
|------|------|
| 主指标（各 benchmark 原生） | GAIA EM / SWE Resolve Rate / HumanEval pass@1 / DeepPlanning Success Rate |
| Avg Prompt Tokens/Task | 量化 token 消耗变化，直接体现 Summarization 的压缩贡献 |
| Tool Call Error Rate | 记录因 dangling tool call 导致的工具调用失败次数，体现 DanglingToolCall 的容错价值 |

**期望结论**：
- `−Summarization` 在 DeepPlanning 上 Success Rate 下降最大（>10%），Avg Prompt Tokens 上升最显著
- `−SubagentIsolation` 在 DeepPlanning 上 Success Rate 下降明显，在 GAIA/SWE/HumanEval 上差异可忽略
- `−DanglingToolCall` 在 SWE-bench 上 Resolve Rate 下降（工具调用鲁棒性退化），Tool Call Error Rate 上升

**产出**：Table 4（消融矩阵：5 配置 × 4 benchmark 主指标 + Avg Prompt Tokens + Tool Call Error Rate）、Fig 6（各配置在四个 benchmark 上的主指标条形图，按 benchmark 分面）

---

#### Exp 3B：长对话场景上的消融（基于 Exp 2 任务集）

**方法**：在 Exp 2 的软件项目开发场景（50 轮对话）上额外跑以下配置（每个跑 3 次，与 Exp 2 保持相同脚本）。Full 和 Bare 配置已在 Exp 2 跑过，直接复用。

| 配置 | 描述 | 消融目标 | 预期影响 |
|------|------|---------|---------|
| **Full** | 完整 11 层 MW | 上界 | Checkpoint Recall ≥ 85%，Token 增长平稳 |
| **−Summarization** | 去掉 SummarizationMiddleware | 验证摘要对长对话 token 控制的贡献 | Token 线性暴涨，Turn 30+ 后质量崩塌；Checkpoint Recall 显著下降 |
| **−Memory** | 去掉 MemoryMiddleware（facts 写入 + 注入均关闭） | 验证跨轮 facts 注入对长对话质量的贡献 | Turn 30+ Checkpoint Recall 下降（早期 facts 无法被注入）；Token 影响较小 |
| **Bare** | 只有 LLM + Tools，无任何 Middleware | 下界 | Checkpoint Recall ≤ 50%，中后期进度停滞（复用 Exp 2 数据）|

**指标**（与 Exp 2 保持一致）：

| 指标 | 说明 |
|------|------|
| Checkpoint Recall@Turn | 各轮次后能通过的 checkpoint 比例（衰减曲线） |
| Milestone Completion | 10 个里程碑的累计完成数 |
| Avg Prompt Tokens/Turn | 各轮 prompt token 数（体现 Summarization 压缩效果）|

**期望结论**：
- `−Summarization` 的 Token/Turn 曲线呈线性上升，`Full` 呈平稳状态，两者在 Turn 20 后差距显著扩大
- `−Memory` 的 Checkpoint Recall 在 Turn 30 后开始低于 `Full`（早期信息随对话压缩而消失，Memory 的 facts 注入成为唯一保留路径）
- `−Summarization` 与 `−Memory` 的**衰减曲线形态不同**：前者 token 爆涨导致崩塌，后者信息丢失导致缓慢衰减——两种失效模式可视化对比是 Exp 3B 的核心发现

**产出**：Table 5（消融矩阵：4 配置 × Checkpoint Recall / Milestone 完成数 / Avg Token/Turn）、Fig 7（4 条 Checkpoint Recall 衰减曲线）、Fig 8（4 条 Token/Turn 增长曲线）


### 6.4 Exp 4: 与业界方案对比

**目的**：展示 DeerFlow 2.0 在 Agent Harness 领域的**架构定位和上下文策略差异**。不是说 DeerFlow 比 Claude Code 更好（它们定位不同），而是通过系统化对比展示 DeerFlow 2.0 的设计取舍和独特价值。

**对比对象选择理由**：

| 产品 | 选择理由 | 数据来源 |
|------|---------|---------|
| **Claude Code** | 上下文管理最成熟的闭源 Agent（MicroCompact + Auto-Compact + Rehydration），2026 标杆 | Decode Claude 逆向工程、Anthropic 官方博客、Context Compaction API 文档 |
| **Codex CLI** | OpenAI 开源 Agent（Rust 实现），代表 lightweight harness 思路 | GitHub 开源代码、OpenAI 官方文档、PR #289 (compact) |
| **OpenClaw** | 2026 最火的开源 Agent（100K+ stars），Gateway + Skills 架构，社区标杆 | GitHub 开源代码、官方文档、Reference Architecture 分析 |
| **LangChain DeepAgents** | 同框架（LangGraph）下的官方 Harness 方案，最直接的同类对比 | LangChain 官方博客"Context Management for Deep Agents"、SDK 文档 |

#### Part A: 架构特性对比（定性，Feature Matrix）

这是论文的 Table 6，展示"作为 Harness，各自有什么能力"：

| 维度 | Claude Code | Codex CLI | OpenClaw | LangChain DeepAgents | **DeerFlow 2.0** |
|------|------------|-----------|---------|---------------------|-----------------|
| **开源** | 是 | 是(Apache 2.0) | 是 | 是 | **是** |
| **架构模式** | Single Agent + 内部状态机 | Single Agent Loop (Rust) | Gateway + Agentic Loop | Single Agent + Middleware | **Lead Agent + 11 层 Middleware + Sub-agent** |
| **Skill 系统** | CLAUDE.md + 自定义 Skill | 无显式 Skill | SKILLS.md + ClawHub | Skills (beta) | **SKILL.md + 渐进式加载 + 10 个内置 Skill** |
| **沙箱执行** | 本地终端 | 本地终端 + sandbox policy | 本地 / VPS | 无内置 | **Local / Docker / K8s 三模式** |
| **Sub-agent** | 无（单 Agent） | 无 | 无（单 Loop） | Subagent（上下文隔离） | **双线程池 + 3 并行 + 超时 + 上下文隔离** |
| **长期记忆** | memory files (Markdown) | transcript resume | persistent memory (Markdown) | 无内置 | **结构化 Fact 库 + 异步队列 + 三 Block 注入** |
| **Tool 输出压缩** | MicroCompact (hot/cold) | 无 | token 管理 + 选择性丢弃 | 大输出 offload 到文件系统 | **SummarizationMiddleware（对话级）** |
| **上下文摘要** | Auto-Compact (LLM 摘要 + Rehydration) | /compact 命令 (手动) | 自动摘要 | LLM 摘要 + 文件归档 | **SummarizationMiddleware（参数化触发）** |
| **Tool Schema 管理** | 无（工具数量少） | 无 | TOOLS.md 声明式 | 无 | **tool_groups 静态分组** |
| **可配置性** | 有限（/compact 手动） | CLI flags | config 文件 | Middleware 参数 | **全参数 YAML** |
| **Middleware 架构** | 无公开中间件链 | 无 | 无（内嵌在 Loop 中） | 有（Middleware 抽象） | **11 层显式 Middleware 链 + 自定义插拔** |

**这张表怎么读**：
- Claude Code 在上下文压缩上最成熟（MicroCompact + Auto-Compact + Rehydration），但**不开放 Middleware 架构**，用户无法自定义上下文管理策略
- Codex CLI 最轻量，但**上下文管理能力最弱**（只有手动 /compact）
- OpenClaw 社区最活跃，但**没有 Sub-agent、没有结构化记忆**
- LangChain DeepAgents 是同框架最近的对比，有 Subagent，但**没有 Skill 体系、没有 Local/Docker/K8s 三模式沙箱**
- DeerFlow 2.0 的差异化：**唯一同时具备 11 层显式 Middleware + 双线程池 Sub-agent + Skill 体系 + 三模式沙箱 + 跨会话结构化记忆的开源 Harness，且附完整架构演进论文**

#### Part B: 上下文策略量化对比（定量）

这里只对比**能定量测量的上下文策略**，不对比整体"谁更好"：

**方法**：在同一个 30 轮 coding 任务上（Exp 1 的 Coding 任务扩展版），分别测量各策略的 token 节省效果。

| 对比方案 | 实现方式 | 可复现性 |
|---------|---------|---------|
| **DeerFlow Full** | 完整增强模块 | ✅ 我们的系统 |
| **DeerFlow Bare** | 关掉所有增强 | ✅ 配置开关 |
| **LangChain DeepAgents** | 官方 offloading + subagent | ✅ 开源可复现 |
| **Claude-style MicroCompact** | 在 DeerFlow 上复刻 Claude 的 hot/cold 策略（不含 Auto-Compact，因为那需要闭源 prompt） | ✅ 我们复刻实现 |
| **Naive Truncation** | 简单截断旧消息保留最近 N 条（学术 baseline） | ✅ 简单实现 |

**注意**：我们**不直接运行 Claude Code / OpenClaw / Codex**（它们的上下文管理策略嵌在各自系统中无法单独测量），而是：
1. 在 DeerFlow 框架内复刻其核心策略（如 Claude-style MicroCompact）
2. 对 LangChain DeepAgents 直接运行（同框架）
3. 比较的是**策略本身的效果**，不是"系统 vs 系统"

这样做的好处是**变量可控**——同一个 LLM、同一个任务、同一个沙箱，唯一变量是上下文管理策略。

**指标**：

| 指标 | 计算方式 | 意义 |
|------|---------|------|
| **Avg Prompt Tokens/Turn** | Σ prompt_tokens / 总轮数 | 平均每轮上下文大小 |
| **Peak Prompt Tokens** | max(prompt_tokens across turns) | 最大上下文峰值 |
| **Tool Output Tokens Saved** | (Bare tool_tokens − Strategy tool_tokens) / Bare tool_tokens | Tool 输出压缩率 |
| **Tool Schema Tokens Saved** | (Bare schema_tokens − Strategy schema_tokens) / Bare schema_tokens | Tool 定义压缩率 |
| **Task Checklist Pass Rate** | 同 Exp 1 的自动化 Checklist | 确保压缩不牺牲质量 |
| **Extra LLM Calls** | 策略引入的额外 LLM 调用次数 | 衡量策略自身的成本 |

**预期结果表**（Table 7）：

```
| 方案 | Avg Token/Turn | Peak Token | Tool 输出节省 | Schema 节省 | Checklist | 额外 LLM 调用 |
|------|---------------|------------|-------------|------------|-----------|-------------|
| DeerFlow Bare | 基准 | 基准 | — | — | ≥80% | 0 |
| Naive Truncation | -30% | -40% | — | — | 降低明显 | 0 |
| Claude-style MicroCompact | -45% | -50% | ~50% | — | ≈Bare | 0 |
| LangChain DeepAgents | -40% | -55% | ~60% | — | ≈Bare | 1-2(摘要) |
| DeerFlow Full | -65% | -70% | ~85% | ~80% | ≈Bare | 0 |
```

**DeerFlow Full 预期优于其他方案的原因**：
- vs Naive Truncation：不丢失关键信息，质量不降
- vs Claude-style MicroCompact（复刻版）：DeerFlow 额外有源头截断 + 去重 + Tool Schema 管理
- vs LangChain DeepAgents：DeerFlow 额外有 Tool Schema 三层管理 + Profiler 可观测性，且不需要额外 LLM 调用做摘要
- DeerFlow Full 的**全部策略都是 zero-extra-LLM-cost**（规则型），这是一个独特卖点

#### Part C: 公平性说明（论文中需写清楚）

| 潜在质疑 | 应对 |
|---------|------|
| "Claude Code 策略复刻不准确" | 明确标注 "Claude-style"，声明是基于公开逆向工程资料的近似复刻，不代表 Claude Code 的完整效果 |
| "不直接运行对手系统不公平" | 解释原因：(1) 变量不可控（不同 LLM、不同 system prompt）(2) 本文核心贡献是架构和策略，不是跑分 (3) LangChain DeepAgents 是直接运行的 |
| "Feature Matrix 太主观" | 每个 ✅/❌ 都标注来源（GitHub 代码 commit、官方文档 URL、博客链接），可验证 |
| "DeerFlow 胜出是因为在自己框架上跑" | Bare 配置使用同一个框架但关掉所有增强，证明增益来自策略而非框架 |

#### 产出

| 编号 | 类型 | 内容 |
|------|------|------|
| Table 7 | Feature Matrix | 5 个 Harness × 12 个维度的定性对比 |
| Table 8 | 量化对比 | 5 种策略 × 6 个指标的定量对比 |
| Figure 9 | 折线图 | 5 种策略的 Prompt Tokens/Turn 随轮数变化 |
| 附录 | 引用来源 | Feature Matrix 每个单元格的来源 URL |


---

## 7. 代码改动清单

### 改动 1: 评测 — `eval/` (新建目录)

```
eval/
├── benchmark_eval.py              # Exp 1: 标准 Benchmark 评测（GAIA / SWE-bench Verified / HumanEval / DeepPlanning）
├── long_dialogue_eval.py          # Exp 2: 长对话质量保持（3 场景 × 50 轮脚本）
├── ablation_eval.py               # Exp 3: Middleware 消融
├── strategy_comparison_eval.py    # Exp 4: 与业界上下文策略对比（5 策略量化比较）
├── config_flexibility_eval.py     # Exp 5: 配置灵活性 + Profiler 可视化
├── judge/
│   ├── rubric.py                  # 三模型交叉评审 Rubric
│   ├── checkpoint_scorer.py       # Checkpoint 关键词匹配 + LLM 兜底
│   └── human_calibration.py       # 人工校准 Spearman ρ 计算
├── fixtures/
│   ├── data_processor.py          # Exp 2 场景 A 的 300 行初始文件
│   └── scripts/                   # 3 个场景的 50 轮 user prompt 脚本
│       ├── code_refactor_50.yaml
│       ├── research_report_50.yaml
│       └── multi_file_project_50.yaml
├── datasets/
│   ├── gaia_validation.jsonl      # Exp 1: GAIA validation split（官方下载）
│   ├── swebench_verified.jsonl    # Exp 1: SWE-bench Verified 500 实例（官方）
│   ├── humaneval.jsonl            # Exp 1: HumanEval 164 题（官方）
│   └── deepplanning_test.jsonl    # Exp 1: DeepPlanning 测试集（官方）
└── results/
```

---

## 8. 论文关键图表清单

| 编号 | 类型 | 内容 | 来源 |
|------|------|------|------|
| Fig 1 | 架构对比图 | DeerFlow 1.0 StateGraph vs 2.0 Lead Agent + MW + SubAgent | Sec 2 |
| Fig 2 | 架构图 | DeerFlow 2.0 完整架构：11 层 MW + 三类工具 + Skills + Sandbox + Memory | Sec 2 |
| Fig 3 | 热力图 | Exp 1: 4 benchmark × Middleware/Skill 激活强度 | Exp 6.1 |
| Fig 4 | 折线图 | Exp 2: Checkpoint Recall 随轮数衰减曲线（4 配置 × 3 场景） | Exp 6.2 |
| Fig 5 | 折线图 | Exp 2: Milestone 进度曲线（Turn vs Milestones Completed） | Exp 6.2 |
| Fig 6 | 条形图 | Exp 3A: 消融实验——5 配置在四个 benchmark 主指标对比（按 benchmark 分面）| Exp 6.3 |
| Fig 7 | 折线图 | Exp 3B: 消融实验——4 配置的 Checkpoint Recall 衰减曲线（50 轮）| Exp 6.3 |
| Fig 8 | 折线图 | Exp 3B: 消融实验——4 配置的 Token/Turn 增长曲线（50 轮）| Exp 6.3 |
| Fig 9 | 折线图 | Exp 4: 5 种上下文策略的 Prompt Tokens/Turn 随轮数变化 | Exp 6.4 |
| Tab 1 | 表格 | 1.0 vs 2.0 架构对比维度表（8 维度） | Sec 2 |
| Tab 2 | 表格 | Exp 1: 4 benchmark × 4 配置 × (主指标 mean±std, Avg Prompt Tokens, Cost) | Exp 6.1 |
| Tab 3 | 表格 | Exp 2: 3 场景 × 4 配置 × (Checkpoint Recall%, Milestone 完成数, 总 Token) | Exp 6.2 |
| Tab 4 | 表格 | Exp 3A: 消融结果矩阵（5 配置 × 4 benchmark 主指标 + Avg Prompt Tokens + Tool Call Error Rate） | Exp 6.3 |
| Tab 5 | 表格 | Exp 3B: 消融结果矩阵（4 配置 × Checkpoint Recall / Milestone 完成数 / Avg Token/Turn） | Exp 6.3 |
| Tab 6 | 表格 | Exp 4 Part A: 5 个 Harness × 11 维度 Feature Matrix（Claude Code / Codex CLI / OpenClaw / DeepAgents / DeerFlow 2.0） | Exp 6.4 |
| Tab 7 | 表格 | Exp 4 Part B: 5 种上下文策略 × 6 指标量化对比 | Exp 6.4 |
| Tab 8 | 表格 | 18 种上下文策略调研总结（Write-Select-Compress-Isolate 分类） | Sec 3 |

---

## 10. Related Work 定位

| 类别 | 代表工作 | 我们的区别 |
|------|---------|-----------|
| Agent Harness / 系统 | Claude Code, Codex CLI, OpenClaw, LangChain DeepAgents | 我们是**首个完整描述并开源**的 Agent Harness 架构论文，含 1.0→2.0 架构演进分析 + 系统性实验验证 |
| Agent 框架 | LangGraph, AutoGen, CrewAI | 我们在 LangGraph 之上构建 Harness（opinionated，内置最佳实践），不是另一个框架 |
| 上下文压缩（训练型） | ACON (ICLR'26 u.r.), CAT/SWE-Compressor, MEM1 (ICLR'26) | 我们是 zero-extra-LLM-cost 的工程优化，不需要额外训练或额外 LLM 调用 |
| 上下文压缩（规则型） | Claude Code MicroCompact, Anthropic Tool Clearing, OpenAI Compaction | 我们是首个在开源系统中实现 + 评估 MicroCompaction + Token Profiling 的工作 |
| 自主压缩决策 | Active Context Compression, Agent Focus | 我们用 middleware 链自动化触发，不占用 agent reasoning token |
| 上下文优化框架 | ACE (ICLR'26), PAACE, Sculptor | 我们是系统层面的工程优化，不是 RL/prompt 优化；有完整可运行系统而非仅算法 |
| Agent 记忆 | AgeMem, MemR3, MemInsight, MEM1 | 我们实现了 LLM 提取 + 结构化三区块存储 + token 预算注入的完整记忆管道，并在标准 benchmark 上量化其贡献 |
| 工具管理 | MemTool, OpenAI Tool Search, Spring AI Dynamic Discovery | 我们通过 tool_groups + SubagentLimitMiddleware 实现工具分组与并发控制，为进一步优化提供了可插拔基础 |
| 上下文工程综述 | Context Engineering Survey (arXiv:2507.13334), Anthropic Blog (2025) | 首个在开源系统中将四象限分类法落地为可运行 Harness 并进行系统性 benchmark 评估的工作 |

**核心差异化**（与 Exp 4 对比对象对齐）:

| 维度 | Claude Code | Codex CLI | OpenClaw | DeepAgents | **DeerFlow 2.0** |
|------|------------|-----------|---------|-----------|-----------------|
| 开源 | 是 | 是(Apache 2.0) | 是 | 是 | **是** |
| 架构论文 | 无 | 无 | 无 | 有(博客级) | **完整学术论文（含 1.0→2.0 演进）** |
| 架构模式 | Single Agent + 内部状态机 | Single Agent Loop (Rust) | Gateway + Agentic Loop | Single Agent + MW | **Lead Agent + 11 层 MW + Sub-agent** |
| Skills 体系 | CLAUDE.md | 无 | SKILLS.md + ClawHub | Skills (beta) | **SKILL.md + 渐进式加载 + 10 内置** |
| Sub-agent | 无 | 无 | 无 | 有（隔离） | **双线程池 + 类型化(GP/bash) + 3 并行** |
| 上下文摘要 | Auto-Compact + Rehydration | /compact (手动) | 自动摘要 | LLM 摘要 + 文件归档 | **参数化 SummarizationMW（trigger/keep 可配）** |
| 长期记忆 | ~/.claude (Markdown) | transcript resume | persistent memory (MD) | 无内置 | **LLM 提取 + 三区块 + 异步队列** |
| 沙箱执行 | 本地终端 | 本地 + sandbox policy | 本地 / VPS | 无内置 | **Local / Docker / K8s 三模式** |
| 全参数可配 | 有限 | CLI flags | config 文件 | MW 参数 | **全 YAML** |
| 四象限覆盖 | Compress 为主 | 仅 Compress | 部分 | Compress+Isolate | **Write+Select+Compress+Isolate 全覆盖** |

**定位总结**: DeerFlow 2.0 是首个**以完整架构演进为核心贡献**的开源 Agent Harness 论文。不是只提出一个优化技巧，而是：(1) 讲述从 Multi-Agent 到 Single Agent + Middleware 的架构演进故事；(2) 展示一个四象限全覆盖的分层 Harness 设计；(3) 通过四个标准 benchmark（GAIA / SWE-bench Verified / HumanEval / DeepPlanning） + 长对话质量保持 + Middleware 消融 + 业界对比，系统验证其作为通用 Harness 的价值。与 Exp 4 中 4 个对比对象的关键差异：**唯一同时具备 11 层显式 Middleware + 双线程池 Sub-agent + Skill 体系 + 三模式沙箱 + 跨会话结构化记忆，并附完整架构演进学术论文的开源 Harness**。

---

## 11. 风险与应对

| 风险 | 应对 |
|------|------|
| 审稿人认为「只是描述了一个系统」 | 架构演进（1.0→2.0）本身就是贡献；加上形式化框架 + 4 个增强模块(7 子模块) + 系统性实验（消融/通用性/业界对比）展示深度 |
| 审稿人认为「增强模块只是工程 trick」 | 18 种策略调研 → 系统化设计；Tool Output Lifecycle 和 Tool Schema Management 各有 3 层架构，有学术深度 |
| 1.0 vs 2.0 对比不公平（2.0 功能更多） | 明确说明：不是说 1.0 做得差，而是架构选型限制了天花板。比较的是**架构模式**，不是实现质量 |
| 某个 benchmark 结果低于预期 | 分析 Bare vs Full 的差距，用 Profiler 数据解释瓶颈；强调"可配置"而非"一刀切"；消融实验揭示各 Middleware 在该 benchmark 上的贡献 |
| 长对话质量不够稳定 | 调整参数，展示 Pareto 曲线中 quality 预设的表现 |
| 消融实验某层去掉后无影响 | 场景依赖性正好说明 YAML 可配的灵活性 |
| 审稿人质疑 vs Claude Code / Codex | 定位不同：DeerFlow 是**开源通用 Harness**，不是与闭源产品竞争。Exp 4 对比的是策略而非系统，且变量可控 |
| AAAI 主 track 认为工程性太强 | 备选投 IAAI / Demo / ICSE SEIP |

---

## 12. 参考文献（35 篇）

**Agent Harness / 系统**:
- LangGraph (LangChain)
- LangChain Blog: Deep Agents / Context Engineering for Agents (2025/2026)
- Anthropic: How We Built Our Multi-Agent Research System (engineering blog, 2025)
- OpenAI Codex CLI (GitHub, Apache 2.0, 2025): Lightweight terminal Agent with /compact command
- Devin/Cognition: Don't Build Multi-Agents (blog, 2025)
- Harrison Chase (LangChain): 红杉播客 on Long-horizon Agents (2026)

**上下文工程**:
- ACE: Agentic Context Engineering (ICLR 2026)
- PAACE: Plan-Aware Agent Context Engineering (arXiv:2512.16970)
- CAT: Context as a Tool / SWE-Compressor (arXiv:2512.22087)
- ACON: Optimizing Context Compression for Long-horizon LLM Agents (arXiv:2510.00615, ICLR 2026 under review)
- Active Context Compression: Autonomous Memory Management in LLM Agents (arXiv:2601.07190)
- Sculptor: Active Context Management (arXiv:2508.04664)
- Context Engineering for Large Language Models — Survey (arXiv:2507.13334)
- Anthropic Blog: Effective Context Engineering for AI Agents (Sep 2025)

**Agent 记忆**:
- AgeMem: Agentic Memory (arXiv:2601.01885)
- MEM1: Learning to Synergize Memory and Reasoning for Efficient Long-Horizon Agents (ICLR 2026)
- MemR3: Memory Retrieval via Reflective Reasoning (arXiv:2512.20237)
- MemInsight: Autonomous Memory Augmentation (EMNLP 2025)
- On the Structural Memory of LLM Agents (arXiv:2412.15266)
- Rethinking Memory in LLM based Agents (arXiv:2505.00675)
- Diagnosing Retrieval vs. Utilization Bottlenecks (arXiv:2603.02473)

**工具管理**:
- MemTool: Optimizing Short-Term Memory Management for Dynamic Tool Calling (arXiv:2507.21428)
- SWE-Pruner: Self-Adaptive Context Pruning for Coding Agents (arXiv:2601.16746)
- Factored Agents (arXiv:2503.22931)
- AgentOrchestra / TEA Protocol (arXiv:2506.12508)
- ReDel: Recursive Multi-Agent Systems (EMNLP 2024)
- CITI: Tool Utilizing (AAAI 2025)
- AutoTool (arXiv:2511.14650)

**工业实践**:
- Claude Code Compaction System (Decode Claude, reverse engineering)
- Anthropic: Context Editing / Tool Result Clearing (API docs, 2025)
- OpenAI: Tool Search API (developer docs, 2025)
- OpenAI Responses API Compaction (developer docs)
- Spring AI: Dynamic Tool Discovery (blog, Dec 2025)

**Multi-Agent 架构**:
- AutoGen: Enabling Next-Gen LLM Applications (Microsoft, 2023)
- CrewAI: Framework for Multi-Agent Collaboration
- CAMEL: Communicative Agents for "Mind" Exploration (NeurIPS 2023)
