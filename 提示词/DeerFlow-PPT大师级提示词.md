# DeerFlow PPT 制作能力大师级强化提示词

---

## 项目当前状态诊断

### 现有 PPT 能力（两大技能）

| 技能 | 行数 | 核心能力 | 深度 |
|------|:----:|---------|:----:|
| `academic-ppt` | 272 + 678 行脚本 | python-pptx 原生可编辑 PPTX、6 种学术风格、10 种幻灯片类型、LaTeX 公式、Speaker Notes、参考文献页 | ⭐⭐⭐ |
| `ppt-generation` | 464 | AI 图像生成式 PPT、8 种视觉风格（glassmorphism/dark-premium 等）、逐张引用链保持一致性 | ⭐⭐⭐⭐ |

### 精确差距分析

| # | 缺失维度 | 影响 | 当前 | 顶级水平 |
|---|---------|:---:|------|---------|
| 1 | **演示叙事设计** | 致命 | 零 — 只是幻灯片序列，无叙事弧 | 一场演讲是一个有起承转合的故事 |
| 2 | **断言-证据模型** | 致命 | Bullet points 列表 | 每张幻灯片 = 一个完整主张句 + 一个视觉证据 |
| 3 | **认知负荷控制** | 高 | 零 | 每张幻灯片严格控制信息量，服从工作记忆限制 |
| 4 | **听众适配策略** | 高 | 零 | 同一内容适配不同听众（技术/通用/评审委员） |
| 5 | **幻灯片排版规范** | 高 | 基础字号 | 字号层级、对比度、留白比例、色彩使用的精确规则 |
| 6 | **数据可视化简化** | 中 | 直接嵌入论文图表 | 论文图表→幻灯片图表需要简化和放大 |
| 7 | **Speaker Notes 专业化** | 中 | 占位句 | 结构化演讲稿含时间标记和过渡句 |
| 8 | **备用/附录幻灯片** | 中 | 零 | Q&A 预判 + 深度备用幻灯片集 |
| 9 | **演讲类型差异化** | 中 | 时长→幻灯片数映射 | Lightning/Conference/Keynote/Defense 各有独特结构 |
| 10 | **渐进式揭示策略** | 中 | 零 | 复杂内容分步呈现，控制观众注意力 |

---

## 你的角色

1. **TED 级演示设计师**：深知"幻灯片不是文档，而是视觉伴奏"——观众应该在听你讲话，偶尔看幻灯片确认理解，而非逐字阅读屏幕。
2. **Michael Alley 断言-证据法实践者**：精通《The Craft of Scientific Presentations》中的方法论——用完整主张句替代标题 + 用视觉证据替代 bullet points。
3. **Nature/AAAI 最佳论文报告分析师**：研究过 50+ 顶级会议最佳论文报告的共同特征——清晰的叙事弧、极简的视觉、精准的时间控制。

---

## 10 项大师级演示能力

### ===== 能力 1：演示叙事弧线设计 =====

**实施位置**：`academic-ppt/SKILL.md` Step 1 之后新增

```markdown
### Step 1.5: Presentation Narrative Design

A presentation is NOT a paper read aloud. It is a performance with a narrative arc. Design the arc BEFORE creating any slides.

**The 5-Act Presentation Structure**:

| Act | Slides | Purpose | Audience State |
|:---:|:------:|---------|---------------|
| **1. Hook** | 1-2 | Grab attention — pose a surprising question, show a failure case, state a bold claim | "This is interesting" |
| **2. Context** | 3-5 | Build shared understanding — only what's needed for the audience to follow your story | "I understand the problem" |
| **3. Journey** | 5-8 | Your approach and how it works — build intuition before details | "I see how this works" |
| **4. Proof** | 3-5 | Evidence that it works — key results, not ALL results | "I'm convinced" |
| **5. Impact** | 1-2 | Why this matters beyond your paper — open a bigger question | "I want to learn more" |

**Narrative Tension Rule**: Tension should RISE through Acts 1-2 (problem is hard, existing solutions fail), RESOLVE in Act 3 (your insight), and be VALIDATED in Act 4 (results). Act 5 ELEVATES to a bigger picture.

**The "Bar Conversation" Test**: Can you explain your entire talk in 3 sentences over a drink? Those 3 sentences are your Acts 1, 3, and 5. Everything else is supporting detail.
```

### ===== 能力 2：断言-证据幻灯片模型 =====

```markdown
### Step 2.5: Assertion-Evidence Slide Model

Replace traditional bullet-point slides with the Assertion-Evidence model — the gold standard for scientific presentations (Alley, 2013).

**Traditional slide** (weak):
```
Title: Experimental Results
• Method A: 85.2% accuracy
• Method B: 87.4% accuracy  
• Our method: 91.3% accuracy
• Our method is 4% better than the best baseline
```

**Assertion-Evidence slide** (strong):
```
Assertion (full sentence as title): "Our method outperforms all baselines by 4+ points across all metrics"
Evidence (visual): [Bar chart showing the comparison with significance brackets]
```

**Rules**:
1. **Title = Full sentence assertion** (not a topic label). "Our method outperforms baselines" NOT "Results"
2. **Body = Visual evidence** supporting the assertion — a chart, diagram, image, or key equation. NOT bullet points.
3. **Maximum 1 assertion per slide**. If you have 2 points, use 2 slides.
4. **Assertion must be self-contained**: If someone reads ONLY slide titles in sequence, they should understand the entire argument.

**The "Title-Only Storyboard" Test**: Write out just the slide titles. Do they tell a coherent story?
```
1. "Language models fail at elementary arithmetic despite high benchmark scores"
2. "The core issue: Transformers are pattern matchers, not calculators"
3. "We embed a symbolic engine directly into the attention mechanism"
4. "CalcFormer achieves 23.7% improvement on math reasoning benchmarks"
5. "This suggests neural-symbolic hybrids are the path forward for reasoning"
```
If yes → good narrative. If titles are "Introduction", "Method", "Results" → rewrite.
```

### ===== 能力 3：认知负荷控制 =====

```markdown
### Step 2.7: Cognitive Load Management

Working memory holds ~4 items simultaneously (Cowan, 2001). Every slide must respect this limit.

**Per-Slide Limits**:

| Element | Maximum | Why |
|---------|:-------:|-----|
| Key message | 1 | One idea per slide |
| Text lines | 4-5 | More = audience reads instead of listening |
| Words per line | 8-10 | Longer = reading time exceeds glance time |
| Data series in chart | 4-5 | More = visual noise |
| Colors | 3-4 | More = distraction |
| Total words on slide | 30-40 | Slides are NOT documents |

**The "6-Second Rule"**: An audience member should understand the slide's main point within 6 seconds of seeing it. If it takes longer, simplify.

**The "Squint Test"**: Squint at the slide from 2 meters. Can you still identify the visual hierarchy (title → main element → supporting detail)? If not, contrast/sizing is wrong.
```

### ===== 能力 4：听众适配策略 =====

```markdown
### Step 1.3: Audience Adaptation

The same research requires completely different presentations for different audiences:

| Audience | Depth | Jargon | Slides | Focus |
|----------|:-----:|:------:|:------:|-------|
| **Conference (peers)** | Deep | Full technical | 15-20 | Method details + results |
| **Department seminar** | Medium | Moderate | 25-35 | Context + method + implications |
| **Thesis defense** | Very deep | Full | 40-50 | Everything — committee tests depth |
| **Invited talk (broad)** | Shallow | Minimal | 20-30 | Motivation + intuition + impact |
| **Lightning talk** | Surface | Minimal | 5-7 | Hook + one key idea + result |
| **Industry audience** | Practical | Minimal | 15-20 | Problem + solution + business value |

**Adaptation principle**: For technical audiences, start with the method and prove it works. For general audiences, start with WHY it matters and only show enough method to build trust.
```

### ===== 能力 5：幻灯片排版规范 =====

```markdown
### Step 2.3: Slide Typography & Visual Standards

**Font Size Hierarchy** (for 16:9 at standard projector distance):

| Element | Size | Weight |
|---------|:----:|:------:|
| Slide title (assertion) | 28-32pt | Bold |
| Subtitle/section | 24pt | Semibold |
| Body text | 20-24pt | Regular |
| Chart labels | 16-18pt | Regular |
| Source/footnote | 12-14pt | Light |
| MINIMUM readable | 16pt | — |

**Contrast & Color**:
- Text on light background: contrast ratio ≥ 7:1 (WCAG AAA)
- Title: darkest color. Body: slightly lighter. Footnotes: gray
- "Your method" always in the most salient color (blue or accent)
- Baselines in muted gray/desaturated tones
- Maximum 3-4 colors in any single chart

**Layout Rules**:
- Margins: ≥5% on all sides (never text touching edges)
- White space: 40-50% of slide area should be empty
- Alignment: Everything on an invisible grid — no "eyeball alignment"
- Consistency: Same position for title, same margins, same fonts on EVERY slide
```

### ===== 能力 6：幻灯片数据可视化 =====

```markdown
### Step 4.3: Slide-Optimized Data Visualization

Paper figures ≠ slide figures. Slides need SIMPLIFIED versions:

| Paper Figure | Slide Adaptation |
|-------------|-----------------|
| 6 baselines in comparison table | Top 2-3 baselines + yours (audience can't process 6) |
| Dense scatter plot with 1000 points | Show trend line + CI band, not individual points |
| Multi-panel figure (a,b,c,d) | One panel per slide with progressive reveal |
| Complex architecture diagram | Simplified 3-block version for overview, detailed only if zooming in |
| Full results table | Highlight row only — bold YOUR result, gray out the rest |

**The "One Number" Rule**: If a slide shows quantitative results, the audience should walk away remembering ONE number. Make that number the largest text element on the slide. Example: a giant "23.7%" with small supporting text below.
```

### ===== 能力 7：专业 Speaker Notes =====

```markdown
### Step 2.8: Structured Speaker Notes

Speaker notes are your script. Structure them professionally:

**Format per slide**:
```
[TIMING: ~1.5 min | Cumulative: 8/15 min]

[TRANSITION FROM PREVIOUS]: "So we've seen the problem. Now let me show you our approach."

[MAIN CONTENT]: "The key insight behind CalcFormer is that we don't replace the Transformer — we augment it. Specifically, we embed a symbolic computation engine as a differentiable module within each attention layer. This means the model can learn WHEN to use the calculator and when to rely on its own pattern matching."

[POINTER CUE]: → Point to the blue module in the diagram

[TRANSITION TO NEXT]: "Now that you have the intuition, let me show you the formal definition."
```

Include for every content slide: timing marker, transition sentence from previous slide, main talking points (not a script — key phrases), pointer/gesture cues for figures, transition to next slide.
```

### ===== 能力 8：备用幻灯片 =====

```markdown
### Step 5.5: Backup Slides for Q&A

After the "Thank You" slide, always prepare backup slides anticipating likely questions:

**Standard Backup Set**:
1. **Detailed ablation study** — "What if you remove component X?"
2. **Additional datasets/metrics** — "Have you tested on dataset Y?"
3. **Computational cost** — "How much slower/faster is this?"
4. **Failure cases** — "When does your method fail?" (having this ready shows intellectual honesty)
5. **Comparison with specific related work** — "How does this compare to [recent paper]?"
6. **Mathematical details** — Full derivation that was simplified in the main talk
7. **Future work specifics** — Concrete next steps if asked

Label these clearly: "Backup: Ablation Details", "Backup: Computational Cost", etc.
```

### ===== 能力 9：演讲类型专用模板 =====

```markdown
### Step 1.7: Talk-Type Specific Templates

**Conference Talk (15-20 min)**:
```
[1] Title + Hook (1 slide)
[2] Problem & Why It's Hard (2 slides)
[3] Our Key Insight — ONE sentence (1 slide)
[4] Method Overview — visual, no math yet (2 slides)
[5] Key Method Detail — the novel part only (2-3 slides)
[6] Main Results — the headline number (2 slides)
[7] Analysis — ablation, why it works (2 slides)
[8] Conclusion + Takeaway (1 slide)
[9] Thank You / Questions (1 slide)
[10+] Backup slides (5-7 slides, hidden)
```

**Thesis Defense (45 min)**:
```
[1] Title (1 slide)
[2] Outline (1 slide)
[3] Background & Motivation (5-7 slides) — deeper than conference
[4] Related Work & Positioning (3-4 slides)
[5] Research Questions / Hypotheses (1-2 slides)
[6] Method — FULL detail (8-12 slides)
[7] Experiments & Results (8-10 slides)
[8] Discussion & Implications (3-4 slides)
[9] Limitations & Future (2 slides)
[10] Conclusion (1-2 slides)
[11] Thank You (1 slide)
[12+] Backup (10+ slides — committee will probe deeply)
```

**Lightning Talk (5 min)**:
```
[1] Hook — the problem in one visual (1 slide)
[2] Our insight — one sentence (1 slide)
[3] How it works — one diagram (1 slide)
[4] Results — one chart, one number (1 slide)
[5] Takeaway + Where to find more (1 slide)
```
No time for outline, related work, or detailed method. Every second counts.
```

### ===== 能力 10：渐进式揭示 =====

```markdown
### Step 4.5: Progressive Reveal Strategy

For complex content, don't show everything at once. Build understanding step by step:

**Architecture diagrams**: Show one component at a time. Slide 1: input → encoder (grayed middle + output). Slide 2: input → encoder → attention (grayed output). Slide 3: full pipeline.

**Results tables**: First show the baseline rows. Then animate (or use a new slide) to reveal your method's row — the audience experiences the improvement in real-time.

**Equations**: Show the intuition first (plain English). Next slide: the equation. Next slide: each term highlighted with explanation.

**Implementation in academic-ppt**: Use multiple slides with incremental content rather than animation (PPTX animation is unreliable across platforms). Each "reveal step" = one additional slide with the new element highlighted and previous elements grayed/present.
```

---

## Lead Agent 提示词增强

在 `<academic_research>` 新增第 13 条：

```
**13. Master-Level Presentation Design (Always Apply for PPT Tasks)**

When creating academic or professional presentations:
- Design the 5-Act narrative arc (Hook → Context → Journey → Proof → Impact) BEFORE creating slides
- Use the Assertion-Evidence model: slide title = full sentence claim, body = visual evidence (not bullets)
- Cognitive load control: max 1 message per slide, 30-40 words, 4-5 text lines, 6-second comprehension rule
- Adapt depth/jargon to audience: conference (deep/technical) vs. invited talk (shallow/intuitive) vs. defense (comprehensive)
- Slide typography: 28-32pt titles, ≥16pt minimum, 40-50% white space, 3-4 colors max
- Simplify paper figures for slides: fewer baselines, larger labels, one panel per slide, "One Number" rule
- Write structured speaker notes: timing markers, transitions, pointer cues, key phrases (not scripts)
- Include 5-7 backup slides anticipating likely Q&A questions
- Apply talk-type templates: lightning (5 slides), conference (15-20), defense (40-50)
- Use progressive reveal for complex content: build diagrams/tables/equations incrementally across slides
```

---

## 实施位置总表

| # | 能力 | 实施文件 | 位置 | 方式 |
|---|------|---------|------|------|
| 1 | 演示叙事弧线 | `academic-ppt/SKILL.md` | Step 1 后 | 新增 Step 1.5 |
| 2 | 断言-证据模型 | `academic-ppt/SKILL.md` | Step 2 后 | 新增 Step 2.5 |
| 3 | 认知负荷控制 | `academic-ppt/SKILL.md` | Step 2.5 后 | 新增 Step 2.7 |
| 4 | 听众适配策略 | `academic-ppt/SKILL.md` | Step 1 后 | 新增 Step 1.3 |
| 5 | 排版规范 | `academic-ppt/SKILL.md` | Step 2 中 | 新增 Step 2.3 |
| 6 | 幻灯片数据可视化 | `academic-ppt/SKILL.md` | Step 4 后 | 新增 Step 4.3 |
| 7 | Speaker Notes 专业化 | `academic-ppt/SKILL.md` | Step 2 后 | 新增 Step 2.8 |
| 8 | 备用幻灯片 | `academic-ppt/SKILL.md` | Step 5 后 | 新增 Step 5.5 |
| 9 | 演讲类型模板 | `academic-ppt/SKILL.md` | Step 1 后 | 新增 Step 1.7 |
| 10 | 渐进式揭示 | `academic-ppt/SKILL.md` | Step 4 后 | 新增 Step 4.5 |
| 11 | Lead Agent 第 13 条 | `prompt.py` | `<academic_research>` | 新增 |

## 约束条件

1. `academic-ppt/SKILL.md` 总长度控制在 550 行以内（当前 272 行，可用 ~278 行）
2. 只修改 `academic-ppt/SKILL.md` 和 `prompt.py`，不修改 `ppt-generation/SKILL.md`（那是图像生成式，设计哲学不同）
3. 新增内容以可执行的规则和模板驱动，非纯理论
4. 保持与现有 Step 编号和 JSON 幻灯片类型系统的兼容性
5. 不修改 `academic_pptx.py` 脚本
