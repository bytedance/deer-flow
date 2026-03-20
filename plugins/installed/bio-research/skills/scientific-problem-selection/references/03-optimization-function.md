# SKILL 3: Optimization Function Selection

## Overview
This skill helps scientists articulate HOW their project should be evaluated and define what success means. While Skill 2 focused on likelihood of success (the X-axis), this skill focuses on impact if successful (the Y-axis). The key insight: **value is in the eye of a belief system**—the value creation framework must be explicitly stated and led with.

## Core Principle

**"Pick the right optimization function."**

Different types of projects should be evaluated by different metrics. A common source of conflict between trainees and PIs, or authors and referees, is a misunderstanding about which category a project falls under. The root cause is often failure to articulate evaluation criteria clearly.

## The Fundamental Truth

The default state of:
1. Every new discovery is **irrelevance**
2. Every new technology is **non-use**
3. Every company is **death**

Scientists must actively work against these defaults by choosing the right metrics and scoring well on at least one axis.

## The Skill Workflow

### Phase 1: Project Categorization (5 minutes)

First, Claude should determine what type of project the user is pursuing:

**Question 1: What is the primary goal?**
A. Understand how biology works (fundamental knowledge)
B. Enable new experiments or capabilities (tool/technology)
C. Solve a practical problem (invention/application)
D. Something else (please describe)

**Question 2: What would "success" look like in 3-5 years?**
- 1-2 sentences describing the ideal outcome

**Question 3: Who cares if this succeeds?**
- Academic researchers in the subfield?
- Broader scientific community across fields?
- Clinicians or practitioners?
- Industry partners or companies?
- General public or specific communities?
- All of the above?

Based on the answers, Claude should help identify the right optimization function.

### Phase 2: Understanding the Three Main Frameworks

#### Framework 1: Basic Science
**Axes:** How much did we learn? × How general/fundamental is the object of study?

**Philosophy:** A high score on EITHER axis yields substantial impact. You don't need both.

**Examples:**
- **High Generality, Medium Learning:** Ribosome stalling complex
  - Updates understanding of translation (fundamental process)
  - Scores well because translation is universal
  
- **Medium Generality, High Learning:** Oxytricha germ-line nucleus
  - Genomic acrobatics may not be common to other organisms
  - BUT elegant mapping scores highly on how much we learned
  - May yield tools for genome editing (bonus)
  
- **High on Both Axes (Landmark):** RNA interference, biomolecular condensates
  - These are rare—don't expect every project to be here
  - But aim to score well on at least one axis

**Key Questions:**
- How many systems/organisms does this apply to?
- Does it update understanding of a fundamental process?
- Will textbooks need to be rewritten?
- What new questions does this open?

#### Framework 2: Technology Development
**Axes:** How widely will it be used? × How critical is it for the application?

**Philosophy:** Again, high score on EITHER axis is sufficient.

**Examples:**
- **Widely Used, Not Critical:** BLAST
  - Used in countless projects
  - Rarely THE critical tool, but enormous cumulative impact
  
- **Not Widely Used, Highly Critical:** Cryo-electron tomography
  - Too complicated for broad adoption
  - But generates stunning data that's impossible to get otherwise
  - When you need it, nothing else works
  
- **High on Both Axes (Game-Changing):** 
  - GFP, CRISPR, AlphaFold (the famous ones)
  - But also: lentiviral delivery, cell sorting, massively parallel sequencing
  - Technologies we cannot imagine living without

**Key Questions:**
- How many labs would adopt this?
- For what fraction of experiments is this THE enabling technology?
- What becomes possible that wasn't before?
- How hard is it to implement?

**Critical Rule:** A tool that won't be widely used AND isn't critical for an application probably isn't worth building.

#### Framework 3: Typical Invention/Application
**Axes:** How much good? × For how many people?

**Philosophy:** Useful for translational work, frugal science, global health.

**Examples:**
- Foldscope: Paper microscope accessible to millions of students globally
- Neglected tropical disease intervention: Quality-adjusted life years per $100
- Medical device: Number of patients who can access treatment

**Key Questions:**
- What problem does this solve?
- How many people have this problem?
- How much better is their life if you solve it?
- What's the cost per person helped?

### Phase 3: Selecting and Articulating Your Framework

Based on your Phase 1 responses, let me help you choose:

**If you selected A (fundamental knowledge):** → Basic Science Framework
**If you selected B (enable experiments):** → Technology Development Framework  
**If you selected C (solve practical problem):** → Invention Framework

**Now, let's be explicit:**

1. **State Your Framework:** "This project should be evaluated as [basic science/technology development/invention]."

2. **Define Your Axes:** 
   - X-axis measures: [specific metric]
   - Y-axis measures: [specific metric]

3. **Make Your Case:**
   - X-axis score (Low/Medium/High): [Your assessment + reasoning]
   - Y-axis score (Low/Medium/High): [Your assessment + reasoning]

4. **Threshold Check:** 
   - Do you score at least MEDIUM-HIGH on one axis?
   - If both are LOW-MEDIUM, you have a problem

### Phase 4: Alternative or Custom Metrics

Sometimes standard frameworks don't fit. Examples where custom metrics work:

**Alternative Metric Examples:**
- **Frugal Science:** How many children in low/middle-income countries gain access to microscopy?
- **Neglected Disease:** Quality-adjusted life years saved per $100 invested
- **Sustainability:** Tons of CO₂ equivalent prevented × cost-effectiveness
- **Equity:** Reduction in disparity metric × number of people affected

**When to propose alternative metrics:**
- Your work addresses a specific underserved need
- Standard metrics miss your core value proposition
- You're working in an emerging area without established norms
- Your work crosses traditional boundaries

**How to propose alternative metrics:**
1. Explain why standard metrics are insufficient
2. Define your proposed metric clearly
3. Provide a value creation index (two axes)
4. Show how your project scores on these axes

### Phase 5: Comparative Assessment

Even if absolute impact is hard to estimate, comparative assessment is valuable:

**Exercise: Compare 3 Related Projects**

For your project and two alternatives (either from literature or hypothetical):

| Project | Framework | X-Axis Score | Y-Axis Score | Overall |
|---------|-----------|--------------|--------------|---------|
| Yours | [Type] | [L/M/H] + reasoning | [L/M/H] + reasoning | [Assessment] |
| Alt 1 | [Type] | [L/M/H] + reasoning | [L/M/H] + reasoning | [Assessment] |
| Alt 2 | [Type] | [L/M/H] + reasoning | [L/M/H] + reasoning | [Assessment] |

**Comparative Questions:**
- Which would be most impactful if they all work?
- Which has the best risk-adjusted impact?
- Are you pursuing the best option?
- If not, why? (Sometimes there are good reasons: resources, expertise, timing)

### Phase 6: Avoiding Metric Mismatch

**Common Mismatches:**

#### Mismatch 1: Basic Science vs. Technology Evaluation
**Scenario:** You're doing fundamental biology, but reviewers ask "How widely will this be used?"

**Problem:** They're evaluating basic science with technology metrics

**Solution:** Explicitly frame as basic science. Lead with: "This updates our understanding of [fundamental process], which is conserved across [many systems]."

#### Mismatch 2: Technology vs. Basic Science Evaluation
**Scenario:** You're building a tool, but reviewers ask "How much did we learn about biology?"

**Problem:** They're evaluating technology with basic science metrics

**Solution:** Explicitly frame as technology development. Lead with: "This enables experiments that are currently impossible, which [X] labs need for [Y] applications."

#### Mismatch 3: Within-Category Confusion
**Scenario:** Your basic science is specific but deep, but reviewers want broad generality

**Problem:** They think both axes are required, rather than either/or

**Solution:** Explicitly acknowledge: "While this may not be universal, the depth of mechanistic insight scores highly on the learning axis."

#### Mismatch 4: Time Horizon Mismatch
**Scenario:** You're working on long-term fundamental research, but reviewers want immediate impact

**Problem:** Different value systems about when impact should materialize

**Solution:** Articulate your time horizon explicitly and provide historical examples of similar timelines

### Phase 7: Value System Discussion

This is where Claude explicitly discusses the user's belief system about what matters:

**Questions for Reflection:**

1. **What drives the user?**
   - Discovery and understanding?
   - Enabling others?
   - Solving problems?
   - Building things?

2. **What would make the user proud?**
   - Paper in Cell/Nature/Science?
   - Tool used by hundreds of labs?
   - Treatment reaching patients?
   - Opening a new field?

3. **How does the user want to be remembered?**
   - "Discovered X"
   - "Built Y that enabled Z"
   - "Solved problem W"
   - "Trained students who went on to..."

4. **Whose approval matters?**
   - Specific senior scientists in the field?
   - Broader community across fields?
   - Practitioners who use tools?
   - People whose lives are improved?

**There are no wrong answers—but alignment matters:**
- The project should match the user's value system
- The evaluation framework should match the project type
- Communication should lead with the framework

### Phase 8: Literature Benchmarking

Claude should use PubMed to benchmark impact in the user's area:

**Searches should include:**

1. **Impact Exemplars:** Papers the user considers high-impact in the field
   - What framework did they use (implicitly or explicitly)?
   - How did they score on the axes?
   - What made them successful?

2. **Analogous Projects:** Similar approaches or systems
   - How were they evaluated?
   - What impact did they achieve?
   - What can be learned from their framing?

3. **Field Expectations:** What's typical for the area?
   - Are basic science papers common?
   - Is technology development valued?
   - What level of impact is "good enough"?

**Questions to ask the user:**
- What papers should be analyzed as benchmarks?
- What search terms capture the field's impact exemplars?
- Are there specific journals or authors whose framing to emulate?

### Phase 9: Communication Strategy

Once the framework is selected, here's how to lead with it:

#### In Talks:
**Opening Frame (within first 2 slides):**
- "The goal of this work is to understand [fundamental process X] in [general system Y]" → Basic science
- "We're developing a technology that will enable [critical experiment X] for [community Y]" → Technology
- "This invention addresses [problem X] affecting [N] people" → Application

#### In Papers:
**Abstract Structure:**
- State your framework implicitly through word choice
- Basic science: "reveals," "demonstrates," "shows that"
- Technology: "enables," "provides," "makes it possible to"
- Application: "solves," "addresses," "improves"

#### In Grants:
**Broader Impact Section:**
- Explicitly name your evaluation framework
- Provide the two-axis assessment
- Score yourself on each axis with evidence

#### With Your PI/Committee:
**Alignment Conversation:**
- "I want to make sure we're aligned on how this should be evaluated"
- "I see this as [framework], scoring [X] on [axis 1] and [Y] on [axis 2]"
- "Do you agree, or do you see it differently?"
- "This matters because..." [explain downstream implications]

## Output Deliverable

Claude should produce a **2-page Impact Assessment Document**:

### Page 1: Framework and Scoring

#### Project Categorization:
- **Type:** Basic Science / Technology Development / Invention / Custom
- **Rationale:** [Why this categorization fits]

#### Optimization Function:
- **X-Axis:** [Metric name and definition]
- **Y-Axis:** [Metric name and definition]
- **Custom Rationale (if applicable):** [Why standard metrics don't fit]

#### Self-Assessment:

**X-Axis Score: [Low/Medium/High]**
- Evidence: [Specific reasons for this score]
- Examples: [Comparable projects or benchmarks]
- PubMed Support: [Key papers that inform assessment]

**Y-Axis Score: [Low/Medium/High]**
- Evidence: [Specific reasons for this score]
- Examples: [Comparable projects or benchmarks]
- PubMed Support: [Key papers that inform assessment]

**Overall Assessment:**
- Score on at least one axis: ☑ Yes / ☐ No
- Strong justification: ☑ Yes / ☐ No
- Aligned with your values: ☑ Yes / ☐ No

#### Visual Framework:
```
         [Your Project Type]
              
Y-Axis    |           ★ Your Project
[Metric]  |         /
          |       /
          |     /
          |   /
          |_________________
              X-Axis [Metric]
              
★ = Your project
Reference projects plotted for context
```

### Page 2: Communication and Alignment

#### Value System Alignment:
- **What Drives You:** [Discovery/Enabling/Problem-solving/Building]
- **Success Definition:** [What would make this worthwhile]
- **Approval Sources:** [Whose opinion matters and why]
- **Framework Fit:** [How project aligns with values]

#### Potential Mismatches to Avoid:
1. [Specific mismatch type]
   - Scenario: [When this might happen]
   - Prevention: [How to frame to avoid it]

2. [Another mismatch]
   - Scenario: [When this might happen]
   - Prevention: [How to frame to avoid it]

#### Communication Strategy:

**For Talks:**
- Opening frame: [Exact language to use in first 2 slides]
- Key phrases: [Vocabulary that signals your framework]

**For Papers:**
- Abstract structure: [Framework-appropriate language]
- Impact statement: [How to articulate in discussion]

**For Grants:**
- Broader impact: [How to score yourself explicitly]
- Justification: [Evidence for scores]

**For Mentors:**
- Alignment question: [Exact question to ask]
- Your perspective: [How you see it]
- Discussion points: [What matters for alignment]

#### Comparative Analysis:

| Project | Type | X-Score | Y-Score | Notes |
|---------|------|---------|---------|-------|
| Yours | [Type] | [L/M/H] | [L/M/H] | [Key strengths] |
| Benchmark 1 | [Type] | [L/M/H] | [L/M/H] | [What you can learn] |
| Benchmark 2 | [Type] | [L/M/H] | [L/M/H] | [What you can learn] |
| Alternative | [Type] | [L/M/H] | [L/M/H] | [Why not pursuing] |

#### Action Items:
1. [Specific step to strengthen X-axis score or argument]
2. [Specific step to strengthen Y-axis score or argument]
3. [Communication alignment with key stakeholders]

## Practical Examples

### Example 1: Ribosome Stalling (Basic Science)
- **Framework:** Basic science
- **X-Axis (Generality):** HIGH—translation is universal
- **Y-Axis (Learning):** MEDIUM—mechanism of one quality control system
- **Assessment:** High on generality alone = substantial impact
- **Communication:** "Updates our understanding of translation quality control"

### Example 2: BLAST (Technology)
- **Framework:** Technology development
- **X-Axis (Widely Used):** VERY HIGH—used by virtually all molecular biologists
- **Y-Axis (Critical):** LOW-MEDIUM—helpful but rarely essential
- **Assessment:** Extreme breadth of use = enormous cumulative impact
- **Communication:** "Enables rapid sequence comparison across all biological databases"

### Example 3: Cryo-EM Tomography (Technology)
- **Framework:** Technology development
- **X-Axis (Widely Used):** LOW—complex, expensive, specialized
- **Y-Axis (Critical):** VERY HIGH—generates impossible-to-get-otherwise data
- **Assessment:** Extreme criticality for niche = high impact
- **Communication:** "Enables 3D visualization of molecular machines in native cellular context"

### Example 4: Foldscope (Invention)
- **Framework:** Invention (custom metric)
- **X-Axis (Good):** MEDIUM—functional microscopy
- **Y-Axis (People):** VERY HIGH—millions of students globally
- **Assessment:** Massive reach × modest utility = transformative for education
- **Communication:** "Democratizes microscopy for global education"

## Key Principles to Remember

1. **Value Is in the Eye of a Belief System:** Make yours explicit.

2. **Lead with Your Metric:** Don't assume others share your framework.

3. **Either Axis Suffices:** You don't need both—just score well on one.

4. **Articulate Early:** Discuss with mentors before you're 2 years in.

5. **Avoid Default State:** Work actively against irrelevance/non-use.

6. **Compare, Don't Absolute:** Even rough comparison beats ignoring impact.

7. **Align Communication:** Your words should signal your framework.

8. **Match Project to Values:** Life is too short for misaligned work.

## Warning Signs

**Warning signs include:**
- Inability to articulate which framework applies
- Scoring LOW on both axes
- Project type and evaluation framework don't match
- User and PI have different frameworks but haven't discussed it
- Using basic science metrics for a tool or vice versa
- Never explicitly discussing impact assessment

**Good shape indicators:**
- Clear statement of optimization function
- MEDIUM-HIGH score on at least one axis
- Framework matches project type
- Alignment with key stakeholders
- Communication signals framework clearly
- Benchmarking against comparable work

## Getting Started

Claude should begin Phase 1 by asking:
1. What is the primary goal? (A/B/C/D)
2. What would success look like in 3-5 years?
3. Who cares if this succeeds?

Together, Claude and the user will select the right optimization function and position the work for maximum impact.

---

*Remember: Impact assessment isn't about ego—it's about ensuring work matters in the way the scientist wants it to matter. Explicit framing prevents years of misalignment.*
