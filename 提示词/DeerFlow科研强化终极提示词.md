# DeerFlow 科研适配深度强化 —— 学术论文写作能力极致化提示词

---

## 你的角色

你是一位同时精通以下三大领域的世界级系统架构师：

1. **AI Agent 系统工程**：深度掌握 LangGraph 状态机编排、多 Agent 协作、中间件链设计、工具系统扩展、Prompt Engineering 系统化方法论
2. **学术研究方法论**：精通从选题到投稿的全生命周期，涵盖 STEM、社会科学、人文学科的差异化研究范式（定量/定性/混合方法），熟悉 Nature/Science/IEEE/ACM/Springer/Elsevier/中文核心 的投稿规范
3. **科研工具链**：精通 LaTeX 排版生态（BibTeX/BibLaTeX/natbib）、Zotero/Mendeley 文献管理、SPSS/R/Python 统计分析、Overleaf 协同编辑、系统综述方法论（PRISMA/Meta-Analysis）、学术诚信规范

你的任务是对 DeerFlow 进行**第三轮深度强化**，将其学术论文写作能力从"可用"（当前 95% 覆盖率）提升到"卓越"——即达到**博士生/青年教师日常科研工作的核心生产力工具**水平。

---

## 背景信息：DeerFlow 当前架构全景

### 技术栈
- **后端**: LangGraph + LangChain + FastAPI（Python 3.12+）
- **前端**: Next.js 16 + React 19 + TypeScript + Tailwind CSS 4
- **核心架构**: Lead Agent → 11 层中间件链 → 子 Agent 编排（general-purpose / bash）→ 沙箱执行

### 核心系统
1. **Agent 系统**: Lead Agent 通过 `apply_prompt_template()` 生成系统提示词，包含 `<role>`, `<thinking_style>`, `<clarification_system>`, `<skill_system>`, `<subagent_system>`, `<academic_research>`, `<citations>`, `<critical_reminders>` 等段落
2. **技能系统**: 通过 `skills/public/` 下的 `SKILL.md`（YAML frontmatter + Markdown 正文）定义，运行时注入到 Lead Agent 的 system prompt，由 `get_skills_prompt_section()` 渲染为 `<available_skills>` XML
3. **工具系统**: 配置工具（web_search/web_fetch/image_search）+ 沙箱工具（bash/ls/read_file/write_file/str_replace）+ MCP 工具 + 内置工具（present_files/ask_clarification/view_image/task）
4. **子 Agent**: `general-purpose`（所有工具，排除 task）和 `bash`（命令执行专用），最多 3 个并发，15 分钟超时
5. **沙箱**: Local / Docker / K8s 三种模式，虚拟路径 `/mnt/user-data/{workspace,uploads,outputs}` + `/mnt/skills`
6. **记忆系统**: 事实抽取（preference/knowledge/context/behavior/goal/research/literature/experiment）+ 上下文注入
7. **引用系统**: web 引用 `[citation:TITLE](URL)` + 学术引用（APA/GB-T/IEEE/BibTeX）

### 已有学术技能矩阵（7 个专用技能 + 3 个通用技能）

| 技能 | 核心能力 | 当前深度评估 |
|------|---------|:----------:|
| `academic-writing` | IMRaD 结构、LaTeX 生成、摘要/关键词、润色、Cover Letter、Rebuttal | ⭐⭐⭐ |
| `literature-review` | Semantic Scholar/arXiv/CrossRef API 搜索、BibTeX 管理、Related Work 生成 | ⭐⭐⭐ |
| `statistical-analysis` | 17 种统计动作、APA 报告、学术级可视化 | ⭐⭐⭐⭐ |
| `academic-ppt` | python-pptx 原生 PPTX、6 种学术风格、公式渲染 | ⭐⭐⭐ |
| `research-code` | 论文→代码、项目脚手架、基准测试 | ⭐⭐⭐ |
| `experiment-tracking` | MLflow/W&B/本地追踪、可复现性 | ⭐⭐⭐ |
| `dataset-search` | HF/UCI/Kaggle/OpenML/PapersWithCode | ⭐⭐⭐ |
| `deep-research` | 4 阶段网络研究（广域→深潜→验证→检查） | ⭐⭐⭐⭐ |
| `data-analysis` | DuckDB/SQL 数据探索 | ⭐⭐⭐ |
| `chart-visualization` | 26 种图表类型 | ⭐⭐⭐⭐ |

### Lead Agent 提示词中的关键段落（当前状态）

**`<academic_research>` 段落**（位于 `backend/src/agents/lead_agent/prompt.py` 的 `SYSTEM_PROMPT_TEMPLATE`）：
- 11 条技能路由规则（关键词→技能映射）
- 8 条跨技能协同流程
- 引用处理规则
- 公式/记号支持

**`<citations>` 段落**：
- Web 引用：`[citation:TITLE](URL)`
- 学术引用：APA 7th / GB/T 7714 / IEEE / BibTeX

**记忆系统提示词**（`backend/src/agents/memory/prompt.py`）：
- `research` 类别：研究方向、方法论偏好、目标期刊/会议
- `literature` 类别：已读论文、引用库、研究影响源
- `experiment` 类别：实验进度、模型配置、数据集使用、结果里程碑

### 关键架构约束（你必须遵守）

1. **技能定义格式**: `SKILL.md` = YAML frontmatter（name, description）+ Markdown 正文，运行时只有 name 和 description 注入 system prompt，正文由 Agent 通过 `read_file` 按需加载
2. **工具注册**: 通过 `config.yaml` 的 `tools` 字段 + `resolve_variable()` 动态加载，或通过 MCP 配置
3. **子 Agent 继承**: 子 Agent 继承父 Agent 全部工具（排除 task/ask_clarification/present_files），最多 3 并发，超时默认 15 分钟
4. **沙箱可执行**: bash 命令 + Python 脚本（通过 `bash` 工具或 `write_file` + `bash` 组合）
5. **输出路径**: 所有最终交付物必须存放在 `/mnt/user-data/outputs/`，通过 `present_files` 呈现
6. **技能渐进加载**: Lead Agent 先看 description 决定是否加载，再用 `read_file` 读取完整 SKILL.md

---

## 第三轮强化目标：六大维度 × 深度攻坚

### ===== 维度一：学术论文写作能力极致化 =====

**目标**: 将 `academic-writing` 从"模板化写作助手"进化为"学术写作智能副驾"

#### 1.1 研究方法论智能顾问（全新能力）

当前缺失：Agent 不理解不同研究范式的差异，无法根据研究类型调整写作策略。

**需要新增的能力矩阵**:

| 研究范式 | 论文结构差异 | 方法论模板 | 写作策略 |
|---------|------------|----------|---------|
| **实证定量研究** | 严格 IMRaD | 假设→变量→取样→统计检验 | 数据驱动，强调统计显著性 |
| **设计科学研究** | 问题→设计→评估→贡献 | DSR 循环（Hevner 框架） | 人工物导向，强调实用贡献 |
| **质性研究** | 主题分析/扎根理论 | 编码→范畴→理论构建 | 叙事丰富，强调深度理解 |
| **混合方法研究** | 并行/顺序/嵌套设计 | QUAL + QUAN 整合 | 三角验证，互补解释 |
| **系统综述/Meta-Analysis** | PRISMA 流程图 + 森林图 | 检索策略→筛选→质量评估→综合 | 系统性，强调方法透明 |
| **案例研究** | Yin 框架 | 单案例/多案例/嵌入式 | 命题驱动，模式匹配 |
| **综述论文** | 分类体系→主题综合→未来方向 | 文献图谱→缺口分析 | 综合批判，前瞻性强 |

**实施要求**：
在 `academic-writing/SKILL.md` 中新增 `## Phase 0: Research Paradigm Detection & Adaptation` 段落，包含：

```markdown
## Phase 0: Research Paradigm Detection & Adaptation

### Step 0.1: Identify Research Paradigm

Before generating any content, identify the research paradigm by analyzing:
1. **User's explicit statement** ("I'm doing a qualitative study...")
2. **Research question type** (causal → quantitative, exploratory → qualitative)
3. **Data type** (numerical → quantitative, text/interview → qualitative)
4. **Discipline conventions** (CS → design science/empirical, Sociology → qualitative/mixed)

### Paradigm-Specific Adaptations

#### Quantitative Empirical Research
- Structure: Strict IMRaD with Hypotheses subsection
- Required sections: Research Model/Framework figure, Variable Operationalization table
- Methods must include: Sample size justification (power analysis), Validity & Reliability measures
- Results: Statistical tables (three-line), effect sizes, confidence intervals
- Discussion: Support/reject hypotheses, practical vs. statistical significance

#### Design Science Research (DSR)
- Structure: Problem → Objectives → Design → Development → Demonstration → Evaluation → Communication
- Required: Design Requirements table, Artifact Description, Evaluation Framework
- Must reference: Hevner et al. (2004) guidelines, Peffers et al. (2007) process
- Evaluation: Formative + Summative, utility demonstration

#### Systematic Review / Meta-Analysis
- Structure: PRISMA-compliant
- Required: PRISMA flow diagram, Search strategy table (per database), Quality assessment
- Synthesis: Narrative synthesis or statistical meta-analysis (forest plot, heterogeneity I²)
- Registration: Mention PROSPERO registration (if applicable)
- Generate PRISMA flow diagram using Mermaid:
  ```mermaid
  graph TD
      A[Records identified through database searching<br/>n = ???] --> C[Records after duplicates removed<br/>n = ???]
      B[Additional records from other sources<br/>n = ???] --> C
      C --> D[Records screened<br/>n = ???]
      D --> E[Records excluded<br/>n = ???]
      D --> F[Full-text articles assessed<br/>n = ???]
      F --> G[Full-text excluded with reasons<br/>n = ???]
      F --> H[Studies included in qualitative synthesis<br/>n = ???]
      H --> I[Studies included in meta-analysis<br/>n = ???]
  ```

#### Qualitative Research
- Structure: Flexible — Introduction → Literature → Methodology → Findings → Discussion
- Methods: Data collection (interviews/observation/documents), Coding strategy (open/axial/selective), Trustworthiness criteria (credibility, transferability, dependability, confirmability)
- Findings: Theme-based with thick description and participant quotes
- Reflexivity: Researcher positionality statement

#### Mixed Methods Research
- Specify design type: Convergent, Explanatory Sequential, Exploratory Sequential
- Joint display table for QUAL + QUAN integration
- Meta-inferences section for integrated findings
```

#### 1.2 论文迭代修订系统（全新能力）

当前缺失：Agent 只能一次性生成文稿，无法模拟真实的"写→审→改→再审"循环。

**需要新增**:

```markdown
## Phase 6: Iterative Revision & Self-Review

### Step 6.1: Academic Self-Review Checklist

After generating any manuscript section, automatically run an internal review:

**Structure Review**:
- [ ] Does each paragraph have exactly ONE main idea?
- [ ] Is there a clear topic sentence followed by supporting evidence?
- [ ] Do transitions between paragraphs maintain logical flow?
- [ ] Is the paragraph length appropriate (150-300 words for body paragraphs)?
- [ ] Are claims properly hedged? (avoid overclaiming)

**Argumentation Review**:
- [ ] Is the research gap clearly articulated?
- [ ] Are contributions specific, measurable, and falsifiable?
- [ ] Does every claim have supporting evidence (citation or data)?
- [ ] Is there circular reasoning anywhere?
- [ ] Are limitations honestly acknowledged?
- [ ] Is the novelty clearly differentiated from prior work?

**Statistical Integrity Review** (for empirical papers):
- [ ] Are all statistics complete? (test statistic, df, p-value, effect size, CI)
- [ ] Is the correct statistical test used for the data type?
- [ ] Are multiple comparisons corrected?
- [ ] Is sample size adequate? (power analysis referenced?)
- [ ] Are assumptions stated and tested?

**Language Review**:
- [ ] No first person in formal academic writing (use "this study", "the authors")
  - Exception: Qualitative research may use first person deliberately
- [ ] No informal language or contractions
- [ ] Consistent terminology throughout
- [ ] Active voice for methods ("We collected"), passive for results where conventional
- [ ] Abbreviations defined on first use

**Citation Review**:
- [ ] All factual claims cited
- [ ] No orphan citations (cited but not in reference list, or vice versa)
- [ ] Self-citation ratio reasonable (<20%)
- [ ] Recent references included (>30% from last 3 years for active fields)
- [ ] Seminal/foundational works included
- [ ] Citation diversity (not over-relying on one research group)

### Step 6.2: Simulated Peer Review

When the user asks "review my paper" or "check my manuscript", simulate a rigorous peer review:

**Review Template**:
```text
## Peer Review Report

### Overall Assessment
[Accept / Minor Revision / Major Revision / Reject]

### Summary
[2-3 sentence summary of the paper's contribution]

### Strengths
1. [Specific strength with evidence from the manuscript]
2. [Specific strength]
3. [Specific strength]

### Weaknesses (Major)
1. [Specific weakness with detailed explanation and suggested fix]
2. [Specific weakness]

### Weaknesses (Minor)
1. [Minor issue]
2. [Minor issue]

### Questions for Authors
1. [Specific question that challenges a claim or assumption]

### Detailed Comments
- **Introduction, Para 3**: [Specific feedback]
- **Section 3.2, Eq. (4)**: [Specific feedback]
- **Table 2**: [Specific feedback]

### Recommendation
[Detailed recommendation with conditions for acceptance]
```

### Step 6.3: Revision Tracking

When revising based on feedback (reviewer comments or self-review):
1. Generate a **change log** with specific location (Section, Page, Line range)
2. Use **colored annotations** (in LaTeX: `\textcolor{blue}{revised text}`)
3. Generate the **Response to Reviewers** document simultaneously
4. Track which reviewer comments have been addressed vs. rebutted
```

#### 1.3 期刊/会议智能推荐引擎（全新能力）

当前缺失：Agent 不能根据论文内容推荐合适的投稿目标。

```markdown
## Phase 7: Venue Recommendation & Submission Strategy

### Step 7.1: Venue Matching

Based on the manuscript content, recommend suitable venues:

**Analysis Dimensions**:
1. **Topic Alignment**: Match keywords against venue scopes
2. **Methodology Fit**: Some venues favor empirical, others theoretical
3. **Impact Level**: Top-tier (Nature/Science/AAAI), mid-tier, or specialized
4. **Turnaround Time**: Fast track vs. standard review
5. **Open Access**: OA requirements (many funders require OA)
6. **Geographic Preference**: Chinese journals, international venues

**Use web_search to look up**:
- Current venue CFP (Call for Papers)
- Recent accepted paper topics
- Impact Factor / CiteScore / h5-index
- Acceptance rates
- Average review time

**Output Format**:

| Rank | Venue | Type | IF/h5 | Fit Score | Review Time | Notes |
|:----:|-------|------|:-----:|:---------:|:-----------:|-------|
| 1 | [Name] | Journal | X.X | ⭐⭐⭐⭐⭐ | ~3 months | [Why it fits] |
| 2 | [Name] | Conference | h5=XX | ⭐⭐⭐⭐ | [Deadline] | [Why it fits] |
| 3 | [Name] | Journal | X.X | ⭐⭐⭐⭐ | ~6 months | [Why it fits] |

### Step 7.2: Submission Checklist Generation

For the selected venue, generate a tailored submission checklist:

- [ ] Manuscript formatted per venue template
- [ ] Word/page count within limits
- [ ] Abstract within word limit
- [ ] Required sections present (e.g., Data Availability Statement)
- [ ] Figures meet resolution/format requirements (EPS/TIFF for print)
- [ ] Supplementary materials prepared
- [ ] Author contributions statement (CRediT taxonomy)
- [ ] Conflict of interest disclosure
- [ ] Ethics approval statement (if applicable)
- [ ] Data and code availability statement
- [ ] ORCID for all authors
- [ ] Cover letter drafted
- [ ] Suggested and excluded reviewers listed
```

#### 1.4 长文档项目管理（全新能力）

当前缺失：Agent 的记忆系统无法有效管理跨会话的长篇论文/学位论文写作。

```markdown
## Phase 8: Long Document Project Management

### For Thesis / Dissertation / Book-length Projects

#### Project Registry (via Memory System)

When the user initiates a thesis/long-document project, create a project registry:

```json
{
  "project_type": "doctoral_thesis",
  "title": "...",
  "discipline": "...",
  "institution": "...",
  "advisor": "...",
  "chapters": [
    {"number": 1, "title": "Introduction", "status": "draft_complete", "word_count": 5200},
    {"number": 2, "title": "Literature Review", "status": "in_progress", "word_count": 3400},
    {"number": 3, "title": "Methodology", "status": "outlined", "word_count": 0},
    {"number": 4, "title": "Results", "status": "not_started", "word_count": 0},
    {"number": 5, "title": "Discussion", "status": "not_started", "word_count": 0},
    {"number": 6, "title": "Conclusion", "status": "not_started", "word_count": 0}
  ],
  "total_target_words": 80000,
  "deadline": "2026-09-01",
  "citation_style": "APA7",
  "master_bib_file": "references.bib",
  "key_decisions": [
    "Using mixed methods design",
    "Primary framework: Technology Acceptance Model (TAM)"
  ]
}
```

#### Cross-Chapter Consistency

When writing/revising any chapter:
1. **Terminology consistency**: Maintain a project glossary, flag inconsistent terms
2. **Narrative arc**: Each chapter's conclusion must bridge to the next chapter's introduction
3. **Citation consistency**: Use the same master BibTeX file, check for orphan refs
4. **Notation consistency**: Same variables, same formatting throughout
5. **Forward/backward references**: "As discussed in Chapter 2..." / "Chapter 4 will demonstrate..."

#### Progress Dashboard

Generate a progress summary on request:

```markdown
## Thesis Progress Dashboard

**Overall**: 8,600 / 80,000 words (10.8%)
**Deadline**: 2026-09-01 (169 days remaining)
**Required pace**: ~423 words/day

| Chapter | Status | Words | Target | Progress |
|---------|--------|------:|-------:|:--------:|
| Ch.1 Introduction | ✅ Draft | 5,200 | 8,000 | ████████░░ 65% |
| Ch.2 Literature | 🔄 In Progress | 3,400 | 15,000 | ██░░░░░░░░ 23% |
| Ch.3 Methodology | 📋 Outlined | 0 | 12,000 | ░░░░░░░░░░ 0% |
| Ch.4 Results | ⬜ Not Started | 0 | 20,000 | ░░░░░░░░░░ 0% |
| Ch.5 Discussion | ⬜ Not Started | 0 | 15,000 | ░░░░░░░░░░ 0% |
| Ch.6 Conclusion | ⬜ Not Started | 0 | 10,000 | ░░░░░░░░░░ 0% |

**Next Actions**:
1. Complete Literature Review Chapter 2 (11,600 words remaining)
2. Start Methodology outline
```
```

#### 1.5 学术图表自动编号与交叉引用系统

当前缺失：生成的论文中图表没有自动编号和交叉引用。

```markdown
## Cross-Reference System

When generating a multi-section paper, maintain a reference registry:

**Auto-Numbering Rules**:
- Figures: Fig. 1, Fig. 2, ... (sequential across entire document)
- Tables: Table 1, Table 2, ...
- Equations: (1), (2), ... or (Section.Number) for long documents
- Algorithms: Algorithm 1, Algorithm 2, ...
- Theorems/Lemmas: Theorem 1, Lemma 1, ...

**Cross-Reference Format**:
- In text: "As shown in Fig. 1, ...", "The results in Table 3 indicate..."
- In LaTeX: \ref{fig:architecture}, \ref{tab:results}, \ref{eq:loss}
- NEVER use "the figure above/below" — always use numbered references

**Consistency Check**:
- Every figure/table MUST be referenced at least once in the text
- Every figure/table MUST have a caption
- Figures: caption below; Tables: caption above (standard convention)
- All figures/tables must appear AFTER their first reference in text
```

#### 1.6 学术写作风格精细化控制

```markdown
## Discipline-Specific Writing Conventions

### Computer Science / AI
- Contributions as numbered list in Introduction
- "We" is acceptable (first person plural)
- Algorithm pseudocode expected for novel methods
- Experimental comparison tables are mandatory
- Ablation study expected for system papers

### Social Sciences
- Hypotheses formally stated with direction (H1, H2, ...)
- Literature review as separate major section
- Participants (not "subjects") for human studies
- Effect sizes mandatory alongside p-values
- Limitations section is substantial

### Natural Sciences
- Methods section must enable exact replication
- Materials subsection with supplier details
- Results and Discussion may be combined
- SI (International System of Units) mandatory
- Gene/protein nomenclature follows field conventions

### Humanities
- Longer, more discursive paragraphs acceptable
- Extensive footnotes/endnotes
- Primary source analysis central
- Theoretical framing prominent
- May use first person singular

### Engineering
- Design specifications and constraints explicit
- Performance metrics quantified
- Comparison with industry standards
- Practical implications emphasized
- Cost/feasibility analysis may be included

### Medical / Clinical
- CONSORT checklist for RCTs
- STROBE checklist for observational studies
- Ethics approval statement mandatory
- Patient privacy (de-identification) documented
- Clinical significance distinct from statistical significance
```

---

### ===== 维度二：文献综述能力深度强化 =====

#### 2.1 系统综述方法论支持（PRISMA）

在 `literature-review/SKILL.md` 中新增：

```markdown
## Phase 5: Systematic Review Protocol

### PRISMA-Compliant Systematic Review

When the user requests a systematic review, follow this protocol:

#### Step 5.1: Protocol Registration
- Recommend registering on PROSPERO (for health/medical) or OSF (other fields)
- Generate protocol document with:
  - Research question (PICO/PEO format)
  - Eligibility criteria (inclusion/exclusion)
  - Information sources and search strategy
  - Study selection process
  - Data extraction plan
  - Quality assessment tool (e.g., Newcastle-Ottawa Scale, CASP, JBI)
  - Synthesis method (narrative or quantitative)

#### Step 5.2: Comprehensive Search

Execute multi-database search with documented strategy:

| Database | Search String | Results | Date |
|----------|--------------|:-------:|------|
| Semantic Scholar | [query] | N | YYYY-MM-DD |
| arXiv | [query] | N | YYYY-MM-DD |
| CrossRef | [query] | N | YYYY-MM-DD |
| Google Scholar (via web_search) | [query] | N | YYYY-MM-DD |
| PubMed (if medical) | [query] | N | YYYY-MM-DD |

#### Step 5.3: Screening Pipeline

```python
# Automated first-pass screening based on title/abstract
screening_criteria = {
    "include_keywords": ["machine learning", "deep learning"],
    "exclude_keywords": ["review", "survey", "editorial"],
    "year_range": (2020, 2026),
    "min_citations": 5,  # for established work
    "languages": ["en"],
}
```

#### Step 5.4: Quality Assessment

For each included study, rate on standardized criteria:

| Study | Relevance | Rigor | Bias Risk | Quality Score |
|-------|:---------:|:-----:|:---------:|:------------:|
| [Paper 1] | High | Medium | Low | 8/10 |
| [Paper 2] | High | High | Low | 9/10 |

#### Step 5.5: Evidence Synthesis

**Narrative Synthesis**: Theme-based integration with strength-of-evidence ratings
**Quantitative Synthesis** (Meta-Analysis): If applicable, generate:
- Forest plot (effect sizes + CIs)
- Heterogeneity statistics (Q, I², τ²)
- Funnel plot (publication bias assessment)
- Sensitivity analysis (leave-one-out)
```

#### 2.2 文献计量分析

```markdown
## Phase 6: Bibliometric Analysis

### When the user wants to understand a field's landscape:

1. **Publication Trend**: Papers per year in the topic area
2. **Top Authors**: Most prolific and most cited authors
3. **Top Venues**: Journals/conferences with most publications
4. **Keyword Co-occurrence**: Identify emerging subtopics
5. **Citation Network**: Identify foundational and bridging papers
6. **Country/Institution Analysis**: Geographic distribution of research

Generate visualizations using the statistical-analysis skill:
- Publication trend line chart
- Author collaboration network (if data available)
- Keyword cloud / co-occurrence matrix
- Citation distribution histogram
```

#### 2.3 前向/后向引用追踪

```markdown
## Forward & Backward Citation Tracing

### Backward (References of a paper)
Use Semantic Scholar API to get a paper's references:
```bash
python -c "
import json, urllib.request
paper_id = '[SEMANTIC_SCHOLAR_ID]'
url = f'https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references?fields=title,authors,year,citationCount,venue&limit=50'
req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
for ref in data.get('data', []):
    cited = ref.get('citedPaper', {})
    print(f'- [{cited.get(\"year\",\"?\")}] {cited.get(\"title\",\"?\")} (Citations: {cited.get(\"citationCount\",0)})')
"
```

### Forward (Papers that cite this paper)
```bash
python -c "
import json, urllib.request
paper_id = '[SEMANTIC_SCHOLAR_ID]'
url = f'https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations?fields=title,authors,year,citationCount,venue&limit=50'
req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
for cit in data.get('data', []):
    citing = cit.get('citingPaper', {})
    print(f'- [{citing.get(\"year\",\"?\")}] {citing.get(\"title\",\"?\")} (Citations: {citing.get(\"citationCount\",0)})')
"
```

### Snowball Search Strategy
1. Start with 3-5 seed papers (highly relevant, well-cited)
2. Backward trace: Identify foundational references shared across seeds
3. Forward trace: Find recent work building on seeds
4. Iterate: Check new high-relevance papers' references
5. Stop when: No new relevant papers emerge (saturation)
```

---

### ===== 维度三：Lead Agent 提示词深度重构 =====

**目标**: 将 `<academic_research>` 段落从简单的路由表升级为真正的"学术意识层"

#### 3.1 重构后的 `<academic_research>` 段落设计

```python
# 替换 backend/src/agents/lead_agent/prompt.py 中的 <academic_research> 段落

ACADEMIC_RESEARCH_SECTION = """<academic_research>
**You have deep academic research capabilities. When the user's request relates to scholarly work, activate this specialized behavior layer.**

### 1. Research Intent Classification

Before routing to any skill, classify the user's intent:

| Intent Category | Indicators | Primary Skill | Supporting Skills |
|----------------|-----------|---------------|-------------------|
| **Writing a new paper** | "write", "draft", "manuscript", "paper" | academic-writing | literature-review, statistical-analysis |
| **Literature investigation** | "find papers", "literature review", "what research exists" | literature-review | deep-research |
| **Data analysis for research** | "analyze my data", "statistics", "hypothesis test" | statistical-analysis | data-analysis, chart-visualization |
| **Reproduce/implement a paper** | "implement this algorithm", "reproduce", "code from paper" | research-code | experiment-tracking |
| **Create academic slides** | "presentation", "defense slides", "conference talk" | academic-ppt | academic-writing |
| **Full research project** | "research project on X", "study X comprehensively" | [orchestrate all] | [all academic skills] |
| **Revise existing manuscript** | "review my paper", "improve", "polish", "revise" | academic-writing (Phase 6) | — |
| **Prepare for submission** | "submit to", "cover letter", "format for journal" | academic-writing (Phase 5+7) | — |
| **Systematic review** | "systematic review", "meta-analysis", "PRISMA" | literature-review (Phase 5) | statistical-analysis |
| **Thesis/dissertation work** | "thesis", "dissertation", "chapter" | academic-writing (Phase 8) | literature-review |

### 2. Academic Orchestration Patterns

For complex academic tasks, use multi-agent decomposition:

**Pattern A: Paper Writing Pipeline**
```
Turn 1 (3 parallel subagents):
  ├── Subagent 1: literature-review → search & collect relevant papers
  ├── Subagent 2: deep-research → gather non-academic context & trends
  └── Subagent 3: dataset-search → find relevant datasets/benchmarks

Turn 2 (synthesize Turn 1 results, then):
  ├── Subagent 1: academic-writing → generate paper outline + Introduction
  └── Subagent 2: academic-writing → generate Related Work from collected references

Turn 3:
  ├── Subagent 1: academic-writing → Methodology + Experiments sections
  └── Subagent 2: statistical-analysis → analyze data if available

Final Turn: Synthesize all sections → complete manuscript → self-review
```

**Pattern B: Systematic Review Pipeline**
```
Turn 1 (3 parallel subagents):
  ├── Subagent 1: literature-review → Semantic Scholar search
  ├── Subagent 2: literature-review → arXiv search
  └── Subagent 3: literature-review → CrossRef + Google Scholar search

Turn 2: Merge, deduplicate, screen
Turn 3: Quality assessment + data extraction
Turn 4: Synthesis + PRISMA flow diagram + write-up
```

**Pattern C: Thesis Chapter Pipeline**
```
Turn 1: Load project registry from memory → identify current chapter
Turn 2 (parallel):
  ├── Subagent 1: literature-review → chapter-specific references
  └── Subagent 2: academic-writing → draft chapter

Turn 3: Self-review → consistency check with other chapters
```

### 3. Academic Quality Standards (Always Apply)

When generating ANY academic content:

**Evidence Hierarchy** (cite the highest available):
1. Systematic reviews / Meta-analyses
2. Randomized controlled trials
3. Cohort / Case-control studies
4. Cross-sectional surveys
5. Expert opinion / Anecdotal evidence

**Claim Strength Calibration**:
- Strong evidence → "demonstrates", "establishes", "confirms"
- Moderate evidence → "suggests", "indicates", "supports"
- Weak/preliminary → "may", "appears to", "preliminary evidence suggests"
- No evidence → DO NOT make the claim

**Academic Integrity**:
- NEVER fabricate citations (if unsure, search first or state "citation needed")
- NEVER invent statistics or data points
- NEVER present AI-generated text as the user's original work without disclosure
- Always note when information could not be verified

### 4. Research Context Awareness (Memory-Enhanced)

Leverage the memory system to provide contextually aware assistance:

- **Remember the user's research direction** → Don't re-ask about their topic
- **Track their writing progress** → Know which sections are complete
- **Maintain their citation library** → Reuse references from prior conversations
- **Recall methodology decisions** → Don't contradict earlier choices
- **Know their target venue** → Apply correct formatting throughout

### 5. Formula & Notation Excellence

- Use LaTeX notation: inline `$...$` and display `$$...$$`
- Number all display equations: `$$ \\mathcal{L} = ... \\tag{1} $$`
- Reference equations by number: "as shown in Eq. (1)"
- Use standard notation for the user's discipline:
  - ML: $\\theta$ for parameters, $\\mathcal{L}$ for loss, $\\nabla$ for gradients
  - Statistics: $\\mu$, $\\sigma$, $H_0$, $H_1$, $\\alpha$, $\\beta$, $p$
  - Physics: $\\hbar$, $\\psi$, $\\hat{H}$
- Define ALL notation at first use

### 6. Citation Intelligence

**Smart Citation Behaviors**:
- When the user mentions a paper vaguely ("that attention paper"), search to find it
- When writing a section, proactively suggest papers that should be cited
- Detect when a claim lacks citation → add "[citation needed]" marker
- When collecting references, automatically generate BibTeX entries
- Track DOIs and prefer DOI-based citations for permanence

**Citation Density Guidelines**:
- Introduction: 3-5 citations per paragraph
- Related Work: 5-10 citations per subsection
- Methodology: 1-3 citations for established methods
- Results: Minimal (your own data)
- Discussion: 2-4 citations per paragraph (for comparison)
</academic_research>"""
```

#### 3.2 `<citations>` 段落增强

```python
# 替换现有的 <citations> 段落

CITATIONS_SECTION = """<citations>
**Context-Aware Citation System**

Automatically select the citation format based on context:

| Context | Format | Example |
|---------|--------|---------|
| General web response | Web citation | `[citation:TITLE](URL)` |
| Paper Introduction/RelatedWork | Numbered inline | "Recent work [1, 2] has shown..." |
| APA-style manuscript | APA 7th parenthetical | "(Author, Year)" or "Author (Year)" |
| IEEE-style manuscript | IEEE numbered | "[1]" |
| GB/T 7714 manuscript | GB/T sequential | "[1]" with Chinese format |
| LaTeX document | BibTeX keys | `\\cite{author2024title}` |
| Presentation slides | Abbreviated | "(Author et al., Year)" |

**Auto-Detection Rules**:
- If the user is writing a paper with `academic-writing` skill → use the specified citation format
- If no format specified → default to APA 7th for English, GB/T 7714 for Chinese
- If generating LaTeX → always use `\\cite{}` commands with BibTeX
- If in casual conversation → use web citation format

**Citation Integrity**:
- ALWAYS include the DOI when available
- VERIFY paper existence before citing (use Semantic Scholar / CrossRef API if uncertain)
- For preprints, clearly mark as "Preprint" or "arXiv:XXXX.XXXXX"
- For retracted papers, explicitly warn the user
</citations>"""
```

---

### ===== 维度四：记忆系统科研深度适配 =====

#### 4.1 记忆系统提示词增强

在 `backend/src/agents/memory/prompt.py` 的 `MEMORY_UPDATE_PROMPT` 中，对科研类别进行深度扩展：

```python
# 在 Facts Extraction 的 Categories 部分，将 research/literature/experiment 扩展为：

"""
  * research: Research direction, methodology preferences, target venues, ongoing studies,
    theoretical frameworks adopted, research paradigm (quantitative/qualitative/mixed/DSR),
    co-authors and collaborators, funding sources, ethics approvals, writing language preferences
  * literature: Key papers read with full metadata (title, authors, year, venue, DOI),
    citation format preference, BibTeX keys used, foundational papers in their field,
    papers they've cited in manuscripts, systematic review protocols, reference manager used
  * experiment: Experiment progress with run IDs, model configurations (hyperparameters, 
    architecture choices), dataset versions used, evaluation metrics and best results achieved,
    hardware setup (GPU type, memory), reproducibility seeds, failed approaches and why,
    baseline comparisons completed
  * writing_progress: Current manuscript title and status, chapters/sections completed,
    word count per section, target venue and its requirements, submission deadlines,
    reviewer feedback received, revision round number, co-author assignments
"""
```

#### 4.2 新增 `writing_progress` 记忆类别

在 `FACT_EXTRACTION_PROMPT` 中新增：

```python
"""
- writing_progress: Manuscript title and status, sections completed, target venue,
  deadlines, revision history, reviewer feedback themes
"""
```

---

### ===== 维度五：跨技能协同流程精细化 =====

#### 5.1 新增协同路径

在 Lead Agent 的 `<academic_research>` 段落的跨技能协同部分，新增以下高级协同路径：

```markdown
### Advanced Cross-Skill Coordination

**Path 9: Systematic Review → Meta-Analysis → Paper**
1. `literature-review` (Phase 5) → PRISMA search across databases
2. `statistical-analysis` → meta-analysis (forest plot, heterogeneity)
3. `academic-writing` → PRISMA-compliant manuscript
4. `academic-ppt` → conference presentation of review findings

**Path 10: Grant Proposal Pipeline**
1. `literature-review` → identify research gaps and justify significance
2. `deep-research` → gather funding body priorities, success stories
3. `academic-writing` → generate proposal sections (Specific Aims, Significance, Innovation, Approach)
4. Budget justification + timeline Gantt chart via `chart-visualization`

**Path 11: Thesis Defense Preparation**
1. `academic-writing` (Phase 8) → thesis document status check
2. `academic-ppt` → defense presentation (45-50 slides)
3. Anticipate committee questions → generate Q&A preparation document
4. Generate 1-page thesis summary / extended abstract

**Path 12: Paper Revision Pipeline**
1. User uploads reviewer comments
2. `academic-writing` (Phase 6) → parse comments into structured list
3. For each comment: determine action (revise text / add analysis / rewrite section / rebut)
4. `statistical-analysis` → run additional analyses if requested by reviewer
5. `academic-writing` → generate Response to Reviewers document
6. Generate diff/tracked-changes version
```

---

### ===== 维度六：新增专用技能 =====

#### 6.1 `grant-writing` 基金申请书撰写技能

```yaml
---
name: grant-writing
description: Use this skill when the user needs to write grant proposals, funding applications, or research project bids. Covers NSF, NIH, NSFC (国自然), ERC, and other funding bodies. Provides proposal structure templates, budget justification, specific aims generation, and compliance checking. Trigger on queries like "write a grant proposal", "apply for funding", "NSFC application", "research proposal", or any request involving securing research funding.
---
```

核心流程：
- Phase 1: 资助方需求分析（解析 CFP、匹配资助方向）
- Phase 2: 提纲生成（按资助方模板：NSF → 15 页限制，国自然 → 申请书正文 8 部分）
- Phase 3: 各部分撰写（研究意义、研究内容、技术路线、研究基础、经费预算）
- Phase 4: 质量审查（创新性、可行性、团队匹配度打分）
- Phase 5: 预算正当性说明

#### 6.2 `academic-integrity` 学术诚信检查技能

```yaml
---
name: academic-integrity
description: Use this skill to check manuscripts for academic integrity issues. Performs citation verification, self-plagiarism detection hints, authorship ethics review, data fabrication red flags, and compliance with publication ethics guidelines (COPE, ICMJE). Trigger on queries like "check my paper", "academic integrity", "citation check", "plagiarism concerns", or before final submission.
---
```

核心流程：
- Phase 1: 引用完整性检查（每个声明是否有引用支撑）
- Phase 2: 引用验证（通过 API 验证引用的论文是否真实存在）
- Phase 3: 逻辑一致性检查（摘要与正文是否一致、数据与结论是否匹配）
- Phase 4: 学术规范检查（COPE 指南、CRediT 作者贡献、利益冲突声明）
- Phase 5: 生成诚信检查报告

---

## 实施优先级与实施方式

### P0（立即实施，直接修改现有文件）

| # | 优化项 | 实施方式 | 修改文件 |
|---|-------|---------|---------|
| 1 | `<academic_research>` 段落全面重构 | 替换现有段落 | `backend/src/agents/lead_agent/prompt.py` |
| 2 | `<citations>` 段落智能化升级 | 替换现有段落 | `backend/src/agents/lead_agent/prompt.py` |
| 3 | `academic-writing` Phase 0 研究范式检测 | 在现有 SKILL.md 开头新增 | `skills/public/academic-writing/SKILL.md` |
| 4 | `academic-writing` Phase 6 迭代修订系统 | 在现有 SKILL.md 末尾新增 | `skills/public/academic-writing/SKILL.md` |
| 5 | `academic-writing` Phase 7 期刊推荐 | 在现有 SKILL.md 末尾新增 | `skills/public/academic-writing/SKILL.md` |
| 6 | `academic-writing` 学科差异化写作规范 | 在现有 SKILL.md 中新增 | `skills/public/academic-writing/SKILL.md` |
| 7 | `academic-writing` 交叉引用系统 | 在现有 SKILL.md 中新增 | `skills/public/academic-writing/SKILL.md` |
| 8 | `literature-review` 系统综述协议(PRISMA) | 在现有 SKILL.md 末尾新增 | `skills/public/literature-review/SKILL.md` |
| 9 | `literature-review` 前向/后向引用追踪 | 在现有 SKILL.md 末尾新增 | `skills/public/literature-review/SKILL.md` |
| 10 | `literature-review` 文献计量分析 | 在现有 SKILL.md 末尾新增 | `skills/public/literature-review/SKILL.md` |
| 11 | 记忆系统科研类别深度扩展 | 修改现有分类描述 | `backend/src/agents/memory/prompt.py` |

### P1（第二批实施，新建文件）

| # | 优化项 | 实施方式 | 新建文件 |
|---|-------|---------|---------|
| 12 | `academic-writing` Phase 8 长文档项目管理 | 在现有 SKILL.md 中新增 | `skills/public/academic-writing/SKILL.md` |
| 13 | `grant-writing` 基金申请撰写技能 | 新建 SKILL.md | `skills/public/grant-writing/SKILL.md` |
| 14 | `academic-integrity` 学术诚信检查技能 | 新建 SKILL.md | `skills/public/academic-integrity/SKILL.md` |
| 15 | Lead Agent 路由规则更新（+2 条） | 修改 | `backend/src/agents/lead_agent/prompt.py` |

### P2（季度级别，可后续实施）

| # | 优化项 | 类型 |
|---|-------|------|
| 16 | 前端 LaTeX 实时编辑器（CodeMirror） | 前端 UI |
| 17 | 文献管理面板 UI（引用库可视化） | 前端 UI |
| 18 | Overleaf MCP 集成 | MCP 配置 |
| 19 | 查重预检工具（SimHash/MinHash） | Tool |
| 20 | 贝叶斯分析脚本（PyMC） | Script |
| 21 | 结构方程模型脚本（semopy） | Script |
| 22 | R 语言支持（Docker 镜像） | 基础设施 |

---

## 输出要求

### 你需要输出的内容

1. **修改后的完整文件**：对于每个需要修改的文件，输出修改后的完整内容（不要只输出 diff）
2. **新建文件的完整内容**：对于新建的 SKILL.md，输出完整的技能定义
3. **变更清单**：列出所有变更的文件、变更类型（新增/修改）、变更摘要
4. **测试验证方案**：给出 3 个端到端测试用例，验证增强后的能力

### 质量标准

- 所有 SKILL.md 中的代码块必须可直接执行（Python 脚本、bash 命令）
- 提示词文本不超过 LLM 的上下文窗口限制（每个 SKILL.md 控制在 20K tokens 以内）
- 所有新增的跨技能协同路径必须在 Lead Agent 提示词中有对应的路由规则
- 引用格式示例必须符合 APA 7th / GB/T 7714-2015 / IEEE 的官方规范
- 新增的记忆类别必须与 `MEMORY_UPDATE_PROMPT` 和 `FACT_EXTRACTION_PROMPT` 同步更新

### 约束条件

- 不修改 Python 代码逻辑，只修改提示词和 Markdown 技能文件
- 保持与现有 17 个通用技能的兼容性
- 保持 SKILL.md 的 YAML frontmatter + Markdown 格式规范
- 新增技能的 description 字段必须包含充分的触发关键词，以确保 Lead Agent 能准确路由
- 所有文件路径使用 `/mnt/skills/public/` 和 `/mnt/user-data/` 虚拟路径体系
