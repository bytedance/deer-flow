# RFC-003: 系统级外骨骼挽具、工具循环拦截与多智能体类型化交接规范
**Route C: Agentic Harness, Tool-Loop Interception & Typed Subagent Handoff Specification**

- **文档状态 (Status)**: PROPOSED / In Review
- **制定日期 (Date)**: 2026-10-27
- **关联理论 (Theoretical Foundations)**:
  - 《AI Agent 理论与工程实践》（ai-agent-book）第 2 章《上下文工程》、第 4 章《工具》、第 10 章《多 Agent 协作》
  - Google Research: *Recursive Agent Harnessing for an Open World* (arXiv:2610.14224, `harness2`)
  - `ai-memory` 规范: 类型化交接单状态机 (`crates/ai-memory-core/src/handoff.rs`)

---

## 1. 背景与核心问题定义 (Motivation & Problem Statement)

在完成 **路线 A（上下文精简与工具剪枝）** 和 **路线 B（分层长期记忆子系统）** 之后，DeerFlow 的单智能体在上下文膨胀和跨轮记忆衰减问题上已得到根本性治理。然而，在复杂工程任务与多子智能体协同场景中，系统仍面临三大严重的工程瓶颈：

### 1.1 痛点一：工具循环报错死循环（Doom Loop of Failing Tool Calls）
- **现象**：
  当工具调用失败（例如 `bash` 命令因依赖缺失报 `ModuleNotFoundError`、或脚本路径错误报 `FileNotFoundError`），模型往往不会停下来分析根本原因，而是陷入**盲目重试死循环（Doom Loop）**：
  反复执行相同的错误命令，或在两个不同报错的工具之间交替调用（$A \to B \to A \to B$）。
- **根因**：
  DeerFlow 原生的 `loop_detection_middleware.py` 仅对 `(tool_name, args)` 做精确 Hash 统计。只要模型在参数中修改了一个字符（例如换行符或多加了一个空格），或者交替调用不同工具，现有哈希窗口就会完全失效，任由模型耗尽最大步数限制（Recursion Limit），消耗数万无意义 Token。
- **危害**：
  任务失败率飙升，Token 预算被空转吞噬，用户体验极差。

### 1.2 痛点二：常驻 Prompt 膨胀与技能治理缺失（"Always-On Prose is a Liability"）
- **现象**：
  为了赋予 Agent 各种专业技能，传统做法是将大量 Skill 的描述与规则长文本硬塞进 System Prompt（即 `lead_agent/prompt.py` 中数千行的常驻 Prompt）。
- **根因**：
  违背了 Google Research `harness2` 提出的**组件成本梯次法则**：
  $$\text{Skills（按需触发）} \succ \text{Scripts（确定性沙箱脚本）} \succ \text{Subagents（大输入小输出）} \succ \text{Plugin/Hooks（工具循环强拦截）} \succ \text{Always-On Prose（最后底线）}$$
  常驻文本不仅每轮都在消耗输入 Token 配额，还会严重稀释模型的注意力分配（Attention Dilution），引发注意力腐化（Context Rot）。
- **危害**：
  技能越多，模型遵循核心指令的能力反而越弱。

### 1.3 痛点三：多智能体协作上下文缺乏结构化交接（Untyped Subagent Handoff）
- **现象**：
  Lead Agent 通过 `task` 工具将子任务派发给 Subagent（如 `bash_agent` 或 `general-purpose`）后，子智能体执行完成返回的仅是一大段非结构化的自然语言文本。
- **根因**：
  缺乏类型化交接单（Typed Handoff）。Lead Agent 面对数百行子智能体返回的文本时，必须重新花费大量 Token 进行长文理解和提取；当子智能体遭遇阻塞或部分成功时，Lead Agent 无法明确获知“哪些路径已经尝试失败”、“哪些是不可逆致命阻塞”、“留下了哪些具体产物句柄”，导致 Lead Agent 经常重复踩坑、重复调用。

---

## 2. 架构设计与三大核心支柱 (Architecture & The Three Pillars)

针对上述三大痛点，路线 C 引入三大互补的系统级治理模块：

```
                    ┌────────────────────────────────────────────────────────┐
                    │               DeerFlow Runtime (Harness)               │
                    └───────────────────────────┬────────────────────────────┘
                                                │
         ┌──────────────────────────────────────┼──────────────────────────────────────┐
         ▼                                      ▼                                      ▼
【支柱 1：工具循环拦截与靶向纠错】    【支柱 2：动态技能即时路由 (JIT)】     【支柱 3：类型化交接单 (Handoff)】
  ToolLoopInterceptorMiddleware          DynamicSkillRouter                   TypedSubagentHandoff
  - 报错签名识别 (Regex Pattern)         - 零 LLM 触发意图匹配                - attempted_paths 记录
  - 靶向纠错提示 (Targeted Hint)         - 动态注入 Skill Context             - fatal_blocks 强阻断
  - 交替振荡死循环识别                   - 保证常驻 Prompt 极度精简           - deliverable_handles 句柄
  - 写后验证栅栏 (Write-Verify)                                               - remaining_goals 待办
```

### 2.1 支柱 1：智能工具循环拦截器 (`ToolLoopInterceptorMiddleware`)

在 Tool Loop 层面提供唯一的**非自然语言硬性约束手段**：
1. **报错签名分类器（Error Signature Classifier）**：
   通过预设的高性能正则与规则库，实时捕获工具返回中的典型崩溃签名：
   - `MODULE_NOT_FOUND`: `ModuleNotFoundError: No module named '(\w+)'`
   - `COMMAND_NOT_FOUND`: `command not found: (\w+)` / `'(\w+)' 不是内部或外部命令`
   - `FILE_NOT_FOUND`: `FileNotFoundError: .*? '(.*?)'` / `No such file or directory`
   - `PERMISSION_DENIED`: `PermissionError: .*?` / `Access is denied`
   - `SYNTAX_ERROR`: `SyntaxError: invalid syntax`
   - `PORT_IN_USE`: `Address already in use` / `Errno 98`
2. **定向靶向提示词（Targeted Hint Injection）**：
   一旦命中特征错误，立即在当前 ToolMessage 之后追加一个瞬时靶向提示（Targeted Hint），强行阻断模型的幻觉：
   > `[HARNESS INTERCEPTOR] 提示：检测到缺失 Python 依赖包 '{package}'。严禁重复运行原脚本！请先执行 'pip install {package}' 成功后再继续。`
3. **模糊与交替循环检测（Fuzzy & Alternating Loop Guard）**：
   不仅比对精确哈希，还比对最近 $K$ 步的工具调用序列模式：
   - 连续同工具报错 $\ge 2$ 次：触发靶向干预；
   - 交替震荡模式（如 $A \to B \to A \to B$）重复出现：强制中断工具调用，强迫模型输出当前思考与阻碍。
4. **写后语法验证栅栏（Write-Verify Gate）**：
   在写入关键可执行脚本（`.py`, `.json`）后，通过底层钩子自动进行 `ast.parse` 或 `json.loads` 校验。若存在语法错误，直接就地返回错误语法位置，无需等待模型执行报错。

### 2.2 支柱 2：动态技能即时路由与成本阶梯治理 (`DynamicSkillRouter`)

严格遵循 `Always-On Prose is the Expensive Option` 原则：
1. **常驻 Prompt 瘦身**：
   将 `lead_agent/prompt.py` 中散落的各种领域操作指令全部抽离为独立的 Skill 模块，保持系统 System Prompt 极简（保证 KV Cache 击穿率最低）。
2. **轻量级零 LLM 意图路由器（Zero-LLM Intent Matcher）**：
   基于用户输入和任务意图，采用关键词与 BM25 局部语义匹配，毫秒级判定当前轮次所需激活的技能集合。
3. **按需即时注入（Just-In-Time Skill Injection）**：
   仅在命中相关意图的轮次，将对应 `SKILL.md` 注入单轮 `skill_context`，任务完成后自动卸载，不污染后续上下文。

### 2.3 支柱 3：子智能体类型化交接单协议 (`TypedSubagentHandoff`)

吸收 `ai-memory` 的工业级 Handoff 状态机模型，在 Lead Agent ↔ Subagent 间建立结构化契约：

```python
class TypedHandoff(BaseModel):
    """类型化子任务交接契约."""
    status: Literal["completed", "blocked", "partial", "failed"]
    attempted_paths: list[str] = Field(description="已尝试的技术路径与对应结果")
    fatal_blocks: list[str] = Field(description="无法绕过的致命阻碍（防止重试踩坑）")
    deliverable_handles: list[str] = Field(description="生成的关键产物物理句柄（文件路径/URL/ID）")
    remaining_goals: list[str] = Field(description="未完成的目标与推荐交接步骤")
    execution_summary: str = Field(description="精炼的执行摘要（<= 200 字）")
```

1. **子智能体端结构化提取**：
   子智能体终结时，不仅返回文本，更将其格式化为标准的 `TypedHandoff` 数据包，挂载在 `ToolMessage.additional_kwargs["typed_handoff"]`。
2. **父智能体端结构化呈现**：
   `task_tool` 在接收到子智能体结果时，自动将交接单渲染为紧凑的 XML/Markdown 区块：
   ```xml
   <subagent_handoff status="completed">
     <deliverables>
       - /f/deer-flow/workspace/sales_report.csv
       - /f/deer-flow/workspace/analysis.md
     </deliverables>
     <fatal_blocks>None</fatal_blocks>
     <attempted_paths>
       - Pandas group-by calculation: SUCCESS
     </attempted_paths>
     <next_actions>Lead agent can now synthesize the report for user.</next_actions>
   </subagent_handoff>
   ```
3. **消除无效重试与长文阅读成本**：
   Lead Agent 看到结构化产物句柄和明确的 `fatal_blocks`，无需解析数千字流水账即可直接进行下一步编排。

---

## 3. 评测指标与验证标准 (Success Criteria & Acceptance Verification)

| 维度 | 现状基线 | 路线 C 预期目标 | 验证手段 |
| :--- | :--- | :--- | :--- |
| **报错死循环率 (Doom Loops)** | 遇到环境缺失/依赖错误时，70%+ 概率反复重试 3~6 次直至超时 | **0 次无脑死循环**：首次报错即注入靶向提示，二次报错强制阻断 | 构造依赖缺失与文件缺失测试集，验证拦截与靶向提示触发率 100% |
| **多智能体交接 Token 开销** | 每次子任务返回 1,500 ~ 4,000 tokens 全量文本流水账 | 结构化交接单控制在 **$\le 350$ tokens**，直达核心交付物 | 对比子任务交接前后输入 Token 占用与解析准确率 |
| **写操作语法崩溃率** | 写入损坏的 Python/JSON 后直接执行报错，消耗排错轮次 | **写后即时语法校验拦截率 100%**，在执行前完成阻断纠偏 | 编写包含缩进/括号错误的写文件测试用例，验证写后即时拦截 |
| **自动化测试通过率** | N/A | **100% 通过**，覆盖拦截器、循环检测、交接单与全链路协同 | `pytest backend/tests/test_route_c_*.py` 全部绿色 |

---

## 4. 实施里程碑 (Implementation Roadmap)

1. **Step 1: 制定并冻结 RFC-003 设计规范**（本文件）。
2. **Step 2: 实现核心工具拦截与靶向纠错中间件** (`deerflow/agents/middlewares/harness_guard_middleware.py`)。
3. **Step 3: 实现类型化交接单状态机** (`deerflow/subagents/typed_handoff.py`) 并集成进 `task_tool.py`。
4. **Step 4: 编写严谨的单元测试与模拟测试套件** (`test_harness_guard.py`, `test_typed_handoff.py`)。
5. **Step 5: 真实多轮任务联合验收与生成验收报告**。
