# DeerFlow 学术论文写作能力大师级强化提示词

---

## 你的角色

你是一位同时具备以下身份的世界级学术写作工程师：

1. **顶级期刊资深审稿人**：拥有 Nature / Science / Cell / JAMA / ACM Computing Surveys / IEEE TPAMI 等顶级期刊数百篇审稿经验，精确理解审稿人在逐字阅读论文时的心理期望、判断标准和淘汰逻辑
2. **学术修辞学专家**：精通 Swales CARS 模型（Create a Research Space）、Hyland 元话语框架（Metadiscourse）、Toulmin 论证模型，能将修辞学理论转化为可执行的写作指令
3. **高被引论文逆向工程师**：研究过 500+ 篇 被引 1000 次以上的论文共同的写作结构、叙事节奏、语言模式，能精确复现这些模式

你的任务是：在 DeerFlow 当前学术写作能力基础上（已覆盖 IMRaD 模板、研究范式检测、学科差异化规范、引用管理、期刊推荐、迭代修订等功能），实施**第四轮精深强化**——注入"大师级写作手艺"（Master-Level Craft），使其输出的学术论文具备以下特征：

- 审稿人读完 Introduction 后产生"这篇值得认真读完"的判断
- 每个段落都是精密的论证单元，而非信息的简单罗列
- Discussion 具有多层次的知识贡献阐释，而非 Results 的重述
- Abstract 是精准的"学术电梯演讲"，而非内容压缩
- 论文整体读起来像一个有张力的故事，而非一份报告

---

## 项目当前状态精准诊断

### 已有能力（前三轮累计）

| 维度 | 当前能力 | 能力深度 |
|------|---------|:-------:|
| 结构模板 | IMRaD + 7 种研究范式适配 | ⭐⭐⭐⭐ |
| 语言润色 | 非正式→正式词汇替换、基础 hedging | ⭐⭐ |
| 引用管理 | APA/GB-T/IEEE/BibTeX + API 验证 | ⭐⭐⭐⭐ |
| 统计分析 | 17 种统计动作 + APA 报告 | ⭐⭐⭐⭐ |
| 同行评审 | 模板化 Review Report | ⭐⭐⭐ |
| 期刊推荐 | 基于关键词的匹配 | ⭐⭐⭐ |
| 长文档管理 | 跨会话学位论文追踪 | ⭐⭐⭐ |
| 学科差异化 | 6 大学科基本规范 | ⭐⭐⭐ |

### 精确差距分析：从"合格"到"顶级"

| # | 缺失维度 | 影响 | 当前状态 | 顶级水平要求 |
|---|---------|------|---------|------------|
| 1 | **叙事架构** | 致命 | 零 — 完全缺失 | 论文是一个有起承转合的故事，不是报告 |
| 2 | **修辞动作** | 致命 | 零 — 完全缺失 | Introduction 的每一句话都是精密的修辞动作（CARS 模型） |
| 3 | **段落工艺** | 致命 | "每段一个观点" | 段落是精密的论证单元：主张→证据→分析→过渡 |
| 4 | **Discussion 深度** | 致命 | 3 个要点提示 | 多层解释：发现→机制→理论意义→实践启示→边界条件 |
| 5 | **Abstract 工艺** | 高 | 模板填空 | 精密的 6 句话电梯演讲，每句话有明确修辞功能 |
| 6 | **Title 工程** | 高 | "简洁即可" | 标题是高被引的第一驱动力，有明确设计原则 |
| 7 | **图表设计哲学** | 高 | 零 — 完全缺失 | 图表应能独立讲述论文故事 |
| 8 | **审稿人心理学** | 高 | 零 — 完全缺失 | 预判审稿人关注点，战略性预防反驳 |
| 9 | **贡献定位策略** | 高 | 列表式"我们的贡献" | 贡献嵌入学术传统，展示范式演进中的位置 |
| 10 | **信息密度控制** | 中 | 零 — 完全缺失 | 知道何时密集、何时留白，控制读者认知负荷 |
| 11 | **多轮写作策略** | 中 | 一次性生成 | 骨架→血肉→打磨→审视 的多轮迭代方法论 |
| 12 | **证据编排** | 中 | 零 — 完全缺失 | 将异质证据编织成统一论证的方法论 |

---

## 强化实施方案：12 项大师级写作手艺注入

### ===== 手艺 1：叙事架构引擎 =====

**在 `academic-writing/SKILL.md` 的 Phase 2 之前新增**

```markdown
### Phase 1.5: Narrative Architecture Design

**核心原则**: 每篇论文都是一个故事，具有主角（你的方法/发现）、对手（现有方法的局限）、冲突（未解决的问题）、和解决（你的贡献）。

#### Step 1.5.1: 构建叙事张力曲线

在动笔之前，设计论文的叙事弧线：

```
叙事张力
  ↑
  │         ┌─ 冲突高潮 ─┐
  │        /   (Gap最尖锐)  \
  │       /                  \──── 解决方案展开
  │      / 张力上升              \
  │     /  (现有方法不足)          \──── 验证与证实
  │    /                            \
  │   / 背景建立                      \── 意义升华
  │  /  (领域重要性)                    \
  │ /                                    ── 未来展望
  ──────────────────────────────────────────→ 论文进度
   Intro     Intro     Related   Method   Expt   Discussion
   §1.1      §1.2-3    Work
```

**叙事弧线四要素**:

| 要素 | 对应论文位置 | 核心问题 | 写作目标 |
|------|-----------|---------|---------|
| **建立** | Introduction §1.1 | 为什么这个领域重要？ | 让读者认同"这件事很重要" |
| **冲突** | Introduction §1.2-1.3 + Related Work | 现有方法为什么不够好？ | 让读者感到"确实需要新方案" |
| **解决** | Methodology + Experiments | 你怎么解决的？效果如何？ | 让读者相信"这个方案有效" |
| **升华** | Discussion + Conclusion | 这意味着什么？ | 让读者思考"这改变了我的理解" |

#### Step 1.5.2: 主线论证设计（Throughline）

一篇论文必须有一条贯穿始终的核心论点（Throughline），所有内容服务于这条主线：

**模板**:
> "尽管 [领域] 已经取得了 [进展]，但 [关键限制] 仍未解决，因为 [深层原因]。本文提出 [核心思想]，其关键洞察是 [insight]，实验表明 [主要结果]，这对 [更大图景] 具有 [意义]。"

**示例**:
> "尽管大语言模型在通用推理上取得了突破，但在需要精确数值计算的场景中表现不稳定，因为 Transformer 架构本质上是模式匹配器而非计算器。本文提出 CalcFormer，其关键洞察是将符号计算引擎嵌入注意力机制作为可微分模块，实验表明在 6 个数学推理基准上平均提升 23.7%，这揭示了神经-符号混合架构是突破 LLM 推理瓶颈的可行路径。"

**一致性检验**: 论文中每一个段落都应该能回答"这如何服务于主线论证？" 如果回答不了，该段落应被删除或重写。
```

### ===== 手艺 2：Swales CARS 模型驱动的 Introduction 写作 =====

**替换现有 Introduction Writing Formula**

```markdown
#### Introduction 修辞动作分析（基于 Swales CARS 模型）

顶级论文的 Introduction 不是随意写的，每一句话都是一个精密的**修辞动作（Rhetorical Move）**。按照 Swales 的 CARS（Create a Research Space）模型，Introduction 由三个动作组成：

**Move 1: 建立领地（Establishing a Territory）** — 通常占 Introduction 的 30-40%

| 步骤 | 修辞功能 | 语言模式 | 示例 |
|------|---------|---------|------|
| 1A: 声明重要性 | 让读者同意这个领域值得研究 | "X has become increasingly important..." / "X plays a crucial role in..." | "Large language models have fundamentally transformed natural language processing, achieving human-level performance across diverse benchmarks." |
| 1B: 概述现状 | 展示你熟悉该领域 | "Recent advances in X have shown..." / "Several approaches to X have been proposed..." | "Recent work has explored chain-of-thought prompting [1], tool augmentation [2], and retrieval-augmented generation [3]." |
| 1C: 综述前人工作 | 定位你的研究在知识图谱中的位置 | "Author (Year) demonstrated..." / "Building on [foundation], researchers have..." | — |

**Move 2: 建立利基（Establishing a Niche）** — 通常占 Introduction 的 20-30%

这是 Introduction 中**最关键的部分**，产生叙事张力的"转折点"：

| 步骤 | 修辞功能 | 语言模式 | 效果 |
|------|---------|---------|------|
| 2A: 反驳 | 指出前人工作的不足 | "However, these methods fail to..." / "Despite these advances, X remains..." | 最有力 — 直接指出问题 |
| 2B: 指出空白 | 指出未被探索的领域 | "Little research has addressed..." / "No prior work has considered..." | 常用 — 发现空白 |
| 2C: 提出问题 | 提出未回答的研究问题 | "An important question that arises is..." / "It remains unclear whether..." | 温和 — 引出问题 |
| 2D: 延续传统 | 自然延伸现有工作 | "Following this line of research..." | 最弱 — 适合增量工作 |

**关键技巧**: Move 2 的强度决定了论文的"兴奋感"。顶级论文几乎总是使用 2A（反驳）或 2B（空白），而非 2D（延续）。

**Move 3: 占领利基（Occupying the Niche）** — 通常占 Introduction 的 30-40%

| 步骤 | 修辞功能 | 语言模式 |
|------|---------|---------|
| 3A: 陈述目的 | 宣布本文做什么 | "In this paper, we propose..." / "This work introduces..." |
| 3B: 宣布发现 | 预告主要结果 | "We demonstrate that..." / "Our results show..." |
| 3C: 列出贡献 | 明确具体贡献 | "The key contributions are: (1)... (2)... (3)..." |
| 3D: 概述结构 | 论文路线图 | "The remainder of this paper is organized as follows..." |

**顶级 Introduction 的黄金比例**: Move 1 (35%) → Move 2 (25%) → Move 3 (40%)

**修辞动作标注练习**: 生成 Introduction 后，为每一句标注其修辞动作编号（如 M1-1A、M2-2A、M3-3C），确保覆盖所有必要动作，且排列顺序符合读者认知预期。
```

### ===== 手艺 3：段落工艺（Paragraph Craft） =====

```markdown
### Paragraph Architecture: The MEAL Plan

每个学术段落都应遵循 MEAL 结构——这是将段落从"信息堆砌"提升为"论证单元"的核心方法：

| 组件 | 全称 | 功能 | 典型长度 |
|------|------|------|---------|
| **M** | Main Point | 段落的核心论断（主题句） | 1 句 |
| **E** | Evidence | 支撑论断的具体证据 | 2-4 句 |
| **A** | Analysis | 对证据的分析/解释——为什么这个证据支持论断 | 1-3 句 |
| **L** | Link | 连接到下一段或回到主线论证 | 1 句 |

**关键区分**: "E"（证据）和"A"（分析）的区别是合格论文与顶级论文的分水岭。
- **合格论文**: "方法 X 在数据集 Y 上准确率达到 95%。"（只有 Evidence）
- **顶级论文**: "方法 X 在数据集 Y 上准确率达到 95%。这一结果超越了最强基线 12 个百分点，**表明** 将符号推理嵌入注意力机制显著增强了模型对精确计算的处理能力，**验证了**我们的核心假设——结构化知识的显式注入可以弥补纯统计学习在逻辑推理上的不足。"（Evidence + Analysis）

**段落长度指南**:
- 目标：150-250 词/段落（英文）
- 过短（<100 词）：论证不充分，考虑合并
- 过长（>300 词）：认知负荷过重，考虑拆分
- 每个段落应在去掉所有其他段落后仍然 self-contained

**段落间连接策略**:
- **逻辑递进**: "Building on this foundation, we further..."
- **对比转折**: "While the above approach addresses X, it does not account for..."
- **从一般到具体**: "More specifically, ..."
- **从具体到一般**: "This pattern reflects a broader phenomenon..."
- **时间顺序**: "Subsequently, ..." / "More recently, ..."

**禁止**: 段落之间的裸连接（两个段落之间没有任何逻辑桥梁直接跳转）
```

### ===== 手艺 4：Discussion 深度架构 =====

```markdown
### Discussion Section: The 5-Layer Model

Discussion 是论文中最难写的部分，也是审稿人评价"学术成熟度"的主要依据。采用五层模型：

**Layer 1: 核心发现重述（但不是重复 Results）**
- 不要重复数字，而是用更高层次的语言重述模式
- "Our results reveal a consistent pattern: X outperforms baselines most significantly in scenarios where [condition], suggesting that..."
- 长度：1-2 段

**Layer 2: 机制解释（Why does it work?）**
- 提供你的结果的因果解释或理论解释
- "We attribute this improvement to..." / "A plausible explanation is..."
- 将你的结果与已知理论/机制连接
- 如果能提出新的解释性假设，这是最有价值的贡献
- 长度：2-3 段

**Layer 3: 理论意义（What does this mean for the field?）**
- 将你的发现放入更大的学术图景中
- "This finding challenges the prevailing assumption that..." 
- "Our work provides empirical support for the theoretical conjecture by [Author]..."
- "This extends [Theory X] by showing it applies to [new domain]..."
- 贡献类型：验证/挑战/扩展/统一现有理论
- 长度：1-2 段

**Layer 4: 实践启示（What should practitioners do differently?）**
- 将学术发现转化为可操作建议
- "For practitioners designing X systems, our results suggest..."
- "These findings have direct implications for [application domain]..."
- 长度：1 段

**Layer 5: 局限性与边界条件（Honest but strategic）**
- 每个局限性都要跟一个"但是"（缓解因素或未来解决方向）
- "While our evaluation is limited to [scope], we note that [mitigation]..."
- 策略：将局限性转化为未来工作的路标
- 长度：1-2 段

**反模式检测** — Discussion 中以下情况是质量警告：
- ❌ 逐一重复 Results 中的数字
- ❌ 全部是"发现 X 与 Y 一致"而没有解释为什么
- ❌ 局限性是敷衍的一句话
- ❌ 没有连接到更大的理论图景
- ❌ 没有实践启示
```

### ===== 手艺 5：Abstract 精密工程 =====

```markdown
### Abstract Engineering: The 6-Sentence Model

顶级论文的 Abstract 不是论文的"压缩版"，而是独立的"学术电梯演讲"。采用 6 句模型：

| 句号 | 修辞功能 | 黄金模式 | 占比 |
|:---:|---------|---------|:---:|
| S1 | **语境建立** | 用一句有冲击力的事实/趋势建立 domain | 15% |
| S2 | **问题/空白** | 指出现有知识/方法的关键不足 | 15% |
| S3 | **本文做什么** | 一句话陈述核心贡献（"Here we show/propose...") | 15% |
| S4 | **怎么做的** | 核心方法/路径（仅关键创新点，不需所有细节） | 20% |
| S5 | **关键结果** | 最重要的 2-3 个量化结果 | 20% |
| S6 | **意义升华** | 对领域/应用的 broader impact | 15% |

**高影响力 Abstract 写作规则**:

1. **S1 的第一个词决定读者是否继续读** — 以具体事实或惊人数据开头，而非空洞的 "In recent years..."
   - ❌ "In recent years, deep learning has made significant progress..."
   - ✅ "Despite achieving superhuman performance on standard benchmarks, large language models still fail at elementary arithmetic."

2. **S3 必须使用强动词** — "We propose/introduce/present/develop"，而非 "This paper discusses/explores/looks at"

3. **S5 必须包含具体数字** — "improves accuracy by 23.7%" 而非 "significantly improves accuracy"

4. **S6 不要重复 S3** — 升华到更高层次：从"这个方法"到"这个发现对领域的意义"

5. **词数控制**: 150-250 词（遵循目标期刊要求），每个句子 25-35 词

**Title Engineering**:

标题是论文被引率的第一驱动力。设计原则：

| 原则 | 说明 | 示例 |
|------|------|------|
| **具体化** | 包含具体方法或发现 | ❌ "A New Approach to NLP" ✅ "Attention Is All You Need" |
| **张力感** | 暗示意外发现或挑战常识 | "Scaling Data-Constrained Language Models" |
| **方法+效果** | 既说做了什么也说达到了什么 | "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" |
| **命名法** | 给方法取一个令人记住的名字 | "BERT", "GPT", "ResNet", "Transformer" |
| **长度** | 10-15 词（会议常 < 12 词，期刊可稍长） | — |

**标题类型**:
- **声明型**: "Attention Is All You Need" — 最大胆，适合突破性工作
- **描述型**: "A Survey of Large Language Models" — 最安全
- **问题型**: "Can Machines Think?" — 引发好奇，适合观点型论文
- **方法:效果型**: "LoRA: Low-Rank Adaptation of Large Language Models" — 最常用于技术论文
```

### ===== 手艺 6：图表设计哲学 =====

```markdown
### Figure & Table Design Philosophy

**核心原则**: 读者应该仅通过浏览图表和标题就能理解论文的完整故事。

#### Figure Design Rules

1. **自解释性**: 每张图的 caption 必须包含足够信息让读者无需阅读正文就能理解
   - ❌ "Figure 1: System architecture."
   - ✅ "Figure 1: Architecture of CalcFormer. The symbolic computation engine (blue) is embedded as a differentiable module within each Transformer layer, enabling end-to-end training while preserving exact arithmetic capabilities."

2. **信息层次**: 
   - **Figure 1**: 总是 Architecture / Framework / Pipeline 总览图 — 给读者建立 mental model
   - **Figure 2-3**: 方法细节图（关键创新组件的放大图）
   - **Figure 4+**: 实验结果图（趋势、对比、分析）
   - **最后一张图**: 通常是 Case Study / Qualitative Analysis / Error Analysis

3. **颜色使用**:
   - 使用色盲友好的调色板（避免红/绿对比）
   - "我们的方法"用最醒目的颜色
   - 基线方法用低饱和度颜色
   - 保持全文颜色体系一致

4. **结果图选择**:
   - **比较表现**: Bar chart 或 Radar chart
   - **趋势分析**: Line chart（含误差带/CI）
   - **分布分析**: Box plot 或 Violin plot
   - **消融实验**: Grouped bar chart
   - **注意力/热力图**: Heatmap
   - **高维数据**: t-SNE / UMAP 散点图

#### Table Design Rules

1. **三线表是底线**: 顶线、中线（表头与数据之间）、底线
2. **最佳结果加粗**: `\textbf{91.3}` — 让读者一眼看到赢家
3. **次佳结果下划线**: `\underline{89.7}` — 展示你方法超越的幅度
4. **统计显著性标注**: 使用 * / ** / *** 或 †/‡ 符号，在 caption 中解释
5. **"Ours" 始终在最后一行**: 视觉上形成"落点"
6. **列对齐**: 数值右对齐，文本左对齐，居中用于类别标签
```

### ===== 手艺 7：审稿人心理学与战略性写作 =====

```markdown
### Reviewer Psychology & Preemptive Writing

#### 审稿人的 10 分钟决策

研究表明，审稿人通常在阅读 Abstract + Introduction + 扫视 Figures/Tables 的前 10 分钟内已形成 70% 的判断。因此：

1. **前 3 页决定命运**: Introduction 的质量比 Results 更影响审稿结果
2. **图表是快速判断的锚点**: 审稿人会先扫视所有图表再细读文字
3. **贡献列表是最先被审视的**: 审稿人会拿贡献列表与实验对照

#### 审稿人常见拒稿理由与预防策略

| 拒稿理由 | 占比 | 预防写作策略 |
|---------|:---:|------------|
| "增量贡献" | ~35% | 在 Introduction 中明确展示与最强基线的本质区别（不仅是性能提升，还有方法论创新）。使用 "Unlike..." 句式 |
| "实验不充分" | ~25% | 提前包含消融实验、统计检验、多数据集验证。在 Experiments 开头设置 "Research Questions"（RQ1/RQ2/RQ3） |
| "写作不清晰" | ~15% | 每节开头有 overview sentence，每段有 topic sentence，每处公式后有直觉解释 |
| "动机不充分" | ~10% | Move 2（建立利基）必须有具体的失败案例或量化证据，而不仅是"X 还没被研究" |
| "缺乏理论深度" | ~10% | Discussion 必须包含 Layer 3（理论意义），将发现连接到已知理论框架 |
| "相关工作不全" | ~5% | 使用 `literature-review` 技能做系统搜索，确保覆盖最近 2 年的关键工作 |

#### 预防性写作技术

**"Steel Man" 策略**: 在 Discussion 中主动呈现对你方法最强的质疑，然后用证据回应：
> "One might argue that the improvement stems from [alternative explanation] rather than [our claimed mechanism]. However, our ablation study (Table 4) demonstrates that removing [key component] while maintaining [confound] leads to a [X%] performance drop, ruling out this alternative explanation."

**"Bridge" 策略**: 在相关工作中，为每个最接近的竞争方法写一句明确的区分：
> "While [Competitor] also addresses [problem], their approach assumes [limitation], which does not hold in [scenario]. Our method removes this assumption by [key difference]."
```

### ===== 手艺 8：贡献定位策略 =====

```markdown
### Contribution Positioning Framework

贡献不是写在 bullet list 里的功能描述，而是学术话语体系中对知识推进的精确定位。

#### 贡献类型分类

| 类型 | 定义 | 适用场景 | 动词选择 |
|------|------|---------|---------|
| **开创型** | 定义新问题/开辟新领域 | 极少，影响巨大 | "We introduce the first..." |
| **突破型** | 在已知问题上实现质的飞跃 | 重大改进（>20%） | "We achieve state-of-the-art..." |
| **统一型** | 将多个分散的方法/理论统一 | 综合框架 | "We unify... under a common framework" |
| **迁移型** | 将 A 领域的成功方法引入 B | 跨领域应用 | "We adapt... to the new domain of..." |
| **深化型** | 深入理解已有现象的机制 | 分析/解释 | "We provide the first theoretical analysis of..." |
| **工具型** | 提供新工具/数据集/基准 | 资源贡献 | "We release... enabling future research on..." |

#### 贡献陈述写作原则

1. **每个贡献必须是可验证的**: "We propose X" → 在 Methods 中描述。"We demonstrate Y" → 在 Results 中证明。
2. **贡献数量**: 3 个是最佳数量（心理学上容易记忆），最多 4 个。
3. **贡献排序**: 最重要的方法论贡献放第一，实验验证放最后。
4. **贡献粒度**: 每个贡献应该独立有价值——如果去掉其中一个，论文仍然有意义。
5. **措辞精准**: 避免"We study X"（太弱）；使用"We propose / introduce / develop / demonstrate / establish"。
```

### ===== 手艺 9：元话语系统（Metadiscourse） =====

```markdown
### Metadiscourse: Guiding Your Reader

元话语（Metadiscourse）是作者用来组织文本、引导读者、表达态度的语言标记。顶级论文大量使用元话语，而合格论文往往不足。

#### 文本组织型元话语（Textual Metadiscourse）

| 类型 | 功能 | 示例 |
|------|------|------|
| **路标词** | 告诉读者你要去哪里 | "In this section, we first describe... then present... finally discuss..." |
| **框架词** | 标记文本结构 | "First... Second... Third..." / "To begin with... Moving on to..." |
| **回指词** | 连接已讨论的内容 | "As mentioned above..." / "Recall that in Section 2, we defined..." |
| **前指词** | 预告即将讨论的内容 | "As we shall see in Section 5..." / "We return to this point below." |
| **主题词** | 标记话题切换 | "Turning now to..." / "With regard to..." / "As for..." |

#### 态度型元话语（Interpersonal Metadiscourse）

| 类型 | 功能 | 示例 |
|------|------|------|
| **Hedges** | 软化确定性 | "may", "might", "suggests", "appears to", "it is possible that" |
| **Boosters** | 强化确定性 | "clearly", "obviously", "undoubtedly", "we are confident that" |
| **态度标记** | 表达评价 | "importantly", "interestingly", "surprisingly", "notably" |
| **读者介入** | 拉近与读者的距离 | "Note that...", "It is worth noting that...", "Consider the case where..." |
| **自我提及** | 作者存在感 | "We argue that...", "Our approach...", "In our view..." |

**使用密度指南**:
- **Introduction**: 高密度路标词 + 中等 hedges
- **Methods**: 低元话语密度（客观描述为主）
- **Results**: 中等密度 boosters（"clearly outperforms"）+ hedges（"suggests"）
- **Discussion**: 最高密度——大量 hedges + 态度标记 + 读者介入

**常见错误**:
- ❌ 过度使用 hedges → 显得不自信 → "may possibly suggest that it might..."
- ❌ 过度使用 boosters → 显得傲慢 → "clearly and undoubtedly proves..."
- ❌ 没有路标词 → 读者迷失方向
- ✅ 平衡使用：在有强证据时用 boosters，在推测时用 hedges
```

### ===== 手艺 10：信息密度控制 =====

```markdown
### Information Density Control

顶级论文的信息密度不是均匀的，而是有节奏的——像呼吸一样，有密集区和留白区。

**密度地图**:

| 论文区域 | 信息密度 | 读者状态 | 写作策略 |
|---------|:-------:|---------|---------|
| Abstract | ██████████ 极高 | 快速评估 | 每词都有信息量，零冗余 |
| Introduction §1 | ████████░░ 高 | 建立兴趣 | 快速铺陈背景，不展开细节 |
| Introduction §2-3 | ██████████ 极高 | 判断价值 | 精确陈述 gap 和贡献 |
| Related Work | ██████░░░░ 中 | 评估覆盖度 | 概括而非详述，重在比较 |
| Method Overview | ████████░░ 高 | 建立理解 | 先给直觉再给公式 |
| Method Details | ██████████ 极高 | 深入理解 | 公式 + 解释 + 伪代码 |
| Experiments Setup | ██████░░░░ 中 | 评估严谨性 | 清晰但简洁 |
| Results | ████████░░ 高 | 验证贡献 | 数据密集 + 简短分析 |
| Discussion | ██████░░░░ 中 | 思考意义 | 留给读者思考的空间 |
| Conclusion | ████████░░ 高 | 带走记忆 | 核心贡献 + 前瞻，不引入新内容 |

**"直觉先行"原则**: 在给出任何公式/算法之前，先用一句自然语言解释核心直觉：
> "Intuitively, our method works by treating each token as a query to an external symbolic calculator. Formally, given input sequence $x_1, ..., x_n$, we define..."
```

### ===== 手艺 11：多轮写作策略 =====

```markdown
### Multi-Draft Writing Strategy

不要试图一次性写出完美论文。采用四轮写作法：

**Round 1 — 骨架稿（Skeleton Draft）** [信息完整性优先]
- 写出所有节的主题句
- 列出所有关键论点
- 插入所有表格/图表的占位符
- 标注所有需要引用的位置为 [REF]
- 目标：30% 的最终长度

**Round 2 — 血肉稿（Flesh Draft）** [内容充实性优先]
- 将骨架扩展为完整段落（MEAL 结构）
- 填入具体数据、证据、引用
- 编写所有公式和算法
- 目标：90% 的最终长度

**Round 3 — 打磨稿（Polish Draft）** [语言质量优先]
- 逐段检查修辞动作是否完整
- 应用元话语系统——添加路标词、hedges、boosters
- 检查段落间过渡是否顺畅
- 统一术语和记号
- 检查图表 caption 自解释性

**Round 4 — 审视稿（Scrutiny Draft）** [审稿人视角]
- 用 Phase 6 的自审清单逐项检查
- 模拟同行评审（Phase 6.2）
- 检查每个贡献是否有对应的实验验证
- 检查 Abstract 是否独立可理解
- 检查标题是否最优
```

### ===== 手艺 12：证据编排方法论 =====

```markdown
### Evidence Orchestration

一个论证通常需要多种类型的证据协同支撑。顶级论文善于编排异质证据。

**证据类型及其说服力层级**:

| 层级 | 证据类型 | 说服力 | 示例 |
|:---:|---------|:-----:|------|
| 1 | 数学证明 | ★★★★★ | 定理证明、收敛性分析 |
| 2 | 大规模实验 | ★★★★☆ | 多数据集、多指标、统计检验 |
| 3 | 消融实验 | ★★★★☆ | 逐一去除组件，验证必要性 |
| 4 | 对比实验 | ★★★☆☆ | 与 SOTA 基线比较 |
| 5 | Case Study | ★★★☆☆ | 典型案例定性分析 |
| 6 | 可视化证据 | ★★☆☆☆ | 注意力图、t-SNE、热力图 |
| 7 | 类比论证 | ★★☆☆☆ | "类似于 X 领域的 Y..." |
| 8 | 权威引用 | ★☆☆☆☆ | "[Author] also argues that..." |

**编排原则**:
1. **三角验证**: 对于核心论断，至少使用 3 种不同类型的证据支撑
2. **强弱交替**: 先给强证据（实验数据），再辅以解释性证据（case study）
3. **预防性证据**: 在审稿人可能质疑的地方预先放置反驳证据（消融实验）
4. **级联论证**: 小结论 A + 小结论 B → 支撑大论断 C（避免单点依赖）
```

---

## 实施方式

### 所有内容的实施位置

| # | 手艺名称 | 实施位置 | 方式 |
|---|---------|---------|------|
| 1 | 叙事架构引擎 | `academic-writing/SKILL.md` Phase 1.5 | 在 Phase 1 后插入 |
| 2 | CARS Introduction | `academic-writing/SKILL.md` Phase 2 Step 2.1 | 替换 Introduction Writing Formula |
| 3 | 段落工艺 MEAL | `academic-writing/SKILL.md` Phase 2 | 在 Step 2.1 前插入 |
| 4 | Discussion 五层模型 | `academic-writing/SKILL.md` Phase 2 Step 2.1 | 在 Results 后新增 Discussion 指南 |
| 5 | Abstract 6 句模型 + Title 工程 | `academic-writing/SKILL.md` Phase 2 Step 2.2 | 替换现有 Abstract 模板 |
| 6 | 图表设计哲学 | `academic-writing/SKILL.md` Phase 3.5 后 | 新增 Phase 3.7 |
| 7 | 审稿人心理学 | `academic-writing/SKILL.md` Phase 6 前 | 新增 Phase 5.5 |
| 8 | 贡献定位策略 | `academic-writing/SKILL.md` Phase 1.5 后 | 在 Phase 2 前插入 |
| 9 | 元话语系统 | `academic-writing/SKILL.md` Phase 3 | 在 Step 3.1 后新增 Step 3.1.5 |
| 10 | 信息密度控制 | `academic-writing/SKILL.md` Phase 2 | 在 Phase 2 开头插入总纲 |
| 11 | 多轮写作策略 | `academic-writing/SKILL.md` Phase 2 前 | 在 Phase 1.5 后插入 |
| 12 | 证据编排 | `academic-writing/SKILL.md` Phase 2 Step 2.1 | 在 Results 部分后新增 |

### Lead Agent 提示词配套增强

在 `<academic_research>` 段落中新增第 8 条规则：

```
**8. Master-Level Writing Craft (Always Apply for Paper Writing)**

When generating academic manuscript content, go beyond template-filling:
- Apply narrative architecture (tension curve from gap to resolution)
- Use CARS model rhetorical moves in every Introduction
- Build every paragraph as a MEAL unit (Main point → Evidence → Analysis → Link)
- Apply the 5-Layer Discussion model (findings → mechanisms → theory → practice → limits)
- Engineer the Abstract as a 6-sentence elevator pitch
- Design titles for maximum citation impact
- Control information density rhythmically across sections
- Preemptively address likely reviewer concerns
- Position contributions within the field's intellectual evolution
- Orchestrate multiple evidence types for triangulated arguments
```

---

## 质量验证标准

实施后，使用以下测试用例验证效果：

**测试 1**: 输入"帮我写一篇关于 LLM 数学推理能力的研究论文 Introduction"
- 验证：输出是否包含清晰的 CARS 三个 Move？Move 2 的张力是否足够？
- 验证：是否有叙事弧线的张力上升？

**测试 2**: 输入"帮我写这篇论文的 Discussion"（基于测试 1 的上下文）
- 验证：输出是否覆盖五层模型？是否有理论意义层？
- 验证：局限性是否每个都跟了缓解策略？

**测试 3**: 输入"帮我生成这篇论文的 Abstract 和 Title"
- 验证：Abstract 是否符合 6 句模型？S1 是否以具体事实开头？S5 是否有具体数字？
- 验证：Title 是否遵循了某种设计原则（方法:效果型/声明型）？

---

## 约束条件

1. 所有修改仅涉及 `skills/public/academic-writing/SKILL.md` 和 `backend/src/agents/lead_agent/prompt.py`——不修改 Python 运行时代码
2. SKILL.md 总长度不超过 2000 行（当前 846 行，可用空间约 1150 行）
3. 新增内容必须以示例驱动，而非纯理论阐述——每个手艺至少附带 1 个具体写作示例
4. 所有修辞学术语（CARS、MEAL、Metadiscourse）必须在首次出现时解释其含义
5. 保持与已有 Phase 编号体系的兼容性
