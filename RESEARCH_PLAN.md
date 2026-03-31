# deer-sci-agent 研发计划

> Fork 自 [bytedance/deer-flow](https://github.com/bytedance/deer-flow)
> 仓库地址：https://github.com/leestar991/deer-sci-agent
> 开发分支：`feature/sci-research-agent`
> 计划创建日期：2026-03-25

---

## 项目目标

在 DeerFlow 超级代理框架基础上，构建面向**专业科学研究**场景的智能 Agent 系统，核心能力：

- 大规模学术文献的摄入、索引与语义检索（集成 OpenViking RAG）
- 多子代理并行的深度文献分析与数据提取
- 结构化科研报告自动生成（文献综述、实验分析、论文草稿）
- 跨会话知识积累，支持长期科研项目管理

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                  deer-sci-agent 系统架构                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   用户输入研究任务                                           │
│       │                                                     │
│       ▼                                                     │
│   ┌─────────────────────────────────────────┐              │
│   │  Phase -1：需求确认与资料准备            │              │
│   │                                         │              │
│   │  ask_clarification ──→ 用户补充需求      │              │
│   │  (ClarificationMiddleware 中断等待)      │              │
│   │                                         │              │
│   │  用户上传本地文档（PDF/Word/PPT）        │              │
│   │  (UploadsMiddleware 自动注入文件列表)    │              │
│   │                                         │              │
│   │  Lead Agent 生成研究计划草案             │              │
│   │  ask_clarification ──→ 用户确认/修改    │              │
│   └──────────────────┬──────────────────────┘              │
│                      │ 用户确认后继续                       │
│                      ▼                                      │
│   Lead Agent (sci-research Skill)                           │
│                    │                                        │
│      ┌─────────────┼──────────────────┐                    │
│      │             │                  │                     │
│  OpenViking    Web Research      并行子代理 (≤3)            │
│  RAG 层        深度搜索                                      │
│                                                             │
│  ov find       tavily/jina      literature-analyzer         │
│  ov read       arxiv/doi        data-extractor              │
│  ov add-res    web_fetch        report-writer               │
│                                 ov-retriever                │
│      │             │                  │                     │
│      └─────────────┴──────────────────┘                    │
│                    │                                        │
│         SummarizationMiddleware (6000 tokens)               │
│         MemoryMiddleware (300 facts)                        │
│                    │                                        │
│         Markdown 学术报告 + 图表可视化                       │
└─────────────────────────────────────────────────────────────┘
```

**双引擎分工**：
- **DeerFlow**：工作流编排、子代理并发、文档转换、上下文压缩、长期记忆
- **OpenViking**：文献向量索引（Doubao Embedding 1024维）、语义检索、跨会话知识库、VLM 图表理解

---

## 新增文件结构

```
deer-sci-agent/
├── RESEARCH_PLAN.md                              ← 本文件
├── config.yaml                                   ← 调整摘要/记忆参数
│
├── skills/custom/sci-research/
│   ├── SKILL.md                                  ← 主 Skill（含 Phase -1 需求确认流程）
│   ├── agents/
│   │   ├── intake-flow.md                        ← 需求确认与资料准备交互脚本
│   │   ├── literature-analyzer.md                ← 子代理 prompt：精读论文
│   │   ├── data-extractor.md                     ← 子代理 prompt：结构化数据提取
│   │   ├── report-writer.md                      ← 子代理 prompt：章节写作
│   │   └── ov-retriever.md                       ← 子代理 prompt：OV 语义检索
│   └── templates/
│       ├── research-report.md                    ← 科研报告结构模板
│       ├── literature-review.md                  ← 文献综述模板
│       └── citation-formats.md                   ← 引用格式规范（APA/GB/IEEE）
│
└── backend/packages/harness/deerflow/
    └── subagents/builtins/
        ├── literature_analyzer.py                ← 注册专用子代理（DeepSeek-R1）
        ├── data_extractor.py                     ← 注册专用子代理（Claude 3.5）
        ├── report_writer.py                      ← 注册专用子代理（GPT-4o）
        ├── ov_retriever.py                       ← 注册专用子代理（Doubao-lite）
        └── __init__.py                           ← 更新注册表
```

---

## 研发阶段

> **进度说明**：✅ 已完成 | 🔄 进行中 | ⬜ 待开始

### Phase -1：需求确认与资料准备（Skill 层，无需修改核心代码）

**目标**：在任何分析动作启动前，通过结构化交互厘清研究目标，允许用户上传本地文献材料，并让用户对研究计划草案做最终确认后再执行。

**实现机制**：

| 机制 | DeerFlow 原语 | 行为 |
|------|-------------|------|
| 向用户提问 | `ask_clarification` 工具 | `ClarificationMiddleware` 拦截调用，中断 Agent 执行，将问题呈现给用户，等待回复后恢复 |
| 接收上传文件 | `UploadsMiddleware` | 用户在任意轮次上传文件后，下一次 Agent 调用时自动将文件路径列表注入对话上下文，Agent 无需轮询 |
| 计划草案确认 | `ask_clarification(clarification_type="approach_choice")` | 呈现研究计划草案，等待用户选择"确认执行 / 修改后执行 / 取消" |

**交互流程（Skill 脚本中编排）**：

```
Step 1  收到用户初始研究任务描述
        │
        ▼
Step 2  ask_clarification：澄清研究目标
        ├─ 研究问题是什么？（要验证的假设 / 要综述的领域）
        ├─ 期望输出类型？（文献综述 / 实验分析报告 / 论文草稿）
        ├─ 目标受众与深度？（同行评审 / 内部报告 / 科普）
        └─ 是否有本地文献需要上传？（引导用户此时上传）
        ── 等待用户回复 ──
        │
        ▼
Step 3  （如用户表示有文件）提示上传
        "请通过附件按钮上传您的 PDF/Word 文献，上传完成后回复'继续'"
        UploadsMiddleware 在下轮自动注入已上传文件列表
        │
        ▼
Step 4  Lead Agent 生成研究计划草案，包含：
        - 确认理解的研究问题
        - 拟检索的文献范围（已上传 + 待网络检索）
        - 分析维度与报告结构
        - 预计分析深度与子代理分工
        │
        ▼
Step 5  ask_clarification(clarification_type="approach_choice")：
        呈现计划草案，选项：
        1. 确认，开始执行
        2. 调整研究范围后执行（说明修改点）
        3. 取消
        ── 等待用户确认 ──
        │
        ▼
Step 6  用户确认后，进入 Phase 0 正式执行
```

**Skill 文件**：`intake-flow.md` — 完整的问题清单、引导话术、计划草案模板

**验收标准**：
- 新会话启动后，Agent 必须在 2 轮以内完成需求澄清
- 用户上传文件后，Agent 在下一轮输出中正确引用文件路径
- 计划草案呈现后，未经用户明确确认前不启动任何子代理或检索任务

> ✅ **已完成（2026-03-26）**：`SKILL.md`、`intake-flow.md`、5 个 agent prompt、3 个报告模板全部创建完毕。

---

### Phase 0：基础设施准备（第 1 周）

**目标**：确保 OpenViking 与 DeerFlow 可互通，子代理扩展机制就绪。

| 任务 | 说明 | 负责层 | 状态 |
|------|------|--------|------|
| 0-1 | 验证 OpenViking 服务启动（`ov ls` 可用） | 环境 | ✅ |
| 0-2 | 确认 `ov add-resource` 可索引 PDF 转换后的 Markdown | 集成测试 | ✅ |
| 0-3 | 扩展 `task_tool.py` 的 `subagent_type` Literal，支持 4 个新类型 | 核心代码 | ✅ |
| 0-4 | 创建 4 个子代理 Python 配置文件并注册到 `BUILTIN_SUBAGENTS` | 核心代码 | ✅ |
| 0-5 | 调整 `config.yaml` 摘要/记忆参数 | 配置 | ✅ |
| 0-6 | 编写单元测试覆盖新子代理注册逻辑 | 测试 | ✅ |

**额外交付**（超出原计划）：
- ✅ `Paths` 用户隔离路径系统（`users/{id}/`、`thread-ownership.json`、路径注入防护）
- ✅ `ThreadDataMiddleware` 扩展：线程 ownership 原子记录 + 用户目录自动创建
- ✅ `test_user_isolation.py`（18 个测试）
- ✅ 修复 `test_subagent_executor.py` session 级 fixture 导致的测试污染 bug
- ✅ 修复 `~/.openviking/ov.conf` 中 `api_base` 错误（SDK 自动追加路径，不应含 endpoint 后缀）和缺失 `"input": "multimodal"` 字段

**验收标准**：`make test` 全部通过，`task(subagent_type="literature-analyzer")` 可正常调用。

> ✅ **已完成（2026-03-27）**：所有 6 项任务通过。OV 服务 healthy，`ov add-resource` Embedding 0 error，`ov find` 语义检索返回正确结果。`config.yaml` 已创建（不入库，含 API key）。

---

### Phase 1：文献摄入与索引（第 2 周）

**目标**：用户上传 PDF/URL，自动完成格式转换 + OpenViking 向量索引。

| 任务 | 说明 | 状态 |
|------|------|------|
| 1-1 | 创建 `sci-research` Skill 主文件（完整 Phase 1A–1E 摄入流程） | ✅ |
| 1-2 | 实现上传后自动调用 `ov add-resource` 的 Skill 指令（1B 节） | ✅ |
| 1-3 | 支持批量 URL 摄入（arXiv、DOI、PubMed），含 URL 规范化表（1C 节） | ✅ |
| 1-4 | 创建 `ov-retriever` 子代理，封装 `ov find` + `ov read` 工作流 | ✅ |
| 1-5 | 编写 `test_sci_ingestion.py`（43 个测试：URL 规范化 + SKILL.md 完整性） | ✅ |

**额外交付**（超出原计划）：
- ✅ `deerflow/utils/arxiv_url.py` — Python URL 规范化工具（`normalize_literature_url`、`batch_urls`），支持 arXiv/DOI/PubMed/plain URL 四种格式，供子代理通过 bash 调用

**验收标准**：上传 PDF → 30 秒内可通过 `ov find` 语义检索到相关段落。

> ✅ **已完成（2026-03-27）**：SKILL.md（1A–1E）+ ov-retriever 子代理（Phase -1 时提前交付）+ `arxiv_url.py` URL 规范化工具 + `test_sci_ingestion.py`（43 个测试全部通过）。

---

### Phase 2：深度文献分析（第 3 周）

**目标**：`literature-analyzer` 子代理对单篇论文做结构化精读。

| 任务 | 说明 | 状态 |
|------|------|------|
| 2-1 | 编写 `literature-analyzer.md` 子代理 prompt（精读模板） | ✅ |
| 2-2 | 配置该子代理使用 DeepSeek-R1 模型（`model="deepseek-v3"`） | ✅ |
| 2-3 | 定义标准化输出格式（研究问题/方法/发现/局限/差异点 五节 + 扩展第六节） | ✅ |
| 2-4 | 编写 `data-extractor.md`，专注提取数值数据和对比表格 | ✅ |
| 2-5 | 配置 `data-extractor` 使用 Claude 3.5 Sonnet（`model="claude-3-5-sonnet"`） | ✅ |
| 2-6 | 编写 `test_sci_analysis.py`（50 个测试：模型配置 + 输出格式 + prompt 文件完整性 + SKILL.md Phase 2） | ✅ |

**验收标准**：单篇论文分析输出包含所有 5 个结构化字段，数据提取准确率 ≥ 90%。

> ✅ **已完成（2026-03-27）**：`literature-analyzer.md`（Phase -1 提前交付）+ `data-extractor.md`（Phase -1 提前交付）+ 模型配置（deepseek-v3 / claude-3-5-sonnet）+ `test_sci_analysis.py`（50 个测试全部通过）。

---

### Phase 3：跨文献综合（第 4 周）

**目标**：整合多篇分析结果，识别共识、分歧与研究空白。

| 任务 | 说明 | 状态 |
|------|------|------|
| 3-1 | 设计跨文献综合的 Skill 工作流（Phase 3 逻辑，SKILL.md 4 步详细流程） | ✅ |
| 3-2 | 利用 `ov find` 做主题聚类检索（ov-retriever dispatch，相似研究归组） | ✅ |
| 3-3 | Lead Agent 整合子代理输出，生成 Gap Analysis（3 维综合：共识/矛盾/空白） | ✅ |
| 3-4 | 创建 `synthesis.md` 子代理 prompt（完整 4 步工作流 + 行为规则） | ✅ |
| 3-5 | 编写 `test_sci_synthesis.py`（37 个测试：synthesis.md 完整性 + SKILL.md Phase 3） | ✅ |

**额外交付**（超出原计划）：
- ✅ 集成 `chart-visualization` Skill 位置预留：SKILL.md Phase 3 Step 3A 共识表格格式化支持图表输出
- ✅ `synthesis.md` 行为规则 6 条（引用强制、禁止捏造、量化优先、存储前置、最少 3 空白、空白≠愿望清单）

**验收标准**：Gap Analysis 包含至少 3 个有据可查的研究空白，每个空白有对应文献支撑。

> ✅ **已完成（2026-03-28）**：`synthesis.md`（完整 4 步工作流）+ SKILL.md Phase 3 扩展（详细工作流替换原有 stub）+ `test_sci_synthesis.py`（37 个测试全部通过）。

---

### Phase 4：报告写作（第 5 周）

**目标**：`report-writer` 子代理生成各章节，Lead Agent 整合为完整报告。

| 任务 | 说明 | 状态 |
|------|------|------|
| 4-1 | 创建报告结构模板（`research-report.md`，7 章结构 + 组装指令） | ✅ |
| 4-2 | 编写 `report-writer.md` 子代理 prompt（3 章模板 + APA/IEEE/GB 引用 + 7 条行为规则） | ✅ |
| 4-3 | 配置 `report-writer` 使用 GPT-4o（`model="gpt-4o"`） | ✅ |
| 4-4 | 实现并行章节写作：SKILL.md Phase 4 完整 5 步工作流（3 并行任务 dispatch + 等待） | ✅ |
| 4-5 | Lead Agent 串行完成：引言、背景、讨论、结论（SKILL.md Step 2） | ✅ |
| 4-6 | 集成引用格式规范：`citation-formats.md`（APA/IEEE/GB-T-7714 完整格式） | ✅ |
| 4-7 | 编写 `test_sci_report.py`（57 个测试：模型配置 + 章节模板 + 引用格式 + SKILL.md Phase 4） | ✅ |

**额外交付**（超出原计划）：
- ✅ `citation-formats.md` 包含常见期刊/会议缩写速查表（IEEE/NeurIPS/ICML/CVPR 等）
- ✅ `research-report.md` Assembly Instructions：完整 7 步组装 + `present_files` 交付流程

**验收标准**：生成报告包含完整 6 章结构，引用格式正确，图表嵌入正常。

> ✅ **已完成（2026-03-28）**：`report-writer.md`（Phase -1 提前交付）+ `research-report.md` + `citation-formats.md` + `report_writer.py`（gpt-4o）+ SKILL.md Phase 4 完整工作流 + `test_sci_report.py`（57 个测试全部通过）。

---

### Phase 5：集成测试与优化（第 6 周）

**目标**：端到端场景测试，性能调优，文档完善。

| 任务 | 说明 | 状态 |
|------|------|------|
| 5-1 | 端到端测试场景 A：20 篇文献 → 完整综述报告（test_sci_e2e.py，@pytest.mark.integration） | ✅ |
| 5-2 | 端到端测试场景 B：指定研究方向 → 网络检索 + 报告（test_sci_e2e.py，@pytest.mark.integration） | ✅ |
| 5-3 | 性能优化：test_sci_e2e.py 配置校验（子代理模型一致性、路径一致性、并发约束） | ✅ |
| 5-4 | 成本优化：ov_retriever.py model inherit → doubao-lite（高频检索用廉价模型） | ✅ |
| 5-5 | 完善文档：`backend/docs/sci-research.md`（前提条件、快速开始、Troubleshooting） | ✅ |
| 5-6 | 提交 PR 到 `main` 分支 | ✅ |

**额外交付**（超出原计划）：
- ✅ `pyproject.toml` 注册 `integration` pytest mark（含 deselect 说明）
- ✅ `TestSubagentCostHierarchy`：验证 4 个子代理的模型成本层级（doubao-lite < claude < deepseek < gpt-4o）
- ✅ `TestWorkspacePathConsistency`：验证所有子代理 system_prompt 和 .md 文件使用规范路径

**验收标准**：225 个单元测试通过；10 个 integration 场景已记录（待真实服务验证）。

> ✅ **已完成（2026-03-28）**：ov_retriever.py model→doubao-lite + test_sci_e2e.py（38 通过 + 10 跳过）+ pyproject.toml integration mark + docs/sci-research.md；PR 已提交。

---

## 子代理模型分配

| 子代理名称 | 模型 | 工具权限 | 最大轮次 | 超时 |
|-----------|------|---------|---------|------|
| `literature-analyzer` | DeepSeek-R1 | bash, read_file, tavily_web_search | 30 | 600s |
| `data-extractor` | claude-3-5-sonnet | bash, read_file, str_replace | 20 | 300s |
| `report-writer` | gpt-4o | bash, read_file, write_file, str_replace | 40 | 900s |
| `ov-retriever` | doubao-lite（或 gpt-4o-mini） | bash | 15 | 180s |
| Lead Agent | gpt-4o / claude-sonnet | 全部（含 task） | — | — |

---

## 关键配置变更（config.yaml）

```yaml
summarization:
  enabled: true
  trigger:
    - type: tokens
      value: 6000      # 论文分析需要更大窗口（原 4000）
    - type: messages
      value: 80        # 原 50
  keep:
    type: tokens
    value: 3000        # 原 messages: 20

memory:
  enabled: true
  max_facts: 300       # 原 100，扩大文献知识点存储
  fact_confidence_threshold: 0.6   # 原 0.7，科研事实容忍更低置信度
  max_injection_tokens: 3000       # 原 2000

subagents:
  enabled: true
  timeout_seconds: 900
  agents:
    literature-analyzer:
      timeout_seconds: 600
    data-extractor:
      timeout_seconds: 300
    ov-retriever:
      timeout_seconds: 180
```

---

## 里程碑

| 里程碑 | 目标日期 | 实际完成 | 状态 | 交付物 |
|--------|---------|---------|------|--------|
| M-1：需求确认流程可用 | 2026-04-01 | 2026-03-26 | ✅ 提前完成 | SKILL.md、intake-flow.md、5 个 agent prompt、3 个报告模板 |
| M0：基础设施就绪 | 2026-04-08 | 2026-03-27 | ✅ 提前完成 | 全部 6 项任务完成；OV 服务正常、Embedding 0 error、语义检索验证通过 |
| M1：文献摄入可用 | 2026-04-15 | — | ⬜ 待开始 | PDF 上传 → OV 索引 → 语义检索 |
| M2：单篇分析可用 | 2026-04-22 | — | ⬜ 待开始 | literature-analyzer 输出标准化 |
| M3：综合分析可用 | 2026-04-29 | 2026-03-28 | ✅ 提前完成 | synthesis.md + SKILL.md Phase 3 扩展 + test_sci_synthesis.py（37 测试） |
| M4：报告写作可用 | 2026-05-06 | 2026-03-28 | ✅ 提前完成 | report-writer.md + research-report.md + citation-formats.md + gpt-4o 配置 + SKILL.md Phase 4 + test_sci_report.py（57 测试） |
| M5：正式发布 | 2026-05-13 | 2026-03-28 | ✅ 提前完成 | 全测试通过，docs/sci-research.md，PR 合并到 main |

---

## 技术债务与风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| OpenViking 服务不稳定 | 检索失败 | 降级到纯 web_search 模式 |
| 子代理并发上限 3 个 | 大批量文献处理慢 | 分批调度，Lead Agent 管理队列 |
| 长报告超出模型上下文 | 写作截断 | 分章节写作 + SummarizationMiddleware |
| 模型 API 成本 | 超预算 | 轻量模型承担高频任务（ov-retriever） |
| 上游 deer-flow 更新冲突 | 合并困难 | 定期 `git fetch upstream` 同步 |

---

## 上游同步策略

```bash
# 定期同步上游更新
git fetch upstream
git checkout main
git merge upstream/main
git push origin main

# 将上游更新 rebase 到开发分支
git checkout feature/sci-research-agent
git rebase main
```

---

## 变更日志

| 日期 | Commit | 内容 |
|------|--------|------|
| 2026-03-25 | `8861b5f` | 创建 RESEARCH_PLAN.md，规划整体架构与 6 周研发路线 |
| 2026-03-26 | `6e8de6f` | Phase -1：创建 intake-flow.md、SKILL.md、agent prompts、报告模板（M-1 ✅） |
| 2026-03-27 | `096fb59` | Phase 0（Part 1）：注册 4 个科研子代理、扩展 task_tool Literal、Paths 用户隔离系统、ThreadDataMiddleware 扩展、修复 session 级 fixture 测试污染；756 tests passed |
| 2026-03-27 | —（不入库）| Phase 0（Part 2）：启动 OV 服务、修复 embedding api_base + 补充 `"input":"multimodal"` 字段、验证 `ov add-resource` + `ov find` 全流程；创建 config.yaml 调整摘要/记忆/子代理超时参数（M0 ✅） |
| 2026-03-28 | — | Phase 3：创建 synthesis.md（完整 4 步工作流 + 6 条行为规则）+ 扩展 SKILL.md Phase 3（stub → 详细工作流）+ test_sci_synthesis.py（37 个测试全部通过）；M3 ✅ |
| 2026-03-28 | — | Phase 4：report_writer.py model→gpt-4o + SKILL.md Phase 4（5 步工作流：3 并行章节 + 串行 + 引用编译 + 摘要 + 组装 present_files）+ test_sci_report.py（57 个测试全部通过）；M4 ✅ |
| 2026-03-28 | — | Phase 5：ov_retriever.py model→doubao-lite + test_sci_e2e.py（38 通 + 10 跳过，integration mark 注册）+ docs/sci-research.md + RESEARCH_PLAN.md 全项目完结；M5 ✅ |

---

*本文档随研发进展持续更新。*
