---
name: academic-writing
description: Use this skill when the user wants to write, draft, or revise academic papers, theses, dissertations, or any scholarly manuscript. Covers the full academic writing lifecycle including topic refinement, IMRaD structure generation, LaTeX/Markdown formatting, abstract writing, keyword extraction, academic language polishing, logical coherence checking, and submission preparation (cover letter, rebuttal, formatting compliance). Trigger on queries like "write a paper", "draft a thesis", "help me with my manuscript", "polish my academic writing", "prepare for submission", or any request involving scholarly writing.
---

# Academic Writing Skill

## Overview

This skill provides a comprehensive methodology for producing high-quality academic manuscripts. It covers the entire lifecycle from topic refinement to submission preparation, following established scholarly conventions across disciplines (STEM, Social Sciences, Humanities).

## When to Use This Skill

**Always load this skill when:**

- User wants to write, draft, or structure an academic paper
- User needs help with thesis/dissertation writing
- User asks for academic language polishing or revision
- User wants to generate an abstract, introduction, or related work section
- User needs LaTeX or academic Markdown formatting
- User is preparing a manuscript for journal/conference submission
- User needs a cover letter, rebuttal letter, or response to reviewers

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Structure Generation** | IMRaD, thesis chapters, review paper structure |
| **Abstract Writing** | Structured (Background-Methods-Results-Conclusion) and unstructured |
| **LaTeX Formatting** | Full LaTeX document generation with BibTeX references |
| **Academic Polishing** | Formal tone, hedging language, passive voice where appropriate |
| **Citation Integration** | BibTeX, APA 7th, GB/T 7714-2015, IEEE, Vancouver |
| **Formula Support** | LaTeX math equations inline and display mode |
| **Table Formatting** | Three-line tables (学术三线表), comparison tables |
| **Keyword Extraction** | Automatic keyword suggestion from manuscript content |
| **Submission Prep** | Cover letter, highlights, graphical abstract description |

## Workflow

### Phase 0: Research Paradigm Detection & Adaptation

Before generating any content, identify the user's research paradigm to adapt structure and writing strategy.

#### Step 0.1: Identify Research Paradigm

Analyze the user's request to detect the paradigm:
1. **User's explicit statement** ("I'm doing a qualitative study...")
2. **Research question type** (causal → quantitative, exploratory → qualitative)
3. **Data type** (numerical → quantitative, text/interview → qualitative)
4. **Discipline conventions** (CS → design science/empirical, Sociology → qualitative/mixed)

#### Step 0.2: Paradigm-Specific Adaptations

**Quantitative Empirical Research**:
- Structure: Strict IMRaD with Hypotheses subsection
- Required sections: Research Model/Framework figure, Variable Operationalization table
- Methods must include: Sample size justification (power analysis), Validity & Reliability measures
- Results: Statistical tables (three-line), effect sizes, confidence intervals
- Discussion: Support/reject hypotheses, practical vs. statistical significance

**Design Science Research (DSR)**:
- Structure: Problem → Objectives → Design → Development → Demonstration → Evaluation → Communication
- Required: Design Requirements table, Artifact Description, Evaluation Framework
- Must reference: Hevner et al. (2004) guidelines, Peffers et al. (2007) process
- Evaluation: Formative + Summative, utility demonstration

**Systematic Review / Meta-Analysis**:
- Structure: PRISMA-compliant (use `literature-review` skill Phase 5)
- Required: PRISMA flow diagram, Search strategy table (per database), Quality assessment
- Synthesis: Narrative synthesis or statistical meta-analysis (forest plot, heterogeneity I²)
- Registration: Mention PROSPERO registration (if applicable)

**Qualitative Research**:
- Structure: Flexible — Introduction → Literature → Methodology → Findings → Discussion
- Methods: Data collection (interviews/observation/documents), Coding strategy (open/axial/selective), Trustworthiness criteria (credibility, transferability, dependability, confirmability)
- Findings: Theme-based with thick description and participant quotes
- Reflexivity: Researcher positionality statement

**Mixed Methods Research**:
- Specify design type: Convergent, Explanatory Sequential, Exploratory Sequential
- Joint display table for QUAL + QUAN integration
- Meta-inferences section for integrated findings
- Clearly separate quantitative and qualitative strands in Methods

**Case Study Research**:
- Framework: Yin (2018) — single/multiple/embedded case design
- Required: Case selection rationale, Unit of analysis definition
- Data: Multiple evidence sources (documents, interviews, observations)
- Analysis: Pattern matching, explanation building, cross-case synthesis

**Review/Survey Paper** — First identify the specific review type:

| Type | Methodology | Structure |
|------|------------|-----------|
| **Narrative Review** | Expert-driven thematic synthesis | Intro → Themes → Synthesis → Future |
| **Systematic Review** | PRISMA protocol, reproducible search | Protocol → Search → Screen → Assess → Synthesize |
| **Scoping Review** | PRISMA-ScR, broad mapping | Protocol → Search → Charting → Mapping |
| **Meta-Analysis** | Statistical pooling of effect sizes | Systematic Review + Forest plot + Heterogeneity |
| **Critical Review** | Argumentative, author's viewpoint | Argument → Evidence → Counter-evidence → Synthesis |
| **Mapping/Survey** (CS) | Taxonomy + comparison table | Taxonomy → Categories → Comparison → Challenges |
| **Tutorial Review** | Pedagogical, foundational | Foundations → Building blocks → Advanced → Practice |

Detect type from user's request and apply corresponding methodology. All review types require: classification framework figure, comparison table, and actionable future directions.

### Phase 1: Topic Refinement & Outline

#### Step 1.1: Understand the Research Context

When a user requests academic writing, gather:

| Information | Description | Required |
|------------|-------------|----------|
| **Research Topic** | The specific topic or research question | Yes |
| **Paper Type** | Research article, review, thesis chapter, conference paper, etc. | Yes |
| **Target Venue** | Journal name, conference, or degree program | Recommended |
| **Discipline** | CS, Biology, Economics, Engineering, etc. | Recommended |
| **Key Findings** | Main results or arguments to present | For drafting |
| **Existing Materials** | Data, figures, prior drafts, references | Optional |

#### Step 1.2: Generate Paper Outline

Based on the paper type, generate an appropriate structure:

**Research Article (IMRaD):**
```markdown
# [Paper Title]

## Abstract
[Structured: Background → Objective → Methods → Results → Conclusion]

## 1. Introduction
### 1.1 Background and Motivation
### 1.2 Research Gap
### 1.3 Contributions
### 1.4 Paper Organization

## 2. Related Work
### 2.1 [Theme 1]
### 2.2 [Theme 2]
### 2.3 Summary and Positioning

## 3. Methodology
### 3.1 Problem Formulation
### 3.2 Proposed Approach
### 3.3 Implementation Details

## 4. Experiments
### 4.1 Experimental Setup
### 4.2 Datasets and Baselines
### 4.3 Results and Analysis
### 4.4 Ablation Study

## 5. Discussion
### 5.1 Key Findings
### 5.2 Limitations
### 5.3 Future Work

## 6. Conclusion

## References
```

**Review/Survey Paper:**
```markdown
# [Survey Title]

## Abstract

## 1. Introduction
### 1.1 Scope and Motivation
### 1.2 Survey Methodology
### 1.3 Paper Organization

## 2. Taxonomy and Classification
### 2.1 Classification Criteria
### 2.2 Category Overview

## 3-N. [Thematic Sections]
### N.1 Overview
### N.2 Representative Methods
### N.3 Comparison and Analysis

## N+1. Open Challenges and Future Directions

## N+2. Conclusion

## References
```

**Thesis/Dissertation Chapter:**
```markdown
# Chapter N: [Title]

## N.1 Introduction
## N.2 Literature Review
## N.3 Theoretical Framework / Methodology
## N.4 Analysis / Implementation
## N.5 Results
## N.6 Discussion
## N.7 Summary
```

### Phase 1.2.5: Taxonomy Design (for Review Papers)

The taxonomy is the CORE intellectual contribution of a survey. Design process:

1. **Open coding**: Tag each paper with descriptive labels (bottom-up)
2. **Axial coding**: Group labels into categories → subcategories
3. **Selective coding**: Identify 2-3 independent organizing dimensions
4. **Validate**: Every paper fits exactly one cell; no orphans

**Quality criteria**: MECE (Mutually Exclusive, Collectively Exhaustive), meaningful dimensions (real conceptual differences), balanced granularity (not too broad/fine).

**Common structures**: By method ("attention: self/cross/sparse"), by problem ("NLP tasks: classification/generation/QA"), by data ("learning: supervised/self-supervised"), multi-dimensional matrix (method × domain), temporal ("gen 1→2→3: rule→statistical→neural").

The taxonomy FIGURE is the most important visual — it becomes the reader's mental map of the field.

### Phase 1.5: Narrative Architecture Design

Every top paper tells a compelling story with narrative tension. Before drafting, design the narrative arc.

#### Step 1.5.1: Design Narrative Tension Curve

Map your paper's tension arc — the reader's engagement should rise through the Introduction, peak at the Gap/Contribution, sustain through Methods/Results, and resolve with deeper understanding in Discussion:

- **Establishing** (Intro §1.1): Why this area matters → reader agrees "this is important"
- **Rising tension** (Intro §1.2-1.3 + Related Work): Why existing solutions are insufficient → reader feels "we need a new approach"
- **Resolution** (Methods + Experiments): How you solve it and proof it works → reader believes "this works"
- **Elevation** (Discussion + Conclusion): What this means for the bigger picture → reader thinks "this changes my understanding"

#### Step 1.5.2: Define the Throughline

Every paper must have ONE core argument (throughline) that all content serves. Formulate it before writing:

> "Although [field] has achieved [progress], [key limitation] remains because [root cause]. We propose [core idea], whose key insight is [insight], demonstrating [main result], which reveals [broader implication]."

**Consistency test**: Every paragraph should answer "How does this serve the throughline?" If it cannot, the paragraph should be cut or rewritten.

### Phase 1.6: Contribution Positioning

Contributions are not feature descriptions — they are precise claims about knowledge advancement.

**Contribution Types** (choose the most accurate):

| Type | Definition | Verb Pattern |
|------|-----------|-------------|
| **Pioneering** | Defines a new problem or opens a new area | "We introduce the first..." |
| **Breakthrough** | Achieves a qualitative leap on a known problem | "We achieve state-of-the-art..." |
| **Unifying** | Unifies disparate methods under a common framework | "We unify... under..." |
| **Transferring** | Brings a method from domain A to domain B | "We adapt... to..." |
| **Deepening** | Provides mechanistic understanding | "We provide the first theoretical analysis of..." |
| **Enabling** | Releases a new tool, dataset, or benchmark | "We release... enabling..." |

**Rules**: (1) Each contribution must be verifiable in the paper. (2) 3 contributions is optimal, 4 maximum. (3) Order by importance: methodological first, experimental last. (4) Use strong verbs: "propose/introduce/develop/demonstrate/establish", never "study/explore/look at".

### Phase 1.6.5: Precision of Scope

Top papers are precise about what they claim AND what they do not claim. This separates confident science from overclaiming.

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
- "We solve the problem of X" → "We advance the state of X by [specific amount/way]"
- "This proves that X" → "This provides strong evidence that X" (unless mathematical proof)
- "For the first time ever" → "To the best of our knowledge, this is the first [specific claim]"
- "Our method is superior" → "Our method outperforms baselines on [specific metrics] under [specific conditions]"

### Phase 1.7: Multi-Draft Writing Strategy

Do not attempt to produce a perfect paper in one pass. Follow the four-round approach:

| Round | Focus | Target | What to produce |
|:-----:|-------|:------:|----------------|
| **1 — Skeleton** | Completeness | 30% length | Topic sentences for all sections, table/figure placeholders, [REF] markers |
| **2 — Flesh** | Content | 90% length | Full MEAL paragraphs, data, citations, formulas, algorithms |
| **3 — Polish** | Language | 100% length | Metadiscourse markers, transitions, hedging, terminology consistency |
| **4 — Scrutiny** | Reviewer's eye | Final | Self-review checklist (Phase 6), contribution-experiment alignment, abstract-body consistency |

### Phase 2: Content Drafting

#### Review-Specific Writing (for Review/Survey Papers)

**Phase 2.0.5: Review Writing Patterns**

Three paragraph patterns unique to reviews:

**Comparative**: "Both [A] and [B] address [problem]. [A] uses [method 1] achieving [result 1], while [B] uses [method 2] achieving [result 2]. Despite different approaches, both share [commonality]. However, neither addresses [gap]."

**Evolutionary**: "Early work by [Author, Year] established [foundation]. [Author, Year] extended this via [extension]. A shift occurred when [Author, Year] demonstrated [breakthrough], challenging [old assumption]. Current approaches [state], but [remaining challenge]."

**Tension**: "A key debate concerns [tension]. [Camp A] argues [position] based on [evidence]. [Camp B] contends [counter-position] based on [counter-evidence]. Recent work by [Author] suggests [potential resolution]."

**"Big Claim" technique**: Open each major section with a bold synthetic claim, then support it. Example: "The shift from feature engineering to end-to-end learning has been the single most transformative change in NLP."

**Phase 2.1.5: Knowledge Synthesis Strategies**

Don't list papers — SYNTHESIZE knowledge into higher-order insights:

| Mode | Pattern | When |
|------|---------|------|
| **Aggregative** | "N studies found X. M found Y. The balance supports X." | Systematic reviews |
| **Configurative** | "While [Group A] approaches X from [angle], [Group B] emphasizes [alt]. Together these suggest [framework]." | Conceptual reviews |
| **Comparative** | "Method A excels in [X] but fails in [Y]; Method B shows the opposite. This reveals [trade-off]." | Technical surveys |
| **Evolutionary** | "The field began with [paradigm 1], challenged by [finding], leading to [paradigm 2]." | Historical reviews |

**"So What?" test**: After every paragraph, ask "So what does this mean for the field?" If no answer → you're describing, not synthesizing.

**Phase 2.1.7: Temporal Evolution Narrative**

For reviews tracing a field's development, use the Paradigm Evolution pattern:

Origins ("The Seed": first formulation) → Foundations ("The Framework": accepted approaches) → Growth ("Expansion": extensions and applications) → Crisis ("The Challenge": failures/anomalies) → Revolution ("The Shift": new paradigm) → Current ("The Frontier": open questions)

Use timeline markers and transition triggers between eras. Map the "intellectual family tree" using `literature-review` citation tracing.

**Phase 2.2.5: Critical Appraisal**

Top reviews JUDGE, not just describe. For each body of work evaluate: internal validity (causal claims justified?), external validity (generalizable?), methodological rigor (appropriate tests? adequate N?), reproducibility (data/code available?).

**Strength-of-Evidence ratings**: Strong (multiple consistent studies + strong methods) / Moderate (some studies, methodological limits) / Preliminary (single study or inconsistent) / Insufficient (no rigorous evidence).

Diplomatic language: "While [study] makes an important contribution, its reliance on [limitation] restricts generalizability."

**Phase 2.3.5: Systematic Gap Identification**

Use the 5-type framework:

| Gap Type | How to Identify | Example |
|----------|----------------|---------|
| **Methodological** | Compare methods across studies | "No work applies causal inference to this association" |
| **Theoretical** | Look for unexplained findings | "Current theories cannot account for [pattern]" |
| **Empirical** | Check population coverage | "Studies focus on English; [language] unexplored" |
| **Application** | Cross-reference methods × domains | "Technique X proven in [A] but untested in [B]" |
| **Integration** | Map citation networks for missing bridges | "Research on [A] and [B] developed independently despite synergies" |

Visualize gaps as a matrix (methods × applications) with "well-studied" / "emerging" / "GAP" cells.

**Phase 2.4.5: Actionable Future Research Agenda**

Each direction must specify: (1) specific testable question, (2) rationale connected to identified gap, (3) feasible approach, (4) expected impact.

Structure as: Short-term (1-2 yr, immediately feasible) → Medium-term (3-5 yr, new methods needed) → Long-term (5+ yr, may reshape field).

Anti-patterns: ❌ "More research is needed" ❌ "Future work could use larger datasets". ✅ "The absence of [evidence] leaves unresolved whether [mechanism] holds under [conditions]. A [study type] measuring [outcome] in [context] would directly test this."

#### Information Density Control

Information density should vary rhythmically across the paper — like breathing, with dense and sparse zones:

| Section | Density | Reader State | Strategy |
|---------|:-------:|-------------|----------|
| Abstract | Extreme | Quick scan | Zero redundancy, every word carries meaning |
| Introduction §1 | High | Building interest | Rapid context setup, no tangential detail |
| Introduction §2-3 | Extreme | Judging value | Precise gap statement and contributions |
| Related Work | Medium | Assessing coverage | Summarize, don't elaborate; focus on contrasts |
| Method Overview | High | Building mental model | **Intuition first, then formalism** |
| Method Details | Extreme | Deep comprehension | Formulas + explanations + pseudocode |
| Experiment Setup | Medium | Checking rigor | Clear but concise |
| Results | High | Validating claims | Data-dense + brief analysis |
| Discussion | Medium | Reflecting on meaning | Give the reader breathing room to think |
| Conclusion | High | Taking away memory | Core contributions + outlook, no new info |

**"Intuition-First" principle**: Before ANY formula or algorithm, provide one sentence of natural-language intuition:
> "Intuitively, our method treats each token as a query to an external calculator. Formally, given input $x_1, ..., x_n$, we define..."

#### Step 2.0: Paragraph Architecture (MEAL Plan)

Every academic paragraph must be a self-contained argumentation unit following the MEAL structure:

| Component | Name | Function | Length |
|:---------:|------|----------|:------:|
| **M** | Main Point | The paragraph's core claim (topic sentence) | 1 sentence |
| **E** | Evidence | Specific data, citations, or examples supporting the claim | 2-4 sentences |
| **A** | Analysis | WHY the evidence supports the claim — this is what separates top papers from average ones | 1-3 sentences |
| **L** | Link | Connection to the next paragraph or back to the throughline | 1 sentence |

**The E→A distinction is critical**:
- Evidence only: "Method X achieves 95% accuracy on dataset Y."
- Evidence + Analysis: "Method X achieves 95% accuracy on dataset Y, surpassing the strongest baseline by 12 points. This substantial margin **suggests** that embedding symbolic reasoning into the attention mechanism significantly enhances numerical computation, **supporting** our hypothesis that explicit structural knowledge can compensate for the inherent limitations of purely statistical learning."

**Paragraph guidelines**: Target 150-250 words. Below 100 = underdeveloped (consider merging). Above 300 = cognitive overload (consider splitting). Each paragraph should be self-contained even when read in isolation.

**Transition strategies between paragraphs**:
- Logical progression: "Building on this foundation, ..."
- Contrast: "While the above addresses X, it does not account for..."
- General→specific: "More specifically, ..."
- Specific→general: "This pattern reflects a broader phenomenon..."

#### Step 2.1: Write Section by Section

For each section, follow the master-level writing principles below.

**Introduction Writing: Swales CARS Model (Create a Research Space)**

Top-tier Introductions are not written intuitively — every sentence serves a precise rhetorical function. Follow the three Moves:

**Move 1 — Establishing a Territory** (~35% of Introduction):
- Step 1A: Claim importance — "X has become increasingly critical for..." / "X plays a pivotal role in..."
- Step 1B: Survey the landscape — "Recent advances have demonstrated..." / "Several approaches have been proposed [1-5]..."
- Step 1C: Review prior contributions — position key works with evaluation, not just listing

**Move 2 — Establishing a Niche** (~25% — the MOST critical part, creates narrative tension):
- 2A Counter-claiming (strongest): "However, these methods fundamentally fail when..." / "Despite these advances, X remains an open challenge because..."
- 2B Gap-indicating: "Little research has addressed the critical issue of..."
- 2C Question-raising: "An important question that remains unanswered is..."
- Top papers almost always use 2A (counter-claim) or 2B (gap), never 2D (continuing tradition)

**Move 3 — Occupying the Niche** (~40% of Introduction):
- 3A Purpose: "In this paper, we propose / introduce..."
- 3B Findings preview: "We demonstrate that..." / "Our results show..."
- 3C Contributions list: "The key contributions are: (1)... (2)... (3)..."
- 3D Structure overview: "The remainder is organized as follows..."

**Self-check**: After writing, annotate each sentence with its Move (M1-1A, M2-2A, M3-3C, etc.) to verify complete coverage and correct ordering.

**Nature/Science Opening: The Intellectual Contract**

When targeting Nature/Science/Cell/PNAS or equivalent top venues, use this opening INSTEAD of standard CARS. The Intellectual Contract promises the reader a cognitive shift within the first paragraph:

1. **The Established Truth** (1 sentence): State something the field believes to be true.
   > "The ability of large language models to generate fluent text has led to the widespread assumption that these models possess genuine language understanding."

2. **The Crack** (1 sentence): A devastating challenge to that established truth.
   > "Here we show that this assumption is fundamentally flawed: models achieving near-perfect scores on comprehension benchmarks fail systematically when questions are rephrased using logically equivalent but syntactically unfamiliar structures."

3. **The Stakes** (1 sentence): Why this crack matters.
   > "This finding has profound implications for deploying LLMs in safety-critical applications where robust understanding, not pattern matching, is required."

4. **The Resolution Preview** (1-2 sentences): What this paper does — at the level of insight, not method.
   > "By developing an evaluation framework grounded in formal semantics, we demonstrate that apparent comprehension can be decomposed into genuine understanding and surface-level pattern exploitation, enabling the first reliable measurement of true language competence."

Key differences from CARS: CARS says "there's a gap" → Intellectual Contract says "the field's core assumption may be wrong". CARS is additive → Intellectual Contract is transformative. Use ONLY for papers where the contribution is a conceptual shift, not an incremental improvement.

**Related Work Writing Strategy:**
- Organize by themes, NOT by individual papers
- Each paragraph should cover a line of research, not a single paper
- End each subsection with a positioning statement: "Unlike prior work that focuses on X, our approach addresses Y"
- Use proper citation clusters: "Several studies have explored ... [1, 2, 3]"

**Preferred Method — Use Built-in Academic API Tools for Literature Discovery:**
When searching for papers to cite in Related Work, prefer built-in tools over manual web search:
- `semantic_scholar_search(query="topic keywords", limit=20, year_range="2020-2026")` — Find relevant papers with citation counts and abstracts
- `arxiv_search(query="topic", category="cs.AI")` — Find latest preprints not yet indexed elsewhere
- `semantic_scholar_paper(paper_id="DOI_or_S2_ID")` — Trace citation chains to find seminal and derivative works
- `crossref_lookup(doi="10.xxxx/xxxxx")` — Validate DOI and retrieve authoritative metadata for BibTeX generation
These tools return structured metadata that can be directly organized into thematic clusters for Related Work paragraphs.

**Methodology Writing Guidelines:**
- Use present tense for describing the method
- Include mathematical formulations where appropriate
- Provide algorithmic pseudocode for complex procedures
- Clearly state assumptions and constraints

**Falsification-Oriented Reasoning (for Nature/Science-level papers)**

When targeting top venues, don't just show your hypothesis is supported — systematically eliminate alternatives:

1. **State your central hypothesis (H1)** explicitly
2. **Generate alternative hypotheses (H2, H3, ...)** that could explain the same observations
3. **Design crucial experiments** that distinguish H1 from alternatives
4. **Report results as eliminations**: "Result X rules out H2 because... Only H1 is consistent with all observed results."

Writing pattern: "If [H2] were correct, we would expect [Prediction]. Instead, we observe [Result], which is inconsistent with H2 but consistent with H1."

Include in Discussion or Results an "Alternative Explanations" paragraph:
> "Several alternative mechanisms could account for the observed improvement. First, [Alt 1]... However, our control experiment (Fig. 3B) demonstrates that... Second, [Alt 2]... This is ruled out by... The most parsimonious explanation consistent with all evidence is [your mechanism]."

**Results Writing Guidelines:**
- Present results objectively with statistical significance
- Reference tables and figures explicitly: "As shown in Table 1, ..."
- Compare with baselines systematically
- Use academic three-line tables:

```latex
\begin{table}[htbp]
\centering
\caption{Comparison of Methods on Benchmark Dataset}
\label{tab:results}
\begin{tabular}{lccc}
\toprule
Method & Accuracy & F1-Score & Latency (ms) \\
\midrule
Baseline A & 85.2 & 83.1 & 45 \\
Baseline B & 87.4 & 85.6 & 62 \\
\textbf{Ours} & \textbf{91.3} & \textbf{89.7} & \textbf{38} \\
\bottomrule
\end{tabular}
\end{table}
```

Markdown equivalent (three-line table):
```markdown
| Method | Accuracy | F1-Score | Latency (ms) |
|:-------|:--------:|:--------:|:------------:|
| Baseline A | 85.2 | 83.1 | 45 |
| Baseline B | 87.4 | 85.6 | 62 |
| **Ours** | **91.3** | **89.7** | **38** |
```

**Discussion Writing: The 5-Layer Model**

The Discussion is the hardest section and the primary indicator of scholarly maturity. It must NOT repeat Results — it must interpret them. Apply these five layers:

**Layer 1 — Core Findings Restatement** (1-2 paragraphs): Restate patterns at a higher level of abstraction, not repeating numbers. "Our results reveal a consistent pattern: X outperforms baselines most significantly when [condition], suggesting..."

**Layer 2 — Mechanism Explanation** (2-3 paragraphs): Explain WHY your results occur. "We attribute this improvement to..." / "A plausible explanation is..." Connect to known theories or propose new explanatory hypotheses.

**Layer 3 — Theoretical Implications** (1-2 paragraphs): Place findings in the larger scholarly picture. "This finding challenges the prevailing assumption that..." / "Our work provides empirical support for [Theory X] by showing..." / "This extends [framework] to [new domain]..."

**Layer 4 — Practical Implications** (1 paragraph): Translate findings into actionable guidance. "For practitioners designing X systems, our results suggest..." / "These findings have direct implications for [application domain]..."

**Layer 5 — Limitations & Boundary Conditions** (1-2 paragraphs): Each limitation must be paired with a mitigation or future direction. "While our evaluation is limited to [scope], we note that [mitigation]..." Strategic: convert limitations into future work signposts.

**Discussion anti-patterns** (if detected, rewrite):
- ❌ Repeating Results numbers line by line
- ❌ Only stating "consistent with prior work" without explaining why
- ❌ One-sentence throwaway limitations
- ❌ No connection to theoretical frameworks
- ❌ No practical implications

**Conceptual Elevation Ladder (for Nature/Science-level papers)**

The difference between a good paper and a Nature paper often lies in ONE paragraph where the author elevates from "what we found" to "what this means for how we understand the world":

| Level | Question | Statement Type | Example |
|:-----:|----------|:-------------:|---------|
| 0 | What happened? | Observation | "Model A outperformed Model B by 15%" |
| 1 | Why? | Mechanism | "This is because A captures long-range dependencies" |
| 2 | So what? (field) | Theoretical insight | "This reveals that local processing is insufficient — challenging [Theory X]" |
| 3 | So what? (science) | Broader principle | "More broadly, this suggests [general principle], extending beyond [domain] to [broader phenomena]" |
| 4 | What next? | New questions | "This raises the question of whether [deeper question] — a question that could not be formulated without this work" |

Good papers reach Level 1-2. Nature/Science papers reach Level 3-4. Level 3-4 requires careful hedging ("suggests", "may indicate", "is consistent with"). The Level 3 paragraph is often the single most important paragraph in the entire paper.

**Layer 6 (Nature/Science only) — Opening New Questions**

The ultimate mark of a paradigm-shifting paper: the Conclusion opens questions that couldn't be formulated before this paper existed.

> "Our findings raise the intriguing possibility that [new question]. If [key finding] indeed reflects [deeper principle], then we would predict [testable prediction]. Testing this would require [specific experiment], now feasible given [your contribution]."

A good closing question must satisfy ALL of: (1) Could NOT have been asked before your paper. (2) Specific enough to be testable. (3) Broad enough to interest wide readership. (4) Answering it would have significant implications.

Anti-pattern: "Future work could improve performance on more datasets" — this is a to-do list item, NOT a new scientific question.

**Conceptual Elevation Ladder (for Nature/Science-level Discussion)**

The difference between a good paper and a Nature paper often lies in ONE paragraph where the author elevates from "what we found" to "what this means for how we understand the world":

| Level | Question | Nature of Statement | Example |
|:-----:|----------|:------------------:|---------|
| 0 | What happened? | Observation | "Model A outperformed Model B by 15%" |
| 1 | Why? | Mechanism | "This is because A captures long-range dependencies" |
| 2 | So what? (field) | Theoretical insight | "This reveals that local processing is insufficient — challenging [Theory X]" |
| 3 | So what? (science) | Broader principle | "More broadly, this suggests [general principle] extending beyond [domain] to [broader phenomena]" |
| 4 | What next? | New questions | "This raises the question of whether [deeper question] — a question that could not be formulated without the framework developed here" |

Good papers reach Level 1-2. Nature/Science papers reach Level 3-4. Level 3-4 requires careful hedging ("suggests", "may indicate", "is consistent with"). The "Level 3" paragraph is often the single most important paragraph in the entire paper.

**Layer 6 (Nature/Science only) — Opening New Scientific Questions**

The ultimate mark of a paradigm-shifting paper: the ending opens a door to questions that couldn't be formulated before this paper existed.

Structure: "Our findings raise the intriguing possibility that [new question]. If [key finding] indeed reflects [deeper principle], then we would predict [testable prediction]. Testing this would require [specific experiment], which is now feasible given [your contribution]."

Quality test for a closing question — it must satisfy ALL of: (1) Could NOT have been asked before your paper. (2) Specific enough to be testable. (3) Broad enough to interest a wide readership. (4) Answering it would have significant implications.

Anti-pattern: "Future work could improve performance on more datasets" — this is a to-do list item, NOT a scientific question.

**Evidence Orchestration**

Strong arguments require multiple evidence types working together. Use triangulation:

| Tier | Evidence Type | Persuasion | When to use |
|:---:|-------------|:----------:|------------|
| 1 | Mathematical proof | ★★★★★ | Theoretical guarantees |
| 2 | Large-scale experiments | ★★★★☆ | Multi-dataset, multi-metric with statistical tests |
| 3 | Ablation studies | ★★★★☆ | Proving each component's necessity |
| 4 | Baseline comparisons | ★★★☆☆ | Establishing competitive performance |
| 5 | Case studies / examples | ★★★☆☆ | Qualitative understanding |
| 6 | Visualizations | ★★☆☆☆ | Intuition building (attention maps, t-SNE) |

**Orchestration rules**: (1) For core claims, provide at least 3 different evidence types. (2) Lead with strong evidence (experiments), then support with explanatory evidence (cases, visualizations). (3) Place preemptive evidence (ablations) where reviewers are likely to question your design choices. (4) Use cascading arguments: sub-conclusion A + sub-conclusion B → support main claim C.

#### Step 2.2: Abstract & Title Engineering

**Abstract: The 6-Sentence Precision Model**

A top-tier abstract is not a compressed version of the paper — it is a standalone "elevator pitch" where each sentence has a specific rhetorical job:

| # | Function | Golden Pattern | Share |
|:-:|----------|---------------|:-----:|
| S1 | **Context** | Open with an impactful fact or trend — NEVER "In recent years..." | 15% |
| S2 | **Problem/Gap** | State the critical limitation of current knowledge/methods | 15% |
| S3 | **This paper** | State your core contribution — use "Here we show/propose..." | 15% |
| S4 | **Approach** | Key methodological innovation (only the critical insight, not all details) | 20% |
| S5 | **Results** | 2-3 headline quantitative findings with specific numbers | 20% |
| S6 | **Significance** | Broader impact — elevate from "this method" to "this finding means..." | 15% |

**Quality rules**:
- S1 first word determines whether the reader continues — open with concrete fact, never vague generality
- S3 must use a strong verb: "propose/introduce/present/develop"
- S5 must contain specific numbers: "improves by 23.7%" not "significantly improves"
- S6 must NOT repeat S3 — it must elevate to a higher level of significance
- Total: 150-250 words, each sentence 25-35 words

**Title Engineering**

The title is the #1 driver of whether a paper gets read and cited. Design principles:

| Principle | Bad | Good |
|-----------|-----|------|
| Be specific | "A New Approach to NLP" | "Attention Is All You Need" |
| Create tension | "Improving Language Models" | "Scaling Data-Constrained Language Models" |
| Method + Effect | "Our New Framework" | "LoRA: Low-Rank Adaptation of Large Language Models" |
| Memorable name | — | "BERT", "GPT", "ResNet", "Transformer" |

**Title types**: Declarative ("Attention Is All You Need"), Descriptive ("A Survey of LLMs"), Question ("Can Machines Think?"), Method:Effect ("LoRA: Low-Rank Adaptation..."). Length: 10-15 words.

**Constraints:**
- No citations in abstract
- No undefined acronyms
- Include quantitative results where applicable
- Match venue word limits

#### Step 2.3: Keyword Extraction

Generate 4-6 keywords:
1. Extract key noun phrases from title and abstract
2. Include both specific terms and broader category terms
3. Avoid words already in the title
4. Follow venue-specific keyword guidelines

### Phase 3: Academic Language & Quality

#### Step 3.1: Academic Language Polishing

Apply these transformations:

| Informal | Academic |
|---------|---------|
| "a lot of" | "numerous" / "a substantial number of" |
| "big" | "significant" / "substantial" |
| "get" | "obtain" / "achieve" / "acquire" |
| "show" | "demonstrate" / "illustrate" / "indicate" |
| "use" | "employ" / "utilize" / "leverage" |
| "think" | "hypothesize" / "postulate" / "argue" |
| "good" | "effective" / "robust" / "promising" |
| "bad" | "suboptimal" / "inadequate" / "limited" |

**Hedging Language (for uncertain claims):**
- "It appears that..." / "The results suggest..."
- "This may be attributed to..." / "One possible explanation is..."
- "To the best of our knowledge..." / "As far as we are aware..."

**Transition Phrases:**
- **Addition**: "Furthermore," / "Moreover," / "In addition,"
- **Contrast**: "However," / "Nevertheless," / "In contrast,"
- **Cause-Effect**: "Consequently," / "As a result," / "Therefore,"
- **Example**: "For instance," / "Specifically," / "In particular,"

#### Step 3.1.3: Scientific Prose Style (for Top-Tier Venues)

When targeting Nature/Science/Cell, apply this distinctive writing style — simultaneously precise, concise, and elegant:

| Standard Academic | Nature/Science Prose |
|------------------|---------------------|
| "It has been demonstrated that X leads to Y (Smith et al., 2020)" | "X drives Y [1]" |
| "In this study, we propose a novel method for..." | "Here we show that..." |
| "The results of our experiments demonstrate that..." | "Our experiments reveal..." |
| "It is important to note that..." | (State the point directly) |
| "Due to the fact that..." | "Because..." |
| "In order to..." | "To..." |
| "A large number of" | "Many" / the exact number |
| 200-300 word paragraphs | 80-150 word paragraphs |

**Principles**: (1) Ruthless conciseness — cut every non-information-carrying word. (2) Strong verbs — "We analyzed" not "We performed an analysis of". (3) Short sentences for key claims — your most important statement should be your shortest sentence. (4) Paragraph compression — 3-5 sentences (80-150 words), one idea per paragraph. (5) "Here we show" as canonical pivot — never "In this paper, we propose a novel...". (6) Active voice throughout — "We measured" not "Measurements were taken".

**Compression example**:
- Before (46 words): "In this paper, we present a novel framework that is designed to address the challenging problem of long-range dependency modeling in sequential data by incorporating a mechanism that enables the model to selectively attend to relevant portions of the input sequence."
- After (12 words): "We introduce a selective attention mechanism for modeling long-range dependencies in sequences."

#### Step 3.1.5: Metadiscourse System

Metadiscourse refers to the linguistic markers authors use to organize text, guide readers, and express stance. Top papers use metadiscourse extensively; average papers underuse it.

**Textual Metadiscourse (organizing the text for the reader)**:

| Type | Function | Examples |
|------|----------|---------|
| Signposts | Tell reader where you're going | "In this section, we first... then... finally..." |
| Frame markers | Mark text structure | "First... Second... Third..." |
| Endophoric | Connect to other parts | "As discussed in Section 2..." / "We return to this below." |
| Code glosses | Explain or elaborate | "in other words," / "specifically," / "namely," |

**Interpersonal Metadiscourse (expressing stance and engaging readers)**:

| Type | Function | Examples |
|------|----------|---------|
| Hedges | Soften certainty | "may", "might", "suggests", "appears to", "it is possible that" |
| Boosters | Strengthen certainty | "clearly", "demonstrate", "establish", "undoubtedly" |
| Attitude markers | Express evaluation | "importantly", "interestingly", "surprisingly", "notably" |
| Reader engagement | Pull reader in | "Note that...", "Consider the case where...", "It is worth noting..." |

**Density by section**: Introduction = high signposts + moderate hedges; Methods = low (objective); Results = moderate boosters + hedges; Discussion = highest density — heavy hedges + attitude markers + reader engagement.

**Anti-patterns**: Over-hedging ("may possibly suggest it might...") signals insecurity. Over-boosting ("clearly and undoubtedly proves...") signals arrogance. Balance based on evidence strength.

#### Step 3.2: Logical Coherence Check

Verify:
- [ ] Each paragraph has a clear topic sentence
- [ ] Arguments follow a logical progression
- [ ] Claims are supported by evidence or citations
- [ ] Transitions between sections are smooth
- [ ] No circular reasoning or unsupported assertions
- [ ] Consistent terminology throughout

#### Step 3.3: Formula Formatting

Use LaTeX math mode:

**Inline**: `$E = mc^2$`

**Display**:
```latex
\begin{equation}
\mathcal{L} = -\sum_{i=1}^{N} y_i \log(\hat{y}_i) + (1-y_i) \log(1-\hat{y}_i)
\label{eq:loss}
\end{equation}
```

### Phase 3.5: Cross-Reference System

When generating a multi-section paper, maintain a reference registry for all numbered elements.

**Auto-Numbering Rules**:
- Figures: Fig. 1, Fig. 2, ... (sequential across entire document)
- Tables: Table 1, Table 2, ...
- Equations: (1), (2), ... or (Section.Number) for long documents like theses
- Algorithms: Algorithm 1, Algorithm 2, ...
- Theorems/Lemmas/Definitions: Theorem 1, Lemma 1, Definition 1, ...

**Cross-Reference Format**:
- In text: "As shown in Fig. 1, ...", "The results in Table 3 indicate..."
- In LaTeX: `\ref{fig:architecture}`, `\ref{tab:results}`, `\ref{eq:loss}`
- NEVER use "the figure above/below" — always use numbered references

**Consistency Rules**:
- Every figure/table MUST be referenced at least once in the text
- Every figure/table MUST have a descriptive caption
- Figures: caption below the figure; Tables: caption above the table
- All figures/tables should appear AFTER their first textual reference
- Maintain a running count — do not restart numbering per section (unless thesis chapters)

**LaTeX Cross-Reference Example**:
```latex
As shown in Fig.~\ref{fig:arch}, the proposed architecture consists of...
Table~\ref{tab:results} summarizes the experimental results.
The loss function is defined in Eq.~(\ref{eq:loss}).
```

### Phase 3.6: Discipline-Specific Writing Conventions

Apply discipline-specific conventions automatically based on the user's field:

**Computer Science / AI**:
- Contributions as numbered list in Introduction
- "We" is acceptable (first person plural)
- Algorithm pseudocode expected for novel methods
- Experimental comparison tables are mandatory
- Ablation study expected for system/model papers
- Reproducibility section encouraged (code/data availability)

**Social Sciences (Psychology, Education, Management)**:
- Hypotheses formally stated with direction (H1, H2, ...)
- Literature review as separate major section
- "Participants" (not "subjects") for human studies
- Effect sizes mandatory alongside p-values
- Limitations section is substantial and thoughtful
- Theoretical implications and practical implications separated

**Natural Sciences (Biology, Chemistry, Physics)**:
- Methods section must enable exact replication
- Materials subsection with supplier details and catalog numbers
- Results and Discussion may be combined
- SI (International System of Units) mandatory
- Gene/protein nomenclature follows field conventions (italics for genes)

**Humanities (Literature, History, Philosophy)**:
- Longer, more discursive paragraphs acceptable
- Extensive footnotes/endnotes common
- Primary source analysis is central
- Theoretical framing prominent in introduction
- May use first person singular ("I argue that...")
- Chicago/MLA citation style common

**Engineering**:
- Design specifications and constraints explicit
- Performance metrics quantified with units
- Comparison with industry standards or benchmarks
- Practical implications and feasibility emphasized
- Cost/feasibility analysis may be included

**Medical / Clinical Research**:
- CONSORT checklist for Randomized Controlled Trials
- STROBE checklist for observational studies
- Ethics approval statement mandatory
- Patient privacy (de-identification) documented
- Clinical significance distinct from statistical significance
- PICO format for research questions
- Trial registration number required

### Phase 3.7: Figure & Table Design Philosophy

Readers should understand the paper's full story by browsing ONLY figures, tables, and their captions.

**Figure Design Rules**:

1. **Self-explanatory captions**: Include enough context that the figure stands alone
   - ❌ "Figure 1: System architecture."
   - ✅ "Figure 1: Architecture of CalcFormer. The symbolic engine (blue) is embedded as a differentiable module within each Transformer layer, enabling end-to-end training while preserving exact arithmetic."

2. **Information hierarchy**: Fig. 1 = Architecture/Framework overview (builds mental model) → Fig. 2-3 = Method details → Fig. 4+ = Experiment results → Last figure = Case study / Error analysis

3. **Color strategy**: Use colorblind-safe palettes. "Ours" gets the most salient color. Baselines get desaturated colors. Maintain color consistency across all figures.

4. **Chart type selection**: Comparison → Bar/Radar chart. Trends → Line chart (with CI bands). Distributions → Box/Violin plot. Ablation → Grouped bar. Attention → Heatmap. High-dimensional → t-SNE/UMAP.

**Table Design Rules**:

1. Three-line tables (booktabs: `\toprule`, `\midrule`, `\bottomrule`)
2. Best result in **bold**, second-best with underline
3. Statistical significance marked with `*`/`**`/`***`, explained in caption
4. "Ours" always in the last row — creates visual "landing point"
5. Numbers right-aligned, text left-aligned
6. Caption ABOVE the table (unlike figures where caption goes below)

### Phase 3.8: The Conceptual Figure (Nature/Science Signature)

When targeting top venues, design a "conceptual figure" — typically Figure 1 — that is NOT a system diagram or data plot, but a visual representation of the paper's core IDEA capturing the intellectual shift.

**Types of Conceptual Figures**:

| Type | When to use | Structure |
|------|------------|-----------|
| **Before/After** | Your work changes how we model something | Left: old understanding → Right: new understanding |
| **Mechanism Schematic** | You've discovered a new mechanism | Step-by-step visual of the causal chain |
| **Unifying Framework** | You unify previously separate concepts | Hierarchical map showing how pieces connect |
| **Scale Bridge** | Your finding connects micro and macro | Multi-scale diagram across levels |
| **Conceptual Space** | You've mapped out a new landscape | 2D space with labeled regions (like a phase diagram) |

**Design principles**: Minimal text — readable in 10 seconds. Use spatial relationships to encode logical relationships. Use color semantically, not decoratively. Include a one-line "punchline" as figure title: not "Overview" but "X enables Y by Z". This figure becomes the paper's visual identity.

**Caption structure**: "**Figure 1: [One-sentence insight].** **a**, [Panel a description]. **b**, [Panel b description]. The key insight is that [intellectual contribution restated visually]."

### Phase 4: Formatting & Output

#### Step 4.1: LaTeX Document Generation

When the user needs a full LaTeX document:

```bash
python -c "
content = r'''
\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}
\usepackage[numbers]{natbib}
\usepackage{algorithm}
\usepackage{algorithmic}

\title{[Paper Title]}
\author{[Author Name] \\\\ [Affiliation] \\\\ [Email]}
\date{}

\begin{document}
\maketitle

\begin{abstract}
[Abstract text]
\end{abstract}

\textbf{Keywords:} keyword1, keyword2, keyword3

\section{Introduction}
[Content]

\section{Related Work}
[Content]

\section{Methodology}
[Content]

\section{Experiments}
[Content]

\section{Conclusion}
[Content]

\bibliographystyle{plainnat}
\bibliography{references}

\end{document}
'''
with open('/mnt/user-data/outputs/paper.tex', 'w') as f:
    f.write(content)
print('LaTeX document generated successfully.')
"
```

#### Step 4.2: BibTeX Reference Generation

**Citation Verification & Metadata Retrieval:**

Before generating BibTeX entries, verify paper metadata using built-in academic tools (if available):
- `crossref_lookup(doi="10.xxxx/xxxxx")` — Validate DOI and retrieve authoritative metadata
- `semantic_scholar_search(query="paper title keywords")` — Find paper and get citation count, venue, abstract
- `semantic_scholar_paper(paper_id="DOI_or_S2_ID")` — Get full reference list and citation network

These tools return structured metadata that can be directly converted to BibTeX. If tools are not configured, manually construct entries from user-provided information.

Generate BibTeX entries from citation information:

```bibtex
@article{author2024title,
  title={Paper Title},
  author={Last, First and Last2, First2},
  journal={Journal Name},
  volume={XX},
  number={X},
  pages={1--10},
  year={2024},
  publisher={Publisher}
}

@inproceedings{author2024conf,
  title={Conference Paper Title},
  author={Last, First},
  booktitle={Proceedings of Conference Name},
  pages={100--110},
  year={2024}
}
```

#### Step 4.3: Citation Format Conversion

Support multiple citation formats:

**APA 7th Edition:**
```
Author, A. A., & Author, B. B. (Year). Title of article. Journal Name, Volume(Issue), Pages. https://doi.org/xxxxx
```

**GB/T 7714-2015:**
```
[1] 作者. 题名[J]. 刊名, 年, 卷(期): 页码.
[2] Author A, Author B. Title[J]. Journal, Year, Vol(No): Pages.
```

**IEEE:**
```
[1] A. A. Author and B. B. Author, "Title of article," Journal Name, vol. X, no. X, pp. X-X, Month Year.
```

### Phase 5: Submission Preparation

#### Step 5.1: Cover Letter Generation

```markdown
Dear Editor-in-Chief,

We are pleased to submit our manuscript entitled "[Title]" for consideration 
for publication in [Journal Name].

[1-2 sentences on the research problem and its significance]

[1-2 sentences on the key findings and contributions]

[1 sentence on why this journal is appropriate]

This manuscript has not been published and is not under consideration for 
publication elsewhere. All authors have read and approved the final manuscript.

We suggest the following potential reviewers:
1. [Name], [Affiliation], [Email] - Expert in [Area]
2. [Name], [Affiliation], [Email] - Expert in [Area]

Thank you for your consideration.

Sincerely,
[Corresponding Author Name]
[Affiliation]
[Email]
```

#### Step 5.2: Rebuttal / Response to Reviewers

```markdown
# Response to Reviewers

We thank the reviewers for their constructive comments. We have carefully 
addressed all concerns. Changes in the revised manuscript are highlighted 
in blue. Below we provide point-by-point responses.

---

## Reviewer 1

### Comment 1.1
> [Paste reviewer's comment]

**Response:** We appreciate this observation. [Address the comment specifically]. 
We have revised Section X (Page Y, Lines Z-W) to [describe the change].

### Comment 1.2
> [Paste reviewer's comment]

**Response:** [Response]

---

## Reviewer 2

### Comment 2.1
> [Paste reviewer's comment]

**Response:** [Response]
```

#### Step 5.3: Venue Format Compliance

Common formatting requirements:

| Venue Type | Typical Requirements |
|-----------|---------------------|
| **IEEE Conferences** | Two-column, 10pt, specific LaTeX template |
| **ACM Conferences** | `acmart` document class, specific format |
| **Springer Journals** | `svjour3` class, single/double column |
| **Elsevier Journals** | `elsarticle` class, structured abstract |
| **Nature** | ~3,000 words (Article) / ~1,500 (Letter), ~150-word abstract (single paragraph, NO headings), max 6 main figures, ~30-50 refs, NO numbered sections (flowing prose), Methods at end + Extended Data, first paragraph IS the introduction, figures as "Fig. 1a" (lowercase panels), "Extended Data" not "Supplementary" |
| **Science** | ~2,500 words (Report) / ~4,500 (Research Article), ~125-word abstract (single paragraph), max 4 figures (Report) / 6 (Article), ~30-50 refs, Report = single continuous flow, Supplementary Materials for methods |
| **Cell** | ~5,000 words, ~150-word abstract, max 7 figures, ~60-80 refs, requires eTOC blurb (~50 words), Highlights (3-4 bullets, each ≤85 chars), STAR Methods (Key Resources Table, Resource Availability, Method Details, Quantification), Graphical Abstract required |
| **Chinese Journals** | GB/T 7714 citations, bilingual abstract |

## Chinese Academic Writing Support (中文学术写作)

For Chinese academic manuscripts:

**结构化摘要模板:**
```
【目的】1-2句阐述研究目的
【方法】2-3句描述研究方法
【结果】2-3句呈现主要发现
【结论】1-2句总结意义和启示
```

**中文学术用语规范:**
- 使用"本文"而非"我们的论文"
- 使用"研究表明"而非"可以看出"
- 使用"具有重要意义"而非"很重要"
- 数据描述使用"约"、"近"、"逾"等约数词

**中英文对照:**
- 提供中英文双语摘要
- 关键词中英文对照
- 参考文献按 GB/T 7714-2015 格式

### Phase 5.5: Reviewer Psychology & Strategic Writing

Understanding reviewer behavior is essential for writing papers that survive peer review.

**The 10-Minute Decision**: Reviewers form ~70% of their judgment within the first 10 minutes (Abstract + Introduction + scanning Figures/Tables). Therefore: (1) The first 3 pages determine your paper's fate. (2) Figures/tables are scanned before text is read. (3) The contributions list is checked against experiments immediately.

**Top 6 Rejection Reasons & Preemptive Strategies**:

| Rejection Reason | Frequency | Prevention Strategy |
|-----------------|:---------:|-------------------|
| "Incremental contribution" | ~35% | In Introduction, show essential (not just performance) difference from strongest baseline. Use "Unlike [X], our approach..." |
| "Insufficient experiments" | ~25% | Include ablation study, statistical tests, multi-dataset validation. Frame experiments as Research Questions (RQ1/RQ2/RQ3) |
| "Unclear writing" | ~15% | Every section opens with overview sentence. Every paragraph has topic sentence. Every formula followed by intuitive explanation |
| "Weak motivation" | ~10% | Move 2 (CARS) must have concrete failure cases or quantitative evidence, not just "X hasn't been studied" |
| "Lacks theoretical depth" | ~10% | Discussion Layer 3 (theoretical implications) must connect findings to established frameworks |
| "Missing related work" | ~5% | Use `literature-review` skill for systematic search; cover all work from last 2 years |

**Preemptive "Steel Man" technique**: In Discussion, proactively present the strongest counter-argument to your claims, then refute it with evidence:
> "One might argue that the improvement stems from [alternative explanation]. However, our ablation (Table 4) shows that removing [key component] while preserving [confound] leads to X% performance drop, ruling out this alternative."

**Preemptive "Bridge" technique**: In Related Work, write an explicit differentiation sentence for each close competitor:
> "While [Competitor] also addresses [problem], their approach requires [limitation], which does not hold in [scenario]. Our method removes this assumption via [key difference]."

### Phase 6: Iterative Revision & Self-Review

#### Step 6.1: Academic Self-Review Checklist

After generating any manuscript section, automatically run an internal review:

**Structure Review**:
- [ ] Does each paragraph have exactly ONE main idea with a clear topic sentence?
- [ ] Do transitions between paragraphs maintain logical flow?
- [ ] Is paragraph length appropriate (150-300 words for body paragraphs)?
- [ ] Are claims properly hedged (avoid overclaiming)?

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
- [ ] Is sample size adequate (power analysis referenced)?

**Language Review**:
- [ ] No informal language or contractions
- [ ] Consistent terminology throughout
- [ ] Abbreviations defined on first use
- [ ] Appropriate voice (active for methods, passive where conventional)

**Citation Review**:
- [ ] All factual claims cited
- [ ] No orphan citations (cited but not in reference list, or vice versa)
- [ ] Self-citation ratio reasonable (<20%)
- [ ] Recent references included (>30% from last 3 years for active fields)
- [ ] Seminal/foundational works included
- [ ] Citation diversity (not over-relying on one research group)

#### Step 6.2: Simulated Peer Review

When the user asks "review my paper" or "check my manuscript", simulate a rigorous peer review:

```markdown
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
1. [Minor issue with suggestion]
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

#### Step 6.3: Revision Tracking

When revising based on feedback (reviewer comments or self-review):
1. Generate a **change log** with specific location (Section, Page, Line range)
2. In LaTeX, use `\textcolor{blue}{revised text}` for tracked changes
3. Generate the **Response to Reviewers** document simultaneously (see Phase 5.2)
4. Track which reviewer comments have been addressed vs. rebutted

### Phase 7: Venue Recommendation & Submission Strategy

#### Step 7.1: Venue Matching

Based on the manuscript content, recommend suitable venues by analyzing:

1. **Topic Alignment**: Match keywords against venue scopes
2. **Methodology Fit**: Some venues favor empirical, others theoretical
3. **Impact Level**: Top-tier (Nature/Science/AAAI/NeurIPS), mid-tier, or specialized
4. **Turnaround Time**: Fast track vs. standard review
5. **Open Access**: OA requirements (many funders require OA)
6. **Geographic Preference**: Chinese journals (核心期刊), international venues

**Use `web_search` to look up**:
- Current venue CFP (Call for Papers) and submission deadlines
- Recent accepted paper topics
- Impact Factor / CiteScore / h5-index
- Acceptance rates and average review time

**Output Format**:
```markdown
## Venue Recommendations for: "[Paper Title]"

| Rank | Venue | Type | IF/h5 | Fit | Review Time | Notes |
|:----:|-------|------|:-----:|:---:|:-----------:|-------|
| 1 | [Name] | Journal | X.X | ⭐⭐⭐⭐⭐ | ~3 months | [Reason] |
| 2 | [Name] | Conference | h5=XX | ⭐⭐⭐⭐ | [Deadline] | [Reason] |
| 3 | [Name] | Journal | X.X | ⭐⭐⭐⭐ | ~6 months | [Reason] |
```

#### Step 7.2: Submission Checklist Generation

For the selected venue, generate a tailored checklist:

- [ ] Manuscript formatted per venue template (LaTeX class / Word template)
- [ ] Word/page count within venue limits
- [ ] Abstract within word limit (check venue: typically 150-250 words)
- [ ] Required sections present (e.g., Data Availability Statement)
- [ ] Figures meet resolution/format requirements (typically 300 DPI, EPS/TIFF for print)
- [ ] Supplementary materials prepared
- [ ] Author contributions statement (CRediT taxonomy)
- [ ] Conflict of interest disclosure
- [ ] Ethics approval statement (if applicable)
- [ ] Data and code availability statement
- [ ] ORCID for all authors
- [ ] Cover letter drafted (see Phase 5.1)
- [ ] Suggested and excluded reviewers listed
- [ ] All co-authors have reviewed and approved

### Phase 8: Long Document Project Management

For thesis, dissertation, or book-length writing projects that span multiple sessions.

#### Step 8.1: Project Registry

When the user initiates a thesis/long-document project, create a project registry and store key facts in memory:

```json
{
  "project_type": "doctoral_thesis",
  "title": "...",
  "discipline": "...",
  "institution": "...",
  "chapters": [
    {"number": 1, "title": "Introduction", "status": "draft_complete", "word_count": 5200},
    {"number": 2, "title": "Literature Review", "status": "in_progress", "word_count": 3400},
    {"number": 3, "title": "Methodology", "status": "outlined", "word_count": 0}
  ],
  "total_target_words": 80000,
  "deadline": "YYYY-MM-DD",
  "citation_style": "APA7",
  "key_decisions": ["Using mixed methods design", "Primary framework: TAM"]
}
```

Save this as `/mnt/user-data/workspace/thesis_project.json` and update it each session.

#### Step 8.2: Cross-Chapter Consistency

When writing/revising any chapter:
1. **Terminology consistency**: Maintain a project glossary, flag inconsistent terms across chapters
2. **Narrative arc**: Each chapter's conclusion must bridge to the next chapter's introduction
3. **Citation consistency**: Use the same master BibTeX file, check for orphan references
4. **Notation consistency**: Same variables, same formatting throughout all chapters
5. **Forward/backward references**: "As discussed in Chapter 2..." / "Chapter 4 will demonstrate..."

#### Step 8.3: Progress Dashboard

Generate a progress summary on request:

```markdown
## Thesis Progress Dashboard

**Overall**: 8,600 / 80,000 words (10.8%)
**Deadline**: YYYY-MM-DD (N days remaining)
**Required pace**: ~423 words/day

| Chapter | Status | Words | Target | Progress |
|---------|--------|------:|-------:|:--------:|
| Ch.1 Introduction | ✅ Draft | 5,200 | 8,000 | ████████░░ 65% |
| Ch.2 Literature | 🔄 In Progress | 3,400 | 15,000 | ██░░░░░░░░ 23% |
| Ch.3 Methodology | 📋 Outlined | 0 | 12,000 | ░░░░░░░░░░ 0% |

**Next Actions**:
1. Complete Literature Review Chapter 2
2. Begin Methodology chapter outline
```

## Quality Checklist

Before finalizing:

- [ ] Title is concise, specific, and informative (no more than ~15 words)
- [ ] Abstract follows structured format and is within word limit
- [ ] Introduction clearly states gap, motivation, and contributions
- [ ] Related work is organized thematically, not paper-by-paper
- [ ] Methodology is reproducible from the description
- [ ] Results include statistical significance and comparison with baselines
- [ ] All figures and tables are referenced in the text
- [ ] Tables use academic three-line format
- [ ] All claims are supported by evidence or citations
- [ ] Language is formal, precise, and uses appropriate hedging
- [ ] Citations are consistent in format
- [ ] No plagiarism — all text is original or properly quoted
- [ ] Conclusion does not introduce new information
- [ ] Acknowledgments include funding sources
- [ ] References are complete and correctly formatted

## Output Format

- **Default**: Markdown document with LaTeX math notation
- **LaTeX**: Full `.tex` file with BibTeX for journal submission
- **Both**: Markdown for review + LaTeX for submission

All output files should be saved to `/mnt/user-data/outputs/` and presented using `present_files`.

## Notes

- Always match the language of the user (Chinese academic writing for Chinese users)
- When the target venue is specified, strictly follow its formatting guidelines
- Use `web_search` to look up venue-specific templates and formatting requirements
- For literature review sections, integrate with the `literature-review` skill for comprehensive citation management
- For data presentation, integrate with `chart-visualization` and `data-analysis` skills
- Prefer generating both Markdown (for preview) and LaTeX (for submission) versions
