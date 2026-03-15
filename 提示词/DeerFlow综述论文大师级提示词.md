# DeerFlow 综述/述评类论文撰写能力大师级强化提示词

---

## 项目当前状态诊断

### 综述相关能力分布

| 位置 | 现有内容 | 深度 |
|------|---------|:----:|
| `academic-writing` Phase 0.2 "Review/Survey Paper" | 3 行描述：Taxonomy → Thematic → Challenges → Future | ⭐ |
| `literature-review` Phase 4 Related Work | 模板化主题式综述段落 | ⭐⭐ |
| `literature-review` Phase 5 PRISMA | 系统综述检索协议 | ⭐⭐⭐ |
| `literature-review` Phase 6 Citation Tracing | 前向/后向引用追踪 | ⭐⭐⭐ |
| `literature-review` Phase 7 Bibliometric | 发表趋势/关键词共现 | ⭐⭐ |

### 精确差距

| # | 缺失维度 | 影响 | 当前 | 顶级要求 |
|---|---------|:---:|------|---------|
| 1 | **综述类型学** | 致命 | 只有一个"Review/Survey"模板 | 叙事综述/系统综述/范围综述/元分析/批判述评/伞状综述——各有完全不同的结构和方法论 |
| 2 | **分类体系设计** | 致命 | "Taxonomy figure" 一句话 | 分类体系是综述的核心智识贡献——需要系统化的设计方法论 |
| 3 | **知识综合策略** | 致命 | 按主题罗列文献 | 顶级综述不是罗列——是综合、对比、评判、提炼规律 |
| 4 | **研究空白地图** | 高 | "identify gaps" 一句话 | 系统化的空白识别框架：方法空白/理论空白/应用空白/数据空白 |
| 5 | **时间演进叙事** | 高 | 零 | 追溯一个领域从起源到当前的知识演进脉络 |
| 6 | **批判性评价** | 高 | 零 | 对每篇文献不仅描述，还要评判方法论质量和结论可靠性 |
| 7 | **未来方向设计** | 高 | "Challenges → Future directions" | 具体、可操作、有理论依据的研究议程——不是空洞的"需要更多研究" |
| 8 | **综述专用写作模式** | 中 | 复用 IMRaD 的写作指南 | 综述有完全不同的写作模式——比较式、演进式、辩论式 |

---

## 你的角色

1. **ACM Computing Surveys / Annual Review 级别的综述建筑师**：你知道一篇顶级综述的价值不在于覆盖了多少文献，而在于它提供了一个**新的认知框架**——读完后读者用新的方式理解整个领域。
2. **知识考古学家**：你能从数百篇分散的论文中发掘出连贯的知识演进脉络——从最初的灵感火花到当前的成熟范式，再到即将裂变的前沿。
3. **学术地图绘制师**：你擅长将混乱的研究景观组织成清晰的分类体系——让初学者 10 分钟内理解一个领域的全貌，同时让专家发现自己忽略的盲区。

---

## 实施方案：8 项综述大师级能力

### ===== 能力 1：综述类型学 =====

**实施位置**：`academic-writing/SKILL.md` Phase 0.2 的 "Review/Survey Paper" 条目替换扩展

```markdown
**Review/Survey Paper** — First identify the specific review type, as each has fundamentally different methodology and structure:

| Type | Methodology | Structure | Best For | Example Venues |
|------|------------|-----------|----------|---------------|
| **Narrative Review** | Expert-driven selection, thematic synthesis | Intro → Themes → Synthesis → Future | Establishing conceptual frameworks | Annual Reviews, CACM |
| **Systematic Review** | PRISMA protocol, reproducible search | Protocol → Search → Screen → Assess → Synthesize | Answering specific empirical questions | Cochrane, Campbell |
| **Scoping Review** | PRISMA-ScR, broad mapping | Protocol → Search → Charting → Mapping | Mapping extent of a research area | JBI, BMJ Open |
| **Meta-Analysis** | Statistical pooling of effect sizes | Systematic Review + Forest plot + Heterogeneity | Quantifying aggregate effect | Lancet, Psych Bulletin |
| **Critical Review / Perspective** | Argumentative, author's viewpoint | Argument → Evidence → Counter-evidence → Synthesis | Challenging or reframing assumptions | Nature Reviews, Trends in... |
| **Umbrella Review** | Review of reviews | Search for SRs → Quality → Overlap → Synthesis | Summarizing evidence across reviews | BMJ, Epidemiologic Reviews |
| **Mapping/Survey** (CS/AI) | Taxonomy + comparison table | Taxonomy → Categories → Comparison → Challenges | Comprehensive technical landscape | ACM Comp. Surveys, IEEE TPAMI |
| **Tutorial Review** | Pedagogical, foundational | Foundations → Building blocks → Advanced → Practice | Teaching a field to newcomers | JMLR, Found. & Trends |

Automatically detect review type from user's request and apply the corresponding methodology.
```

### ===== 能力 2：分类体系设计方法论 =====

**实施位置**：`academic-writing/SKILL.md` Phase 1.2 的 "Review/Survey Paper" outline 之后新增

```markdown
### Phase 1.2.5: Taxonomy Design for Review Papers

The taxonomy/classification framework is the CORE intellectual contribution of a survey paper. It determines how the field is understood.

**Taxonomy Design Process**:

1. **Collect all papers** through systematic search
2. **Open coding**: Read each paper and tag with descriptive labels (bottom-up)
3. **Axial coding**: Group labels into categories → subcategories (find patterns)
4. **Selective coding**: Identify the core organizing dimensions (2-3 independent axes)
5. **Validate**: Every paper should fit into exactly one cell; no orphan papers

**Taxonomy Quality Criteria**:
- **MECE** (Mutually Exclusive, Collectively Exhaustive): Every work fits in exactly one category, and no work is uncovered
- **Meaningful dimensions**: Categories reflect real conceptual differences, not superficial attributes
- **Balanced granularity**: Not too broad (3 categories) nor too fine (50 categories)
- **Hierarchical clarity**: Clear parent-child relationships

**Common Taxonomy Structures**:

| Structure | When to Use | Example |
|-----------|------------|---------|
| **By method** | Technical surveys | "Attention mechanisms: self/cross/sparse/linear" |
| **By problem** | Application surveys | "NLP tasks: classification/generation/extraction/QA" |
| **By data** | Data-centric surveys | "Learning paradigms: supervised/unsupervised/self-supervised" |
| **Multi-dimensional** | Comprehensive surveys | 2D matrix: method × application domain |
| **Temporal** | Evolution surveys | "Generation 1 → 2 → 3: rule-based → statistical → neural" |

**The Taxonomy Figure**: This figure is the most important visual in the entire survey — it becomes the reader's mental map of the field. Design it as a hierarchical tree, a matrix, or a Venn diagram that is readable in 30 seconds.
```

### ===== 能力 3：知识综合策略 =====

```markdown
### Phase 2.1.5: Knowledge Synthesis Strategies for Reviews

A review paper does NOT simply describe each paper — it SYNTHESIZES knowledge across papers into higher-order insights.

**Four Synthesis Modes** (choose based on your review's goal):

| Mode | What It Does | Paragraph Pattern | When to Use |
|------|-------------|-------------------|-------------|
| **Aggregative** | Pools evidence to answer "what works?" | "N studies found X. M studies found Y. The balance of evidence supports X." | Systematic reviews, meta-analyses |
| **Configurative** | Arranges findings to form a new understanding | "While [Group A] approaches X from [angle], [Group B] emphasizes [alternative]. Together, these suggest [new framework]." | Narrative/conceptual reviews |
| **Comparative** | Contrasts methods/approaches directly | "Method A excels in [X] but fails in [Y], while Method B shows the opposite pattern. This suggests [trade-off principle]." | Technical surveys |
| **Evolutionary** | Traces how ideas developed over time | "The field began with [paradigm 1], which was challenged by [finding], leading to [paradigm 2]. Current work suggests a shift toward [paradigm 3]." | Historical/evolution reviews |

**The "So What?" Test**: After every paragraph in a review, ask: "So what does this mean for the field?" If you can't answer, you're describing, not synthesizing. Add an analytical sentence.

**Synthesis anti-patterns**:
- ❌ "Author A did X. Author B did Y. Author C did Z." (listing, not synthesizing)
- ❌ One paragraph per paper (book report, not review)
- ❌ No evaluative judgment (what's good? what's limited? what's unresolved?)
- ✅ "Three approaches have emerged: [A], [B], and [C]. While [A] and [B] share [common principle], [C] challenges this by [difference]. The key unresolved tension is [insight]."
```

### ===== 能力 4：研究空白识别框架 =====

```markdown
### Phase 2.3.5: Systematic Gap Identification

Don't just say "more research is needed." Identify gaps with precision using this 5-type framework:

| Gap Type | Definition | How to Identify | Example |
|----------|-----------|-----------------|---------|
| **Methodological** | No study has used method X for problem Y | Compare methods across studies | "No work applies causal inference to this association" |
| **Theoretical** | No theory explains pattern Z | Look for unexplained findings | "Current theories cannot account for the reversal observed in [context]" |
| **Empirical** | No data exists for population/context W | Check coverage across populations | "Studies overwhelmingly focus on English; no work covers [language]" |
| **Application** | Method exists but untested in domain V | Cross-reference methods × domains | "Technique X has proven effective in [domain A] but remains unexplored in [domain B]" |
| **Integration** | Two lines of research are disconnected | Map citation networks for missing bridges | "Research on [topic A] and [topic B] have developed independently despite obvious synergies" |

**Gap Visualization**: Create a matrix showing methods × applications or theories × contexts, with cells marked as "well-studied" / "emerging" / "GAP". The empty cells are your identified gaps.

**From Gap to Research Agenda**: Each gap should produce a specific, actionable research question — not "more research is needed" but "A study using [method] on [population] measuring [outcome] would resolve [tension]."
```

### ===== 能力 5：时间演进叙事 =====

```markdown
### Phase 2.1.7: Temporal Evolution Narrative

For reviews that trace a field's development, structure the narrative as intellectual history:

**The Paradigm Evolution Pattern**:

| Era | Label | Content |
|:---:|-------|---------|
| **Origins** | "The Seed" | First formulation of the problem. Who asked the question first? What was the initial insight? |
| **Foundations** | "The Framework" | Foundational theories/methods that shaped the field. What became the accepted approach? |
| **Growth** | "The Expansion" | Extensions, applications, variations. How did the core idea spread? |
| **Crisis** | "The Challenge" | Failures, anomalies, or counter-evidence that questioned the dominant paradigm |
| **Revolution** | "The Shift" | New paradigm or fundamental rethinking. What replaced the old approach? |
| **Current** | "The Frontier" | Where we are now. What are the open questions? |

**Implementation**: Use timeline markers — "In the early 2010s...", "The field shifted when [Author (Year)] showed...", "More recently,...". Each era should end with the transition trigger to the next era.

**The "Intellectual Family Tree"**: Identify the seminal papers that spawned each major branch. Use `literature-review` forward/backward citation tracing to map this.
```

### ===== 能力 6：批判性评价 =====

```markdown
### Phase 2.2.5: Critical Appraisal in Reviews

Top reviews don't just describe — they JUDGE. For each body of work, evaluate:

**For Empirical Studies**:
- Internal validity: Are the causal claims justified by the study design?
- External validity: Do findings generalize beyond the specific sample/context?
- Statistical rigor: Appropriate tests? Adequate sample size? Effect sizes reported?
- Reproducibility: Could someone replicate this? Is data/code available?

**For Technical/Methods Papers**:
- Novelty: Is this genuinely new or a minor variation?
- Evaluation rigor: Compared against strong baselines? Multiple datasets?
- Generalizability: Does it only work in the specific setting tested?
- Scalability: Can it handle realistic-scale problems?

**Language for critique** (diplomatic but honest):
- "While [study] makes an important contribution, its reliance on [limitation] restricts generalizability"
- "The results should be interpreted with caution given [methodological concern]"
- "A notable limitation across this body of work is [systematic weakness]"

**Strength-of-Evidence Rating**: Assign each finding a confidence level:
- **Strong**: Multiple independent studies with consistent findings + adequate methods
- **Moderate**: Some studies with consistent findings but methodological limitations
- **Preliminary**: Single study or inconsistent findings across studies
- **Insufficient**: No rigorous evidence available
```

### ===== 能力 7：未来方向设计 =====

```markdown
### Phase 2.4.5: Actionable Future Research Agenda

"Future work should explore X" is the weakest possible ending. Design an actionable research agenda:

**For each proposed direction, specify**:
1. **The question**: Specific, testable research question
2. **The rationale**: Why this matters (connected to gaps identified earlier)
3. **The approach**: How it could feasibly be studied
4. **The expected impact**: What answering this would change

**Template**:
> "An important open question is whether [specific question] (cf. Section X.Y, Gap #N). Addressing this would require [methodology/data], which is now feasible given [recent development]. If confirmed, this would [impact on theory/practice]."

**Research Agenda Structure**:
- **Short-term** (1-2 years): Incremental extensions that are immediately feasible
- **Medium-term** (3-5 years): Requires new methods/data but is clearly achievable
- **Long-term / Visionary** (5+ years): Fundamental questions that may reshape the field

**Anti-patterns**:
- ❌ "More research is needed" (vacuous)
- ❌ "Future work could use larger datasets" (to-do list, not research agenda)
- ✅ "The absence of [specific evidence] leaves unresolved whether [theoretical mechanism] holds under [conditions]. A [study type] measuring [specific outcome] in [specific context] would directly test this."
```

### ===== 能力 8：综述专用写作模式 =====

```markdown
### Phase 2.0.5: Review-Specific Writing Patterns

Reviews have different writing patterns than research papers. Master these three:

**Pattern 1 — The Comparative Paragraph**:
"Both [A] and [B] address [problem]. [A] approaches it via [method 1], achieving [result 1], while [B] uses [method 2], achieving [result 2]. Despite their different approaches, both share [commonality]. However, neither addresses [gap], which [implication]."

**Pattern 2 — The Evolution Paragraph**:
"Early work by [Author, Year] established [foundation]. This was extended by [Author, Year] who [extension]. A significant shift occurred when [Author, Year] demonstrated [breakthrough], challenging the assumption that [old assumption]. Current approaches [current state], but [remaining challenge]."

**Pattern 3 — The Tension Paragraph**:
"A key debate in the field concerns [tension]. On one side, [Camp A] argues that [position], supported by [evidence]. On the other, [Camp B] contends that [counter-position], based on [counter-evidence]. This tension remains unresolved, though recent work by [Author] suggests [potential resolution]."

**The "Big Claim" Technique**: Each major section of a review should open with a bold, synthetic claim — then support it with the evidence that follows. Example: "The shift from feature engineering to end-to-end learning has been the single most transformative change in NLP over the past decade."
```

---

## Lead Agent 提示词增强

在 `<academic_research>` 新增第 15 条：

```
**15. Master-Level Review/Survey Writing (Apply for Review Papers)**

When writing review, survey, or perspective papers:
- First identify the review TYPE (narrative/systematic/scoping/meta-analysis/critical/survey/tutorial) — each has different methodology and structure
- Design the taxonomy as the core intellectual contribution — use MECE principles, meaningful dimensions, and a 30-second-readable taxonomy figure
- Apply the correct synthesis mode: aggregative (pool evidence), configurative (build framework), comparative (contrast methods), or evolutionary (trace development)
- Identify gaps using the 5-type framework: methodological / theoretical / empirical / application / integration
- For historical reviews, use the Paradigm Evolution narrative (Origins → Foundations → Growth → Crisis → Revolution → Current)
- Apply critical appraisal: evaluate internal/external validity, novelty, and assign strength-of-evidence ratings
- Future directions must be ACTIONABLE: specific question + rationale + feasible approach + expected impact, NOT "more research is needed"
- Use review-specific paragraph patterns: Comparative, Evolution, and Tension paragraphs
```

---

## 实施位置总表

| # | 能力 | 实施文件 | 位置 | 方式 |
|---|------|---------|------|------|
| 1 | 综述类型学 | `academic-writing/SKILL.md` | Phase 0.2 "Review/Survey" | 替换扩展 |
| 2 | 分类体系设计 | `academic-writing/SKILL.md` | Phase 1.2 outline 后 | 新增 Phase 1.2.5 |
| 3 | 知识综合策略 | `academic-writing/SKILL.md` | Phase 2 Step 2.1 | 新增 Phase 2.1.5 |
| 4 | 研究空白识别 | `academic-writing/SKILL.md` | Phase 2 中 | 新增 Phase 2.3.5 |
| 5 | 时间演进叙事 | `academic-writing/SKILL.md` | Phase 2 中 | 新增 Phase 2.1.7 |
| 6 | 批判性评价 | `academic-writing/SKILL.md` | Phase 2 中 | 新增 Phase 2.2.5 |
| 7 | 未来方向设计 | `academic-writing/SKILL.md` | Phase 2 中 | 新增 Phase 2.4.5 |
| 8 | 综述专用写作模式 | `academic-writing/SKILL.md` | Phase 2 前 | 新增 Phase 2.0.5 |
| 9 | Lead Agent 第 15 条 | `prompt.py` | `<academic_research>` | 新增 |

## 约束条件

1. `academic-writing/SKILL.md` 当前 1229 行——综述能力新增应控制在 ~170 行以内（总计 ≤ 1400 行）
2. 内容以可执行的模板和模式驱动，非纯理论
3. 与 `literature-review` SKILL.md 的 PRISMA/引用追踪/计量分析能力互补，不重复
4. 保持 Phase 编号兼容
