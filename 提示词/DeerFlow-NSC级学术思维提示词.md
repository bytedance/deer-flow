# DeerFlow 第五轮强化：Nature/Science/Cell 级学术思维与写作提示词

---

## 诊断：当前水平 vs. Nature/Science/Cell 水平

经过四轮强化，DeerFlow 的 `academic-writing` 技能已达到 1085 行，涵盖了从研究范式检测、叙事架构、CARS 修辞模型、MEAL 段落工艺、Discussion 五层模型、审稿人心理学，到图表设计、多轮写作、证据编排、元话语系统等 12 项大师级手艺。

然而，这些能力本质上仍然是**写作技术**层面的——即"如何正确地写一篇论文"。Nature/Science/Cell 级别的论文之所以与众不同，不是因为写作技术更好，而是因为**思维方式**不同。

### 核心差距：思维层

| 维度 | 当前系统（优秀论文水平） | Nature/Science/Cell 水平 |
|------|---------------------|------------------------|
| **研究定位** | 解决一个具体问题 | 改变一个领域的思考方式 |
| **论证逻辑** | 线性论证（A→B→C→结论） | 多层次辩证推理（正题→反题→合题） |
| **开场方式** | CARS 模型（领地→利基→占领） | "智识契约"——第一段建立改变认知的承诺 |
| **证据使用** | 支撑自己的结论 | 系统排除替代假设 |
| **Discussion** | 解释发现 + 理论连接 | 提出新的概念框架 / 重新定义问题边界 |
| **结论** | 总结贡献 | 开启新的科学疑问 |
| **语言特征** | 精准的学术语言 | 优雅简洁、高信息密度的"科学散文" |
| **图表** | 展示数据 | 一张概念图改变读者心智模型 |
| **Impact 感** | "我们做了 X，效果提升了 Y%" | "这揭示了 Z 的基本原理/挑战了 W 的核心假设" |

---

## 你的角色

你是一位融合以下三重身份的科学思维建筑师：

1. **Nature/Science 资深编辑**：15 年编辑经验，精确理解什么论文在 desk reject 时被淘汰（~92% 的投稿），什么论文被送审，什么论文最终发表。你知道区分这三个层次的不是写作技术，而是思维深度和科学洞见。
2. **科学哲学家**：精通波普尔的证伪主义、库恩的范式转移、拉卡托斯的研究纲领方法论。你能将这些哲学原则转化为可执行的科学写作指令。
3. **高被引作者心理画像师**：研究过 h-index > 100 的顶级教授的写作模式——他们共同的思维特征是：**永远在思考"这对人类知识意味着什么"，而非"这个方法好不好"**。

你的任务：在 DeerFlow 当前写作技术能力（四轮累计）的基础上，注入**科学思维引擎**——使系统的输出从"技术上正确的论文"跃升为"推动领域认知边界的论文"。

---

## 实施方案：8 项科学思维引擎

### ===== 引擎 1："智识契约"开场法（Nature/Science Opening） =====

**替代场景**：当用户明确以 Nature/Science/Cell 或同级别顶刊为目标时，用此开场法取代标准 CARS 模型。

**实施位置**：在 `academic-writing/SKILL.md` 的 Step 2.1 CARS 模型之后新增

```markdown
**Nature/Science Opening: The Intellectual Contract**

Nature/Science papers do NOT follow the standard CARS model. They use a more powerful opening — the "Intellectual Contract" — which promises the reader a shift in understanding within the first paragraph.

**Structure of the Intellectual Contract (first 3-5 sentences):**

1. **The Established Truth** (1 sentence): State something the field currently believes to be true — something readers will nod along to.
   > "The ability of large language models to generate fluent text has led to the widespread assumption that these models possess genuine language understanding."

2. **The Crack** (1 sentence): Introduce a subtle but devastating challenge to that established truth.
   > "Here we show that this assumption is fundamentally flawed: models achieving near-perfect scores on comprehension benchmarks fail systematically when the same questions are rephrased using logically equivalent but syntactically unfamiliar structures."

3. **The Stakes** (1 sentence): Why this crack matters — what are the consequences if the established truth is wrong?
   > "This finding has profound implications for the deployment of LLMs in safety-critical applications where robust understanding, not pattern matching, is required."

4. **The Resolution Preview** (1-2 sentences): What this paper does about it — stated at the level of insight, not method.
   > "By developing a new evaluation framework grounded in formal semantics, we demonstrate that apparent comprehension can be decomposed into genuine understanding and surface-level pattern exploitation, enabling the first reliable measurement of true language competence in neural models."

**Key differences from CARS**:
- CARS says "there's a gap in the literature" → Intellectual Contract says "the field's fundamental assumption may be wrong"
- CARS is additive ("we add X to the literature") → Intellectual Contract is transformative ("we change how you think about X")
- CARS builds slowly → Intellectual Contract delivers the punchline immediately

**When to use**: ONLY for papers targeting Nature/Science/Cell/PNAS or equivalent venues where the contribution is a conceptual shift, not an incremental improvement.
```

### ===== 引擎 2：假设-排除推理框架 =====

**实施位置**：在 SKILL.md 中 Phase 2 Step 2.1 的 Methodology 指南之后新增

```markdown
**Falsification-Oriented Reasoning (for Nature/Science-level papers)**

Top scientific papers don't just show that their hypothesis is supported — they systematically eliminate alternative explanations. This Popperian approach is the gold standard for Nature/Science.

**The Hypothesis Elimination Framework**:

1. **State your central hypothesis (H₁)** explicitly
2. **Generate alternative hypotheses (H₂, H₃, ...)** that could explain the same observations
3. **Design "crucial experiments"** that distinguish H₁ from alternatives — experiments whose outcomes would be different under each hypothesis
4. **Report results as eliminations**: "Result X rules out H₂ because... Result Y is inconsistent with H₃ because... Only H₁ is consistent with all observed results."

**Writing pattern for each crucial experiment**:
> "If [Alternative Hypothesis H₂] were correct, we would expect [Prediction P₂]. Instead, we observe [Result R], which is inconsistent with H₂ (p < 0.001) but consistent with our proposed mechanism H₁."

**Experimental Design Implications**:
- **Positive controls**: Show that your method CAN detect the effect when it exists
- **Negative controls**: Show that your method does NOT produce false positives
- **Ablation as hypothesis testing**: Each ablation should correspond to removing a specific mechanistic component, not just an architectural component

**The "Alternative Explanations" paragraph** (in Discussion or Results):

Always include a paragraph that explicitly considers and refutes the most likely alternative explanations:
> "Several alternative mechanisms could account for the observed improvement. First, [Alternative 1]... However, our control experiment (Fig. 3B) demonstrates that... Second, [Alternative 2]... This is ruled out by... The most parsimonious explanation consistent with all evidence is [your mechanism]."
```

### ===== 引擎 3：概念层次架构（从 Method 到 Insight） =====

**实施位置**：在 Discussion 五层模型之后新增

```markdown
**Conceptual Elevation: From Results to Insight**

The difference between a good paper and a Nature paper often lies in ONE paragraph in the Discussion where the author elevates from "what we found" to "what this means for how we understand the world."

**The Elevation Ladder**:

| Level | Question | Nature of Statement | Example |
|:-----:|----------|--------------------| --------|
| 0 | What happened? | Observation | "Model A outperformed Model B by 15%" |
| 1 | Why? | Mechanism | "This is because A can capture long-range dependencies" |
| 2 | So what? (for the field) | Theoretical insight | "This reveals that the dominant paradigm of local processing is insufficient — a finding that challenges the core assumption of [Theory X]" |
| 3 | So what? (for science) | Broader principle | "More broadly, this suggests that [general principle], which may extend beyond [specific domain] to [broader class of phenomena]" |
| 4 | What next? | New questions | "This raises the question of whether [deeper question] — a question that could not even be formulated without the conceptual framework developed here" |

**Rules**:
- Good papers reach Level 1-2. Nature/Science papers reach Level 3-4.
- Level 3-4 statements require the most careful hedging ("suggests", "may indicate", "is consistent with the hypothesis that")
- A paper that only reaches Level 0-1 in Discussion will be rejected as "descriptive, not insightful"
- The "Level 3" paragraph is often the single most important paragraph in the entire paper
```

### ===== 引擎 4：概念图设计（The Conceptual Figure） =====

**实施位置**：在 Phase 3.7 (Figure Design) 之后新增

```markdown
**The Conceptual Figure (Nature/Science Signature)**

Nature/Science papers almost always contain one "conceptual figure" — typically Figure 1 — that is NOT a system diagram or data plot, but a visual representation of the paper's core IDEA. This figure captures the intellectual shift the paper proposes.

**Types of Conceptual Figures**:

| Type | When to use | Example |
|------|------------|---------|
| **Before/After** | Your work changes how we model something | Left: old understanding. Right: new understanding. Arrow showing the shift |
| **Mechanism Schematic** | You've discovered a new mechanism | Step-by-step visual of the causal chain |
| **Unifying Framework** | You unify previously separate concepts | Venn diagram or hierarchical map showing how pieces connect |
| **Scale Bridge** | Your finding connects micro and macro | Multi-scale diagram (molecular → cellular → organismal → population) |
| **Conceptual Space** | You've mapped out a new landscape | 2D conceptual space with regions labeled (like a phase diagram) |

**Design principles**:
- Minimal text — the figure should be "readable" in 10 seconds
- Use spatial relationships to encode logical relationships
- Use color semantically (not decoratively)
- Include a one-line "punchline" as the figure title: not "Overview" but "X enables Y by Z"
- This figure often becomes the paper's visual identity — make it memorable

**Caption structure for conceptual figures**:
> "**Figure 1: [One-sentence insight statement].** **a**, [Description of panel a]. **b**, [Description of panel b]. The key insight is that [restate the intellectual contribution visually represented]."
```

### ===== 引擎 5：精确范围界定（Precision of Scope） =====

**实施位置**：在 Phase 1.6 Contribution Positioning 之后新增

```markdown
### Phase 1.6.5: Precision of Scope

Top papers are precise about what they claim AND what they do not claim. This is what separates confident science from overclaiming.

**The Scope Statement Formula**:
> "We show that [specific claim] under conditions [boundary conditions]. We do not claim that [explicit non-claim], which remains an open question."

**Scope dimensions to explicitly address**:

| Dimension | What to specify |
|-----------|----------------|
| **Generality** | Does this hold for all X, or only for a specific subset? |
| **Conditions** | Under what conditions does your result hold? |
| **Mechanism vs. correlation** | Are you claiming causation or association? |
| **Quantitative bounds** | Within what range is your result valid? |
| **Temporal scope** | Is this a transient or permanent effect? |

**Anti-overclaiming checklist**:
- ❌ "We solve the problem of X" → ✅ "We advance the state of X by [specific amount/way]"
- ❌ "This proves that X" → ✅ "This provides strong evidence that X" (unless you have a mathematical proof)
- ❌ "For the first time ever" → ✅ "To the best of our knowledge, this is the first [specific claim]"
- ❌ "Our method is superior" → ✅ "Our method outperforms baselines on [specific metrics] under [specific conditions]"
```

### ===== 引擎 6：科学散文风格（Nature/Science Prose） =====

**实施位置**：在 Phase 3 Step 3.1 学术语言润色之后新增

```markdown
#### Step 3.1.3: Scientific Prose Style (for Top-Tier Venues)

Nature/Science papers have a distinctive writing style — "scientific prose" — that is simultaneously precise, concise, and elegant. It is NOT the same as standard academic writing.

**Key differences from standard academic prose**:

| Standard Academic | Nature/Science Prose |
|------------------|---------------------|
| "It has been demonstrated that X leads to Y (Smith et al., 2020)" | "X drives Y [1]" |
| "In this study, we propose a novel method for..." | "Here we show that..." / "We demonstrate..." |
| "The results of our experiments demonstrate that..." | "Our experiments reveal..." |
| "It is important to note that..." | (Just state the point directly) |
| "Due to the fact that..." | "Because..." |
| "In order to..." | "To..." |
| "A large number of" | "Many" / specify the exact number |
| 250-word paragraphs | 80-150 word paragraphs |

**Nature/Science prose principles**:
1. **Ruthless conciseness**: Cut every word that doesn't carry information. "Due to the fact that" → "Because". "It should be noted that" → delete entirely.
2. **Strong verbs over weak constructions**: "We performed an analysis of" → "We analyzed". "There was an increase in" → "X increased".
3. **Short sentences for key claims**: Your most important statement should be your shortest sentence. "Attention is all you need." Not: "Our experimental results demonstrate that the attention mechanism alone, without the need for recurrent or convolutional components, is sufficient for achieving state-of-the-art performance."
4. **Paragraph compression**: Nature paragraphs are typically 3-5 sentences (80-150 words), NOT 8-10 sentences. One idea, one paragraph, maximum compression.
5. **"Here we show" as the canonical pivot**: Nature papers almost universally use "Here we show that..." or "Here we demonstrate..." as the pivotal sentence. Never "In this paper, we propose a novel..."
6. **Active voice throughout**: "We measured" not "Measurements were taken". Active voice is shorter, clearer, and more authoritative.

**Sentence-level compression exercise**:
Before: "In this paper, we present a novel framework that is designed to address the challenging problem of long-range dependency modeling in sequential data by incorporating a mechanism that enables the model to selectively attend to relevant portions of the input sequence." (46 words)
After: "We introduce a selective attention mechanism for modeling long-range dependencies in sequences." (12 words)
```

### ===== 引擎 7：Nature/Science 格式适配 =====

**实施位置**：在 Phase 5.3 Venue Format Compliance 中替换 Nature/Science 条目

```markdown
**Nature/Science/Cell Format Requirements**:

| Constraint | Nature | Science | Cell |
|-----------|--------|---------|------|
| Main text | ~3,000 words (Article), ~1,500 (Letter) | ~2,500 words (Report), ~4,500 (Research Article) | ~5,000 words |
| Abstract | ~150 words, single paragraph, NO headings | ~125 words, single paragraph | ~150 words, structured (eTOC blurb + Highlights) |
| Figures | Max 6 (main) + unlimited supplementary | Max 4 (Report) / 6 (Article) | Max 7 |
| References | ~30 (Letter) / ~50 (Article) | ~30 (Report) / ~50 (Article) | ~60-80 |
| Methods | In main text (brief) + Extended Data | Supplementary Materials | STAR Methods (structured) |
| Structure | No numbered sections, flowing prose | Report: single continuous flow | Intro, Results, Discussion, STAR Methods |

**Nature-specific writing rules**:
- NO numbered sections — use topic transitions, not "Section 2.3"
- Methods go in "Methods" section at the end (brief) + Extended Data Methods (detailed)
- First paragraph IS the introduction — no separate "Introduction" heading
- Figures referenced as "Fig. 1a" (lowercase 'a' for panels)
- "Extended Data" for supplementary figures/tables (not "Supplementary")
- Data/code availability statement required after Methods

**Cell-specific requirements**:
- Requires "eTOC blurb" (~50 words for Table of Contents)
- Requires "Highlights" (3-4 bullet points, each ≤85 characters)
- Uses "STAR Methods" (Structured, Transparent, Accessible Reporting) with specific subsections: Key Resources Table, Resource Availability, Experimental Model and Study Participant Details, Method Details, Quantification and Statistical Analysis
- "Graphical Abstract" required — a single-panel conceptual summary
```

### ===== 引擎 8：新科学疑问开启法 =====

**实施位置**：在 Discussion 五层模型 Layer 5 之后新增

```markdown
**Layer 6 (Nature/Science only) — Opening New Questions**

The ultimate mark of a paradigm-shifting paper: the Conclusion doesn't just summarize — it opens a door to questions that couldn't even be formulated before this paper existed.

**Structure**:
> "Our findings raise the intriguing possibility that [new question that emerges from your work]. If [your key finding] indeed reflects [deeper principle], then we would predict [testable prediction for future work]. Testing this prediction would require [specific experiment/observation], which is now feasible given [your contribution]."

**The "New Question" quality test**: A good closing question satisfies ALL of:
1. It could NOT have been asked before your paper
2. It is specific enough to be testable
3. It is broad enough to interest a wide readership
4. Answering it would have significant implications

**Anti-pattern**: "Future work could improve performance on more datasets" — this is NOT a new scientific question; it's a to-do list item.
```

---

## Lead Agent 提示词增强

在 `<academic_research>` 段落的第 8 条 "Master-Level Writing Craft" 之后新增第 9 条：

```
**9. Nature/Science-Level Scientific Thinking (Apply When Targeting Top Venues)**

When the user explicitly targets Nature/Science/Cell/PNAS or equivalent top venues:
- Use the "Intellectual Contract" opening instead of standard CARS — promise a cognitive shift in paragraph one
- Apply falsification-oriented reasoning: systematically generate and eliminate alternative hypotheses
- Elevate Discussion to Level 3-4 on the Conceptual Ladder (from findings to principles to new questions)
- Design a Conceptual Figure (Fig. 1) that captures the intellectual shift, not just the system architecture
- Write in Nature/Science prose style: ruthlessly concise, active voice, "Here we show...", 80-150 word paragraphs
- Apply precision of scope: explicitly state what you claim AND what you do not claim
- End with a genuine new scientific question that your work enables for the first time
- Enforce venue-specific constraints (word limits, figure limits, Methods placement)
```

---

## 实施位置总表

| # | 引擎 | 实施位置 | 方式 |
|---|------|---------|------|
| 1 | 智识契约开场法 | `SKILL.md` Phase 2 Step 2.1, CARS 之后 | 新增 |
| 2 | 假设-排除推理框架 | `SKILL.md` Phase 2 Step 2.1, Methodology 后 | 新增 |
| 3 | 概念层次架构 | `SKILL.md` Phase 2, Discussion 五层后 | 新增 Layer 6 + 概念阶梯 |
| 4 | 概念图设计 | `SKILL.md` Phase 3.7 后 | 新增 Phase 3.8 |
| 5 | 精确范围界定 | `SKILL.md` Phase 1.6 后 | 新增 Phase 1.6.5 |
| 6 | 科学散文风格 | `SKILL.md` Phase 3 Step 3.1 后 | 新增 Step 3.1.3 |
| 7 | NSC 格式适配 | `SKILL.md` Phase 5.3 | 扩展现有条目 |
| 8 | 新科学疑问开启法 | `SKILL.md` Phase 2, Discussion Layer 5 后 | 新增 Layer 6 |
| 9 | Lead Agent 第 9 条 | `prompt.py` <academic_research> | 新增 |

## 约束条件

1. 所有 "Nature/Science-level" 指令仅在用户明确表示投稿 Nature/Science/Cell/PNAS 或同级别顶刊时激活，不影响普通论文写作流程
2. SKILL.md 总长度控制在 1400 行以内（当前 1085 行，可用空间 ~315 行）
3. 新增内容以条件触发（"When targeting top venues..."）方式嵌入，而非替换现有内容
4. 保持与已有 Phase 编号体系的兼容性
