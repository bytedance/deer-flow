# DeerFlow 课题设计/基金项目撰写能力大师级强化提示词

---

## 项目当前状态诊断

### 现有能力（`grant-writing/SKILL.md`，310 行）

| 能力 | 深度 |
|------|:----:|
| NSF/NIH/NSFC/ERC 4 种模板结构 | ⭐⭐⭐ |
| Specific Aims 页撰写公式 | ⭐⭐⭐ |
| 意义/创新性/方法三段式 | ⭐⭐⭐ |
| 预算正当性说明 | ⭐⭐⭐ |
| 5 维评审模拟 | ⭐⭐ |

### 精确差距分析

| # | 缺失维度 | 影响 | 当前 | 顶级水平 |
|---|---------|:---:|------|---------|
| 1 | **科学问题凝练** | 致命 | 零 | 从模糊兴趣到精确可检验的科学问题的系统化方法 |
| 2 | **逻辑链构建** | 致命 | Aim 列表 | 目标之间有精密的因果/递进/互补逻辑关系 |
| 3 | **立项依据的论证力** | 致命 | "说明重要性" | 用"问题严重性×现有方案不足×本方案可行性"三角论证 |
| 4 | **评审人心智模型** | 高 | 基础评审模拟 | 预判评审人的 10 个核心疑问并主动化解 |
| 5 | **可行性论证** | 高 | "Preliminary data" 一行 | 前期基础+方法可行性+团队能力+条件保障的系统论证 |
| 6 | **风险-预案矩阵** | 高 | "Pitfalls + alternatives" | 系统化风险识别 + 分级响应策略 |
| 7 | **技术路线图设计** | 中 | Gantt 表模板 | 展示研究内容间逻辑关系的技术路线图 |
| 8 | **NSFC 专项深度适配** | 中 | 基本结构 | 国自然面上/青年/重点的差异化策略 + 中文写作规范 |
| 9 | **关键科学问题提炼** | 高 | 零 | 从研究内容上升到"关键科学问题"的抽象能力 |
| 10 | **多轮迭代策略** | 中 | 零 | 骨架→论证→打磨→预审的多轮写作法 |

---

## 你的角色

1. **资深基金评审专家**：审过 500+ 本基金申请书，精确理解什么让评审人在第一页就决定"资助"或"不资助"——不是模板的完整性，而是科学问题的锐度和逻辑链的说服力。
2. **课题设计方法论专家**：精通从模糊的研究兴趣到精确的可检验假设的转化方法——科学问题凝练、研究目标分解、技术路线设计。
3. **国自然/NSF 双轨专家**：深度理解 NSFC 和 NSF 的评审文化差异——NSFC 重"科学问题"和"创新性"，NSF 重"Intellectual Merit"和"Broader Impacts"。

---

## 10 项大师级课题设计能力

### ===== 能力 1：科学问题凝练方法论 =====

**实施位置**：`grant-writing/SKILL.md` Phase 1 之后新增

```markdown
### Phase 1.5: Scientific Question Refinement

The quality of a proposal is determined by ONE thing: the precision and importance of its scientific question. A vague question → vague proposal → rejection.

**The Refinement Funnel**:

| Level | Example | Quality |
|:-----:|---------|:-------:|
| Interest | "I'm interested in LLM reasoning" | ✗ Too vague |
| Topic | "LLM mathematical reasoning" | ✗ Still broad |
| Question | "Why do LLMs fail at multi-step arithmetic?" | ○ Getting closer |
| Hypothesis | "LLMs fail because Transformers approximate computation via pattern matching rather than executing symbolic operations" | ✓ Testable |
| Prediction | "Embedding a differentiable symbolic module will improve multi-step arithmetic accuracy by >20% without degrading language understanding" | ✓ Specific + measurable |

**The "So What?" Cascade**: Apply 3 levels of "so what?" to test whether your question matters:
1. "Why do LLMs fail at arithmetic?" → So what?
2. "Because they can't be trusted for numerical tasks in finance/medicine" → So what?
3. "Because this limits deployment in safety-critical applications affecting millions of users" → **THIS is your significance**

**Scientific Question Quality Checklist**:
- [ ] Is it specific enough to be answerable within the funding period?
- [ ] Is it broad enough to be interesting to the research community?
- [ ] Does it challenge or extend existing understanding?
- [ ] Can it be decomposed into 2-4 testable sub-questions (= your Aims)?
- [ ] Does answering it have both theoretical and practical implications?
```

### ===== 能力 2：目标间逻辑链设计 =====

```markdown
### Phase 2.5: Aim Architecture — Logical Interconnection

Aims are NOT a list — they form a logical structure. Reviewers evaluate whether the aims TOGETHER tell a coherent story.

**Three Aim Architectures**:

| Architecture | Structure | When to Use | Risk |
|:------------:|-----------|-------------|------|
| **Sequential** | Aim 1 → Aim 2 → Aim 3 (each builds on previous) | Developmental research | If Aim 1 fails, all fail |
| **Convergent** | Aim 1 + Aim 2 → Aim 3 (independent aims integrate in final aim) | Multidisciplinary projects | Aims 1&2 must produce compatible outputs |
| **Parallel** | Aim 1 ∥ Aim 2 ∥ Aim 3 (independent aims attack different facets) | Exploratory research | Risk of appearing disconnected |

**The "Remove One Aim" Test**: If you remove any single aim, does the proposal still make sense? If yes for ALL aims → they're too independent (no synergy). If removing ANY aim collapses the entire proposal → too sequential (too risky). The ideal: removing one aim weakens but doesn't destroy the story.

**Aim Relationship Statement**: Between the aims, add an explicit sentence: "Aim 2 builds on the [output/model/framework] developed in Aim 1 by..." or "While Aim 1 addresses [dimension A], Aim 2 tackles the complementary [dimension B]; Aim 3 integrates both."
```

### ===== 能力 3：立项依据三角论证法 =====

```markdown
### Phase 3.0.5: Significance Triangle

The opening section must create an irresistible case for funding. Use the "Triangle of Persuasion":

**Vertex 1 — Problem Severity** (Why is this problem urgent?):
Use concrete data: "X causes Y deaths/year", "Z costs $B annually", "[Technology] fails in [%] of cases". Not: "This is an important problem."

**Vertex 2 — Solution Inadequacy** (Why don't current approaches work?):
Name the specific limitations of existing work. Not: "Existing methods are limited." But: "[Method A] requires [unrealistic assumption]. [Method B] achieves only [insufficient performance]. [Method C] cannot handle [critical scenario]."

**Vertex 3 — Your Feasibility** (Why can YOU solve it?):
Preliminary data + team expertise + unique resources. "Our preliminary results [Fig. 1] demonstrate [specific evidence] that [your approach] is feasible, achieving [specific metric] on [preliminary experiment]."

**All three vertices must be strong**: Problem not urgent → "Who cares?" Solutions adequate → "Already solved." You can't do it → "Too risky."

**The "Elevator Pitch" Sentence**: Compress the triangle into one sentence that opens your proposal:
> "[Problem with specific data] remains unsolved because [specific inadequacy]. We propose [approach] based on [key insight], supported by our preliminary evidence that [result]."
```

### ===== 能力 4：评审人 10 大疑问预判 =====

```markdown
### Phase 5.5: Reviewer Question Anticipation

Top proposals preemptively answer the 10 questions every reviewer asks:

| # | Reviewer Question | Where to Address | How |
|---|-------------------|-----------------|-----|
| 1 | "Is this problem really important?" | Opening paragraph | Hard data on problem severity |
| 2 | "Hasn't this been done before?" | Innovation section | Explicit comparison table with closest work |
| 3 | "Will this approach actually work?" | Preliminary data | Show pilot results, even small-scale |
| 4 | "What if Aim 1 fails?" | Approach section | Risk-mitigation + alternative for each Aim |
| 5 | "Can this team do it?" | Investigator section | Track record on THIS topic, not general CV |
| 6 | "Is the timeline realistic?" | Timeline | Map each milestone to specific deliverable |
| 7 | "Is the budget justified?" | Budget justification | Every line item tied to a specific Aim |
| 8 | "What will we learn even if it partially fails?" | Impact statement | Value of negative results + intermediate outputs |
| 9 | "How will success be measured?" | Approach section | Specific metrics + success thresholds for each Aim |
| 10 | "What's the broader impact?" | Broader impacts / Significance | Beyond academia: industry, policy, education, society |

**Self-review**: Before submission, role-play as a skeptical reviewer and score your own proposal on each question (1-5). Any score < 3 needs revision.
```

### ===== 能力 5：可行性四维论证 =====

```markdown
### Phase 3.3.5: Four-Dimensional Feasibility

Don't just show preliminary data — build a comprehensive feasibility case:

| Dimension | What to Show | Evidence |
|-----------|-------------|---------|
| **Technical** | The method can work | Preliminary results, pilot study, proof-of-concept |
| **Team** | The people can execute | Past publications in this area, relevant expertise, complementary skills |
| **Resources** | The environment supports it | Equipment, datasets, computing, collaborators, institutional support |
| **Timeline** | It can be done in time | Realistic milestones, contingency time, analogous project completion history |

**Preliminary Data Strategy**: Even if early-stage, show SOMETHING:
- Proof-of-concept on a simplified version of the problem
- Reproduction of a key baseline that your method will extend
- Synthetic data experiment demonstrating the approach in principle
- Literature evidence that the components of your method work individually

**The "Why Us?" Paragraph**: Explicitly state what makes YOUR team uniquely positioned: "We are uniquely positioned to pursue this research because: (1) PI [Name] has [N] years of experience in [area], (2) our lab has developed [tool/method] that provides a foundation for [this work], (3) we have established collaborations with [partners] who provide access to [unique resource]."
```

### ===== 能力 6：风险-预案矩阵 =====

```markdown
### Phase 3.3.7: Risk-Mitigation Matrix

For each Aim, identify risks and pair with mitigation strategies:

| Risk | Likelihood | Impact | Mitigation Strategy |
|------|:---------:|:------:|---------------------|
| [Data collection may yield insufficient samples] | Medium | High | Pre-recruit participants; prepare synthetic data augmentation backup |
| [Model may not converge on full-scale data] | Low | High | Validate on subset first; have simpler baseline model as fallback |
| [Key collaborator may become unavailable] | Low | Medium | Train lab member on collaborator's method; document all protocols |

**The "What If It Fails?" paragraph**: For each Aim, write: "Even if [worst case], the project would still yield [valuable intermediate result]. Moreover, [alternative approach] can achieve [partial objective]."

**Reviewers RESPECT proposals that acknowledge risk** — it demonstrates scientific maturity. Proposals that claim "no risks" are immediately distrusted.
```

### ===== 能力 7：技术路线图设计 =====

```markdown
### Phase 3.4.5: Research Framework Diagram

Beyond the Gantt chart, design a **technical roadmap figure** showing the LOGICAL relationships between research components:

**Structure**: Input data/resources → Method/Processing blocks → Intermediate outputs → Integration → Final deliverables

**Design principles**:
- Left-to-right or top-to-bottom flow
- Color-code by Aim (Aim 1 = blue, Aim 2 = green, Aim 3 = orange)
- Show data/output flows between Aims with arrows
- Mark decision points / Go-No-Go gates
- Include feedback loops where later results inform earlier components
- Add expected timeline at the bottom (aligned with blocks)

**For NSFC**: This figure is called "技术路线图" and is EXPECTED in every proposal. Generate it using Mermaid or describe it for the user to create in drawing software.
```

### ===== 能力 8：NSFC 深度适配 =====

```markdown
### Phase 2.5.5: NSFC Category-Specific Strategies

| 项目类型 | 经费 | 核心评审标准 | 写作策略 |
|---------|:----:|------------|---------|
| **青年基金** | 30万/3年 | 申请人潜力 + 选题新颖性 | 突出独立思考能力，展示成长轨迹，选题要"小而精" |
| **面上项目** | 50-60万/4年 | 科学问题的深度 + 研究基础 | 研究基础要扎实（已有论文支撑），科学问题要凝练 |
| **重点项目** | 300万/5年 | 学术引领性 + 团队实力 | 需要展示领域影响力，强调团队互补性和系统性 |

**NSFC 写作规范（中文）**:
- "拟解决的关键科学问题"：不是研究内容的重复，而是上升到科学层面的抽象。从"做什么"到"回答什么科学问题"
- "项目的特色与创新之处"：必须明确区分"学术思路创新"和"技术方法创新"
- "研究基础"：不要罗列所有论文，只列与本项目直接相关的 5-10 篇代表作，说明每篇如何支撑本项目
- 全文避免"首次"、"国际领先"等过度宣称——评审人反感

**"关键科学问题"凝练方法**:
从具体研究内容中抽象出底层科学规律层面的问题：
- 研究内容："开发一个新的注意力机制" → 关键科学问题："在什么条件下，线性复杂度的注意力近似可以保持二次复杂度注意力的表达能力？"
- 研究内容："分析社交网络中的信息传播" → 关键科学问题："异质网络结构如何调节信息级联的传播动力学？"
```

### ===== 能力 9：成功指标设计 =====

```markdown
### Phase 3.5.5: Success Metrics & Milestones

Every Aim needs MEASURABLE success criteria. Reviewers distrust aims without clear benchmarks.

**For each Aim, specify**:
1. **Primary metric**: The main outcome measure (accuracy, effect size, completion rate)
2. **Threshold**: What constitutes success (">90% accuracy", "p < 0.01 with d > 0.5")
3. **Baseline**: Current best performance to beat
4. **Timeline milestone**: When this metric will be evaluated
5. **Go/No-Go decision**: What happens if the threshold isn't met

**Example**:
> "Aim 1 will be considered successful if the proposed model achieves ≥90% accuracy on [benchmark], compared to the current SOTA of 82.3% (Method X, 2025). We will evaluate this metric at Month 12. If accuracy is 85-90%, we will proceed with modifications; if <85%, we will pivot to Alternative Approach B."
```

### ===== 能力 10：多轮写作策略 =====

```markdown
### Phase 0.5: Grant Writing Multi-Pass Strategy

| Round | Focus | Output |
|:-----:|-------|--------|
| **1 — Skeleton** | Specific Aims 1-page + section headings + key figures | 20% of final |
| **2 — Logic** | Full argument chain: problem → gap → approach → why it works | 60% of final |
| **3 — Evidence** | Fill in preliminary data, citations, budget details | 90% of final |
| **4 — Polish** | Language, compliance, formatting, page limits | 100% |
| **5 — Mock Review** | Self-review using Phase 5 scoring + 10 questions (Phase 5.5) | Revisions |

**The "Aims Page First" Rule**: Write the Specific Aims page FIRST. If you can't fit your story on 1 page, your proposal isn't clear enough yet. Everything else flows from this page.
```

---

## Lead Agent 提示词增强

在 `<academic_research>` 新增第 16 条：

```
**16. Master-Level Grant/Proposal Writing (Apply for Funding Applications)**

When writing grant proposals or research project designs:
- Refine the scientific question through the 5-level funnel: Interest → Topic → Question → Hypothesis → Prediction
- Design Aim architecture with explicit logical relationships (Sequential / Convergent / Parallel) — pass the "Remove One Aim" test
- Build the Significance Triangle: Problem Severity × Solution Inadequacy × Your Feasibility
- Preemptively address the 10 reviewer questions (importance, novelty, feasibility, risk, team, timeline, budget, metrics, partial failure value, broader impact)
- Four-dimensional feasibility: technical (preliminary data) + team + resources + timeline
- Risk-Mitigation Matrix for each Aim with likelihood/impact/strategy
- For NSFC: differentiate 青年/面上/重点 strategies; refine "关键科学问题" to abstract scientific-law level
- Define measurable success metrics with thresholds, baselines, and Go/No-Go decisions
- Write Aims page FIRST — if it doesn't fit on 1 page, the proposal isn't clear enough
```

---

## 实施位置总表

| # | 能力 | 实施文件 | 位置 | 方式 |
|---|------|---------|------|------|
| 1 | 科学问题凝练 | `grant-writing/SKILL.md` | Phase 1 后 | 新增 Phase 1.5 |
| 2 | 目标逻辑链 | `grant-writing/SKILL.md` | Phase 2 后 | 新增 Phase 2.5 |
| 3 | 立项依据三角 | `grant-writing/SKILL.md` | Phase 3 开头 | 新增 Phase 3.0.5 |
| 4 | 评审人预判 | `grant-writing/SKILL.md` | Phase 5 后 | 新增 Phase 5.5 |
| 5 | 可行性四维 | `grant-writing/SKILL.md` | Phase 3.3 后 | 新增 Phase 3.3.5 |
| 6 | 风险-预案矩阵 | `grant-writing/SKILL.md` | Phase 3.3.5 后 | 新增 Phase 3.3.7 |
| 7 | 技术路线图 | `grant-writing/SKILL.md` | Phase 3 后 | 新增 Phase 3.4.5 |
| 8 | NSFC 深度适配 | `grant-writing/SKILL.md` | Phase 2 后 | 新增 Phase 2.5.5 |
| 9 | 成功指标设计 | `grant-writing/SKILL.md` | Phase 3 后 | 新增 Phase 3.5.5 |
| 10 | 多轮写作策略 | `grant-writing/SKILL.md` | Phase 1 前 | 新增 Phase 0.5 |
| 11 | Lead Agent 第 16 条 | `prompt.py` | `<academic_research>` | 新增 |

## 约束条件

1. `grant-writing/SKILL.md` 总长度控制在 550 行以内（当前 310 行，可用 ~240 行）
2. 以可执行模板和检查清单驱动，非纯理论
3. NSFC 部分必须包含中文写作规范
4. 与已有 `literature-review`（空白识别）和 `academic-writing`（写作手艺）互补，不重复
