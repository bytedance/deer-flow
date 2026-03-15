---
name: grant-writing
description: Use this skill when the user needs to write grant proposals, funding applications, or research project bids. Covers NSF, NIH, NSFC (国家自然科学基金), ERC, and other funding bodies. Provides proposal structure templates, budget justification, specific aims generation, significance articulation, and compliance checking. Trigger on queries like "write a grant proposal", "apply for funding", "NSFC application", "NSF proposal", "research proposal", "funding application", "基金申请", "项目申请书", or any request involving securing research funding.
---

# Grant Writing Skill

## Overview

This skill provides a comprehensive methodology for writing competitive research grant proposals. It covers the full lifecycle from identifying funding opportunities to drafting, reviewing, and finalizing proposals for submission to major funding bodies worldwide.

## When to Use This Skill

**Always load this skill when:**

- User wants to write a grant proposal or funding application
- User needs help with NSFC (国自然), NSF, NIH, ERC, or other funding body applications
- User asks for research proposal writing assistance
- User needs to articulate research significance and innovation
- User wants budget justification writing
- User needs to structure a Specific Aims page

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Proposal Structure** | Templates for NSF, NIH, NSFC, ERC, and generic proposals |
| **Specific Aims** | Structured aims page generation |
| **Significance** | Research significance and broader impacts articulation |
| **Innovation** | Novelty statement and differentiation from prior work |
| **Approach** | Research plan with timeline and milestones |
| **Budget** | Budget justification and narrative |
| **Compliance** | Format and content compliance checking |

## Workflow

### Phase 0.5: Grant Writing Multi-Pass Strategy

| Round | Focus | Output |
|:-----:|-------|--------|
| **1 — Skeleton** | Specific Aims 1-page + section headings + key figures | 20% |
| **2 — Logic** | Full argument chain: problem → gap → approach → why it works | 60% |
| **3 — Evidence** | Preliminary data, citations, budget details | 90% |
| **4 — Polish** | Language, compliance, formatting, page limits | 100% |
| **5 — Mock Review** | Self-review using Phase 5 scoring + 10 questions (Phase 5.5) | Revisions |

**"Aims Page First" Rule**: Write Specific Aims FIRST. If it doesn't fit on 1 page, the proposal isn't clear enough.

### Phase 1: Funding Opportunity Analysis

#### Step 1.1: Identify Suitable Funding

When the user has a research idea but no specific funder:

1. Use `web_search` to find relevant calls for proposals
2. Match research topic to funder priorities
3. Check eligibility requirements (career stage, institution, nationality)
4. Note deadlines and submission requirements

#### Step 1.2: Analyze the Call for Proposals

Extract from the CFP:
- **Funding body priorities**: What topics/themes are emphasized?
- **Page/word limits**: Strict compliance required
- **Required sections**: Each funder has specific section requirements
- **Review criteria**: How proposals are evaluated
- **Budget limits**: Maximum funding amount and duration
- **Eligibility**: PI requirements, institutional requirements

### Phase 1.5: Scientific Question Refinement

A proposal's quality is determined by the precision of its scientific question.

**The Refinement Funnel**:

| Level | Example | Quality |
|:-----:|---------|:-------:|
| Interest | "I'm interested in LLM reasoning" | ✗ Vague |
| Topic | "LLM mathematical reasoning" | ✗ Broad |
| Question | "Why do LLMs fail at multi-step arithmetic?" | ○ Closer |
| Hypothesis | "LLMs fail because Transformers approximate via pattern matching rather than symbolic ops" | ✓ Testable |
| Prediction | "Embedding a differentiable symbolic module will improve accuracy by >20%" | ✓ Measurable |

**"So What?" Cascade** — apply 3 levels to find significance:
1. "Why do LLMs fail at arithmetic?" → So what?
2. "They can't be trusted for numerical tasks in finance/medicine" → So what?
3. "This limits deployment in safety-critical applications affecting millions" → **THIS is your significance**

**Quality checklist**: Specific enough to answer in funding period? Broad enough to interest the community? Challenges existing understanding? Decomposable into 2-4 testable sub-questions (= Aims)?

### Phase 2: Proposal Structure by Funder

#### NSF (US National Science Foundation)

```markdown
# NSF Proposal Structure (15-page Project Description limit)

## 1. Project Summary (1 page, separate)
- **Overview**: [What, why, how — 1 paragraph]
- **Intellectual Merit**: [Scientific contribution — 1 paragraph]
- **Broader Impacts**: [Societal benefit — 1 paragraph]

## 2. Project Description (max 15 pages)
### 2.1 Introduction and Motivation
### 2.2 Related Work and Background
### 2.3 Proposed Research
#### 2.3.1 Thrust 1: [Title]
#### 2.3.2 Thrust 2: [Title]
#### 2.3.3 Thrust 3: [Title]
### 2.4 Evaluation Plan
### 2.5 Broader Impacts
### 2.6 Timeline and Milestones
### 2.7 Results from Prior NSF Support (if applicable)

## 3. References Cited (no page limit, separate)
## 4. Budget and Budget Justification
## 5. Biographical Sketches
## 6. Data Management Plan (2 pages)
## 7. Facilities and Equipment
```

#### NSFC (国家自然科学基金 / China)

```markdown
# 国家自然科学基金申请书结构

## 一、基本信息（系统填写）

## 二、项目正文
### （一）立项依据与研究内容
#### 1. 项目的立项依据
- 研究意义（学术价值和应用前景）
- 国内外研究现状及发展动态分析
- 参考文献

#### 2. 项目的研究内容、研究目标及拟解决的关键科学问题
- 研究内容（3-4 个研究内容）
- 研究目标（1-2 段）
- 拟解决的关键科学问题（2-3 个）

#### 3. 拟采取的研究方案及可行性分析
- 研究方案（技术路线图）
- 可行性分析
- 项目的特色与创新之处

#### 4. 年度研究计划及预期研究结果

### （二）研究基础与工作条件
#### 1. 研究基础（与本项目相关的研究工作积累和已取得的研究成果）
#### 2. 工作条件（实验条件、数据资源等）
#### 3. 正在承担的与本项目相关的科研项目
#### 4. 完成国家自然科学基金项目情况

## 三、预算说明
```

#### NIH (US National Institutes of Health)

```markdown
# NIH R01 Proposal Structure

## Specific Aims (1 page — the most critical page)
- **Opening paragraph**: Establish the problem and its significance
- **Knowledge gap**: What is unknown
- **Long-term goal / Overall objective**: What this project will achieve
- **Central hypothesis**: The testable hypothesis
- **Rationale**: Why this approach will work
- **Specific Aim 1**: [Title] — hypothesis and approach
- **Specific Aim 2**: [Title] — hypothesis and approach
- **Specific Aim 3**: [Title] — hypothesis and approach
- **Impact statement**: How success will advance the field

## Research Strategy (12 pages)
### A. Significance
### B. Innovation
### C. Approach
#### C.1 Preliminary Studies
#### C.2 Research Design for Aim 1
#### C.3 Research Design for Aim 2
#### C.4 Research Design for Aim 3
#### C.5 Timeline
#### C.6 Potential Problems and Alternative Approaches
```

#### ERC (European Research Council)

```markdown
# ERC Proposal Structure

## Part B1 (max 10 pages)
### Section a: Extended Synopsis
- State of the art and objectives
- Methodology
- Expected results and impact

## Part B2 (max 15 pages)
### Section b: Scientific Proposal
- Detailed research plan
- Work packages with deliverables
- Risk assessment and contingency
- Timeline (Gantt chart)
```

### Phase 2.5: Aim Architecture — Logical Interconnection

Aims are NOT a list — they form a logical structure:

| Architecture | Structure | When | Risk |
|:------------:|-----------|------|------|
| **Sequential** | Aim 1 → 2 → 3 (each builds on previous) | Developmental | If Aim 1 fails, all fail |
| **Convergent** | Aim 1 + 2 → Aim 3 (independent aims integrate) | Multidisciplinary | Must produce compatible outputs |
| **Parallel** | Aim 1 ∥ 2 ∥ 3 (independent facets) | Exploratory | May appear disconnected |

**"Remove One Aim" Test**: If removing ANY aim collapses the proposal → too sequential (risky). If removing ALL individual aims still works → too independent (no synergy). Ideal: removing one weakens but doesn't destroy.

Add explicit relationship sentences: "Aim 2 builds on the [output] from Aim 1 by..." or "While Aim 1 addresses [A], Aim 2 tackles complementary [B]; Aim 3 integrates both."

### Phase 2.5.5: NSFC Category-Specific Strategies

| 类型 | 经费 | 核心标准 | 策略 |
|-----|:----:|---------|------|
| **青年基金** | 30万/3年 | 申请人潜力+选题新颖 | 突出独立思考，选题"小而精" |
| **面上项目** | 50-60万/4年 | 科学问题深度+研究基础 | 研究基础扎实（论文支撑），科学问题凝练 |
| **重点项目** | 300万/5年 | 学术引领性+团队实力 | 展示领域影响力，强调团队互补性 |

**NSFC 写作规范**: "关键科学问题"不是研究内容重复，而是上升到科学层面的抽象（"做什么"→"回答什么科学问题"）。"特色与创新"区分"学术思路创新"和"技术方法创新"。"研究基础"只列与本项目直接相关的 5-10 篇代表作。避免"首次""国际领先"等过度宣称。

**关键科学问题凝练**: 从具体内容抽象出底层规律："开发新注意力机制"→"线性复杂度近似在什么条件下保持二次复杂度的表达能力？"

### Phase 3: Content Drafting

#### Step 3.0.5: Significance Triangle

Build an irresistible funding case using three vertices:

**Vertex 1 — Problem Severity**: Use concrete data — "X causes Y deaths/year", "Z costs $B annually". NOT "This is an important problem."

**Vertex 2 — Solution Inadequacy**: Name specific limitations — "[Method A] requires [unrealistic assumption]. [Method B] achieves only [insufficient %]." NOT "Existing methods are limited."

**Vertex 3 — Your Feasibility**: "Our preliminary results [Fig. 1] demonstrate [evidence] that [approach] is feasible, achieving [metric] on [pilot experiment]."

All three must be strong: Problem not urgent → "Who cares?" Solutions adequate → "Already solved." You can't do it → "Too risky."

**Elevator Pitch sentence**: "[Problem with data] remains unsolved because [specific inadequacy]. We propose [approach] based on [insight], supported by preliminary evidence that [result]."

#### Step 3.1: Specific Aims / Research Objectives

The Specific Aims page (or equivalent) is the most critical component. Follow this structure:

**Opening Hook** (2-3 sentences):
State the broad problem and its importance with a compelling statistic or fact.

**Knowledge Gap** (2-3 sentences):
What is currently unknown or inadequate. Use "However, ..." to pivot from known to unknown.

**Long-term Goal and Objective** (2 sentences):
"The long-term goal of this research is to... The objective of this proposal is to..."

**Central Hypothesis** (1-2 sentences):
"Our central hypothesis is that... This hypothesis is supported by..."

**Specific Aims** (1 paragraph each):
- **Aim 1**: [Action verb] [topic]. *Hypothesis*: ... *Approach*: ...
- **Aim 2**: [Action verb] [topic]. *Hypothesis*: ... *Approach*: ...
- **Aim 3**: [Action verb] [topic]. *Hypothesis*: ... *Approach*: ...

**Payoff/Impact** (2-3 sentences):
"The expected outcome is... This contribution is significant because..."

#### Step 3.2: Significance and Innovation

**Significance Writing Strategy**:
1. Establish the importance of the problem (societal/scientific impact)
2. Describe current barriers to progress
3. Explain how your project will remove these barriers
4. Articulate the expected impact if successful

**Innovation Writing Strategy**:
1. State what is conceptually new (new framework, theory, model)
2. State what is technically new (new method, algorithm, tool)
3. State what is practically new (new application, domain, scale)
4. Differentiate clearly from closest prior work

#### Step 3.3: Research Plan / Approach

For each aim/research content:
1. **Rationale**: Why this specific approach
2. **Preliminary data**: What you've already done (if any)
3. **Methodology**: Detailed technical plan
4. **Expected outcomes**: What success looks like
5. **Potential pitfalls**: What could go wrong
6. **Alternative approaches**: Backup plans
7. **Timeline**: Milestone-based schedule

Generate a Gantt chart or timeline table:

```markdown
| Task | Y1-Q1 | Y1-Q2 | Y1-Q3 | Y1-Q4 | Y2-Q1 | Y2-Q2 | Y2-Q3 | Y2-Q4 |
|------|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
| Aim 1: Data collection | ████ | ████ | | | | | | |
| Aim 1: Analysis | | ████ | ████ | | | | | |
| Aim 2: Development | | | ████ | ████ | ████ | | | |
| Aim 2: Evaluation | | | | | ████ | ████ | | |
| Aim 3: Integration | | | | | | ████ | ████ | |
| Paper writing | | | | ████ | | | ████ | ████ |
```

#### Step 3.3.5: Four-Dimensional Feasibility

| Dimension | What to Show | Evidence |
|-----------|-------------|---------|
| **Technical** | The method can work | Preliminary results, pilot study, proof-of-concept |
| **Team** | The people can execute | Past publications in this area, complementary skills |
| **Resources** | The environment supports it | Equipment, datasets, computing, collaborators |
| **Timeline** | It can be done in time | Realistic milestones, contingency time |

**"Why Us?" paragraph**: "We are uniquely positioned because: (1) PI has [N] years in [area], (2) our lab developed [tool] providing a foundation, (3) we have collaborations with [partners] providing access to [unique resource]."

#### Step 3.3.7: Risk-Mitigation Matrix

For each Aim:

| Risk | Likelihood | Impact | Mitigation |
|------|:---------:|:------:|-----------|
| [Insufficient data] | Medium | High | Pre-recruit; synthetic data backup |
| [Model won't converge] | Low | High | Validate on subset first; simpler fallback |

**"What If It Fails?"**: "Even if [worst case], the project yields [valuable intermediate result]. Moreover, [alternative approach] achieves [partial objective]." Reviewers RESPECT risk acknowledgment — "no risks" = immediately distrusted.

#### Step 3.4.5: Research Framework Diagram

Beyond Gantt charts, design a **technical roadmap figure** showing logical relationships:
- Left-to-right or top-to-bottom flow
- Color-code by Aim (Aim 1 = blue, Aim 2 = green, Aim 3 = orange)
- Show data/output flows between Aims with arrows
- Mark Go/No-Go decision points
- For NSFC: this "技术路线图" is EXPECTED — generate via Mermaid or describe for user

#### Step 3.5.5: Success Metrics & Milestones

Every Aim needs MEASURABLE success criteria:
1. **Primary metric**: Main outcome measure
2. **Threshold**: What constitutes success (">90% accuracy")
3. **Baseline**: Current best to beat
4. **Timeline milestone**: When evaluated
5. **Go/No-Go**: What happens if threshold isn't met

Example: "Aim 1 succeeds if model achieves ≥90% on [benchmark] (current SOTA: 82.3%). Evaluated at Month 12. If 85-90% → proceed with modifications; if <85% → pivot to Alternative B."

### Phase 4: Budget Justification

#### Common Budget Categories

| Category | Description | Justification Pattern |
|----------|-------------|----------------------|
| **Personnel** | PI salary, postdocs, students | Role, % effort, duration |
| **Equipment** | >$5000 items | Necessity, no existing access |
| **Travel** | Conferences, fieldwork | Specific conferences, dissemination |
| **Supplies** | Materials, software | Specific needs with cost estimates |
| **Other** | Publication fees, participant compensation | Itemized with justification |

### Phase 5: Quality Review

#### Grant Review Simulation

When the user asks to review their proposal, evaluate against typical review criteria:

```markdown
## Grant Proposal Review

### Significance: [Score 1-5]
- Is the problem important?
- Will the results advance the field?

### Innovation: [Score 1-5]
- Is the approach novel?
- Does it challenge existing paradigms?

### Approach: [Score 1-5]
- Is the methodology sound?
- Are potential problems addressed?
- Is the timeline realistic?

### Investigator: [Score 1-5]
- Does the team have relevant expertise?
- Are preliminary results convincing?

### Environment: [Score 1-5]
- Are resources adequate?
- Is institutional support evident?

### Overall Assessment: [Score 1-5]
### Strengths: [List]
### Weaknesses: [List]
### Suggestions for Improvement: [List]
```

### Phase 5.5: Reviewer Question Anticipation

Top proposals preemptively answer the 10 questions every reviewer asks:

| # | Question | Where | How |
|---|---------|-------|-----|
| 1 | "Is this important?" | Opening | Hard data on problem severity |
| 2 | "Done before?" | Innovation | Comparison table with closest work |
| 3 | "Will it work?" | Preliminary data | Pilot results, even small-scale |
| 4 | "What if Aim 1 fails?" | Approach | Risk-mitigation for each Aim |
| 5 | "Can this team do it?" | Investigator | Track record on THIS topic |
| 6 | "Realistic timeline?" | Timeline | Each milestone → specific deliverable |
| 7 | "Budget justified?" | Budget | Every line item → specific Aim |
| 8 | "Value if partial failure?" | Impact | Intermediate outputs + negative result value |
| 9 | "How measured?" | Approach | Metrics + thresholds per Aim |
| 10 | "Broader impact?" | Significance | Beyond academia: industry, policy, education |

**Self-review**: Before submission, score your own proposal on each (1-5). Any < 3 needs revision.

## Integration with Other Skills

- **literature-review**: Identify research gaps to justify significance
- **deep-research**: Gather funding body priorities and success stories
- **academic-writing**: Share writing conventions (hedging, formality, citation style)
- **chart-visualization**: Create timeline Gantt charts and framework diagrams
- **statistical-analysis**: Power analysis for sample size justification

**Academic API Tools (use directly when available):**
- `semantic_scholar_search(query="...", year_range="2020-2026")` — Find supporting literature for Significance and Innovation sections
- `crossref_lookup(doi="...")` — Validate and retrieve metadata for preliminary data citations
- `arxiv_search(query="...", category="...")` — Find latest preprints to demonstrate awareness of cutting-edge work

## Output Files

All outputs saved to `/mnt/user-data/outputs/`:
- `proposal.md` — Full proposal in Markdown
- `proposal.tex` — LaTeX version (if requested)
- `budget_justification.md` — Itemized budget narrative
- `specific_aims.md` — Standalone aims page

Use `present_files` to share outputs with the user.

## Notes

- Always check the most current CFP — requirements change frequently
- Use `web_search` to verify deadlines, page limits, and format requirements
- Tailor language to the funding body's review culture
- For NSFC: write in Chinese, follow the official template structure exactly
- For NSF: emphasize both Intellectual Merit AND Broader Impacts
- For NIH: the Specific Aims page determines whether reviewers read further
- Never exceed page or word limits — proposals are rejected for non-compliance
