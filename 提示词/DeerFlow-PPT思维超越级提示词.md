# DeerFlow PPT 能力超越级强化提示词：从演示技术到认知建筑术

---

## 核心诊断

上一轮（408 行 `academic-ppt/SKILL.md`）注入了 10 项**演示技术**——叙事弧线、断言-证据模型、认知负荷控制、听众适配、排版规范、数据可视化简化、Speaker Notes、备用幻灯片、演讲类型模板、渐进式揭示。

这些是"**怎么做好幻灯片**"的技术。但观看 Steve Jobs 的 iPhone 发布、Hinton 的 NeurIPS keynote、或 Jennifer Doudna 的诺贝尔演讲后，你会意识到——那些演讲之所以不同凡响，不是因为幻灯片更精美，而是因为演讲者在**设计观众的认知体验**。

| 上一轮（演示技术层） | 本轮（认知建筑层） |
|:---:|:---:|
| 知道用断言-证据模型 | 能设计一个让观众"自己得出结论"的信息揭示序列 |
| 知道控制认知负荷 | 能精确操控观众的注意力焦点在幻灯片的时间轴上移动 |
| 知道 5 幕叙事弧 | 能构建"认知地震"——让观众的世界观在第 N 张幻灯片上裂开 |
| 知道简化论文图表 | 能用一张图改变观众对整个问题的心智模型 |
| 知道准备备用幻灯片 | 能预判听众的认知阻力点并在主演中主动化解 |

---

## 你的角色

1. **认知建筑师**：你设计的不是幻灯片，而是观众脑中的思维建筑。每张幻灯片放置一块认知砖，最终建成一座让观众无法反驳的理解大厦。
2. **注意力导演**：你精确控制观众在每一秒注意什么、忽略什么——就像电影导演控制镜头一样。
3. **"顿悟时刻"工程师**：你追求的不是"观众理解了"，而是"观众在第 N 张幻灯片上顿悟了"——那个瞬间比任何数据都有说服力。

---

## 7 项认知建筑术

### ===== 术 1：认知地震设计 =====

**实施位置**：`academic-ppt/SKILL.md` Step 1.5 叙事弧线之后新增

```markdown
### Step 1.5.5: Cognitive Earthquake Design

The most memorable talks contain ONE moment where the audience's mental model cracks and is rebuilt. Design this moment intentionally.

**The Earthquake Pattern** (3 phases):

**Phase A — Build the Old World** (3-5 slides): Establish what everyone currently believes. Use clear, familiar language. The audience should be nodding along: "Yes, this is how I understand it."

**Phase B — The Quake** (1-2 slides): Present ONE piece of evidence that the old model cannot explain. A failure case. A counter-example. An unexpected result. The audience should feel: "Wait... that can't be right."

**Phase C — The New World** (3-5 slides): Present YOUR framework/model that explains BOTH the old evidence AND the new. The audience should feel: "Oh! Now I see it differently."

**Examples from legendary talks**:
- Jobs (iPhone): "Phone + iPod + Internet — these are NOT three devices" → QUAKE → "It's ONE device"
- Hinton (Capsules): "CNNs are incredibly successful" → QUAKE → "But they can't distinguish left from right" → New model
- Attention paper: "Seq2seq with RNNs works well" → QUAKE → "But they can't attend to distant tokens" → Attention

**Implementation**: Identify your Quake slide. Make it visually distinct (darker background, single large image/number, full-bleed). Everything before it builds the setup; everything after it delivers the payoff.
```

### ===== 术 2：引导式发现法 =====

```markdown
### Step 2.5.5: Guided Discovery Method

Instead of TELLING the audience your conclusion, LEAD them to discover it themselves. Self-discovered conclusions are 10x more persuasive than stated ones.

**Technique**: Present the evidence BEFORE the conclusion. Let the audience draw the inference from the data.

**Traditional** (weak — you tell):
```
Slide: "Our method is better because it handles long-range dependencies"
[Then show data supporting this]
```

**Guided Discovery** (strong — they discover):
```
Slide 1: [Chart showing all methods' performance vs. sequence length]
Slide 2: [Zoom into the long-sequence region — your method diverges upward]
Slide 3: "Why? Because our attention mechanism directly captures long-range structure"
```

The audience sees the pattern, wonders why, and THEN you explain. They feel like they figured it out, not like you told them.

**The "Question Before Answer" Rule**: For every key insight, first pose it as a question (visually or verbally), pause 2-3 seconds, then reveal the answer. The pause creates anticipation and activates the audience's own reasoning.
```

### ===== 术 3：视觉焦点时间轴 =====

```markdown
### Step 2.7.5: Visual Attention Timeline

Design exactly WHERE the audience looks at each moment. On every slide, there should be ONE focal point, and you control the sequence in which secondary elements are noticed.

**The F-Pattern / Z-Pattern Principle**:
- Western audiences scan: Top-left → Top-right → Middle-left → Bottom-right
- Place your most important element (the assertion) at the top
- Place visual evidence in the center (largest area)
- Place source/footnote at bottom-right (noticed last)

**Contrast Hierarchy** (what gets noticed first):
1. Largest element (size dominance)
2. Highest contrast (color pop against muted background)
3. Isolated element (surrounded by white space)
4. Motion (if video/GIF — use sparingly)

**Practical rule**: On every slide, circle what you want the audience to look at FIRST. If there's no clear answer, the slide has a focus problem — redesign it.

**"Where Are They Looking?" test**: For each slide, write one sentence: "The audience's eye goes to _____ first, then _____, then _____." If you can't answer this clearly, simplify.
```

### ===== 术 4：类比桥接法 =====

```markdown
### Step 2.9: Analogy Bridging

The most effective way to explain a complex technical concept is to bridge it to something the audience already understands.

**The Analogy Formula**: "[Complex concept] is like [familiar concept], except [key difference]."

**Examples**:
- "Attention is like a spotlight that the model can point at different parts of the input"
- "Dropout is like randomly removing roads in a city — the remaining routes become more robust"
- "A GAN is like a counterfeiter (generator) trying to fool a detective (discriminator)"

**Rules for good analogies**:
1. The familiar concept must be UNIVERSALLY understood (not domain-specific)
2. The mapping must be STRUCTURALLY correct (not just superficially similar)
3. State the LIMITS of the analogy: "Unlike [analogy], [concept] also [difference]"
4. Use a single visual slide that shows the analogy side-by-side with the real concept

**Analogy Slide Template**:
- Left half: Familiar concept (with everyday illustration)
- Right half: Your concept (with technical diagram)
- Arrow or equals sign connecting the analogous parts
- One sentence at the bottom: "[Familiar] → [Technical]: [the key insight]"
```

### ===== 术 5：情绪节奏控制 =====

```markdown
### Step 1.5.7: Emotional Rhythm Control

Great presentations alternate between tension and relief, complexity and simplicity, like breathing.

**The Rhythm Map**:

| Slide Block | Emotion | Pace | Visual Density |
|:-----------:|---------|:----:|:--------------:|
| Hook | Curiosity/surprise | Fast | Low — one striking image |
| Problem | Tension/concern | Medium | Medium — show the failure |
| Key Insight | Excitement/aha! | Slow — PAUSE here | Low — one powerful statement |
| Method | Intellectual engagement | Medium | Medium-High — diagrams |
| Results | Satisfaction | Medium | Medium — charts |
| Demo/Example | Delight | Fast | Visual — live or animated |
| Conclusion | Elevation/inspiration | Slow | Low — one takeaway sentence |

**The "Breathing" Principle**: After every HIGH-density slide (complex diagram, results table), follow with a LOW-density slide (one sentence, one image, or a section divider). This gives the audience time to absorb.

**Pause Design**: Mark 3 moments in the talk where you deliberately PAUSE for 3-5 seconds:
1. After the Quake slide (let it sink in)
2. After showing the main result (let them read the number)
3. Before the final takeaway (build anticipation)
```

### ===== 术 6：开场与收尾的对称设计 =====

```markdown
### Step 1.5.9: Bookend Design

The most elegant talks end where they began — creating a narrative circle that gives the audience a sense of completeness.

**The Bookend Pattern**:
- **Opening**: Pose a question, show a failure, or present a challenge
- **Closing**: Return to the SAME question/failure/challenge and show how your work transforms the answer

**Example**:
- Open: "Here is a math problem that GPT-4 gets wrong 94% of the time" [show the wrong answer]
- Close: "Remember this problem? Here is CalcFormer's answer." [show the correct answer]

**Implementation**: Design your FIRST and LAST content slides as a pair. They should be visually similar (same layout, same colors) but with the KEY element changed (failure → success, question → answer, old → new).

**The "Full Circle" Test**: Does your last slide make more sense BECAUSE of your first slide? If you could swap the order of your conclusion with any random talk's conclusion, your bookend is too generic.
```

### ===== 术 7：论文→演讲的认知转换引擎 =====

```markdown
### Step 0.5: Paper-to-Talk Cognitive Transformation

A presentation is NOT a paper read aloud. It requires a fundamental cognitive transformation of the content:

**What to CUT from the paper**:
- Literature review details (keep only 2-3 positioning references)
- Proof details (move to backup slides)
- Most related work (keep only the closest competitor)
- Implementation details (unless the audience is highly technical)
- Most ablation details (show 1-2 key ablations, rest in backup)

**What to ADD that's NOT in the paper**:
- A hook that creates curiosity (papers don't need hooks)
- Analogies and intuitive explanations (papers use formal definitions)
- A demo or live example (papers can't do this)
- A failure case or "what doesn't work" (builds trust)
- A provocative future question (papers end with "future work")

**What to TRANSFORM**:
- Abstract → 1-sentence pitch on title slide subtitle
- Introduction → Hook + Quake setup
- Method section → Visual pipeline diagram + key intuition
- Results tables → 1-2 highlight charts with One Number
- Discussion → Implications stated as assertions
- Conclusion → Bookend callback to opening

**The "Inverse Pyramid" Rule**: Papers give context first, results last. Great talks can do the OPPOSITE — start with the result ("We improved X by 23%"), then explain how ("Here's why..."), then contextualize ("This matters because..."). Audience hooks on the result and stays for the explanation.
```

---

## Lead Agent 提示词增强

在 `<academic_research>` 第 13 条后新增第 14 条：

```
**14. Cognitive Architecture for Presentations (Apply for High-Stakes Talks)**

When creating presentations for keynotes, conference best-paper talks, thesis defenses, or invited lectures:
- Design a "Cognitive Earthquake": build the old world → one slide shatters it → rebuild with your model
- Use Guided Discovery: present evidence BEFORE conclusions — let the audience draw inferences themselves
- Control Visual Attention Timeline: design exactly where eyes go on every slide (size → contrast → isolation)
- Bridge complex concepts with universally understood analogies (the Analogy Slide: familiar ↔ technical)
- Control Emotional Rhythm: alternate high-density/low-density slides; mark 3 deliberate pauses
- Apply Bookend Design: opening and closing slides form a narrative circle (question → answer)
- Paper-to-Talk transformation: cut lit review details, ADD hooks/analogies/demos/failure cases, use Inverse Pyramid (result first)
```

---

## 实施位置总表

| # | 术 | 实施文件 | 位置 | 方式 |
|---|---|---------|------|------|
| 1 | 认知地震设计 | `academic-ppt/SKILL.md` | Step 1.5 后 | 新增 Step 1.5.5 |
| 2 | 引导式发现法 | `academic-ppt/SKILL.md` | Step 2.5 后 | 新增 Step 2.5.5 |
| 3 | 视觉焦点时间轴 | `academic-ppt/SKILL.md` | Step 2.7 后 | 新增 Step 2.7.5 |
| 4 | 类比桥接法 | `academic-ppt/SKILL.md` | Step 2.8 后 | 新增 Step 2.9 |
| 5 | 情绪节奏控制 | `academic-ppt/SKILL.md` | Step 1.5 后 | 新增 Step 1.5.7 |
| 6 | 开场收尾对称 | `academic-ppt/SKILL.md` | Step 1.5.7 后 | 新增 Step 1.5.9 |
| 7 | 论文→演讲转换 | `academic-ppt/SKILL.md` | Step 1 前 | 新增 Step 0.5 |
| 8 | Lead Agent 第 14 条 | `prompt.py` | `<academic_research>` | 新增 |

## 约束条件

1. `academic-ppt/SKILL.md` 总长度控制在 550 行以内（当前 408 行，可用 ~142 行）——每项必须极度精炼
2. 每项引擎以具体示例驱动，避免抽象描述
3. 保持与已有 Step 编号兼容
4. 不修改 `academic_pptx.py` 脚本和 `ppt-generation/SKILL.md`
