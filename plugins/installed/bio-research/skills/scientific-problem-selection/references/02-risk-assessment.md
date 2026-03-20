# SKILL 2: Risk Assessment and Assumption Analysis

## Overview
This skill helps scientists systematically identify, quantify, and manage project risk through rigorous assumption analysis. The goal is not to eliminate risk—risk-free projects tend to be incremental—but to name it, quantify it, and work steadily to chip away at it. This skill builds directly on the Problem Ideation Document from Skill 1.

## Core Principle

**"Don't avoid risk; befriend it."**

The most important concept in problem choice is the two-axis evaluation:
- **X-axis:** Likelihood of success
- **Y-axis:** Impact if successful

This skill focuses on the X-axis, helping users move their project rightward through systematic risk analysis.

## Why This Matters

A project with a high-risk assumption that won't read out for >2 years is problematic. One that requires multiple miracles to succeed should be avoided or refined. The human tendency is to stay in a safe local space, work laterally, and put off facing existential risks—like an ostrich burying its head in the sand. This skill helps users face risk head-on.

## The Skill Workflow

### Phase 1: Extract Project Assumptions (10-15 minutes)

First, Claude should gather information about the user's project from Skill 1:

1. **Project Summary** (from Skill 1):
   - The biological question
   - The technical approach
   - What's novel about it

2. **Project Horizon:**
   - How long is this project expected to take? (months/years)
   - What is the user's role? (graduate student, postdoc, PI, startup founder)

3. **Initial Risk Sense:**
   - What keeps the user up at night about this project?
   - What's the scariest assumption?

### Phase 2: Comprehensive Assumption Listing

Claude should work with the user to list EVERY assumption the project makes from inception through conclusion. Assumptions fall into two categories:

#### Type A: Assumptions About Biological Reality
These are facts about the world that either are or aren't true. They won't change during the project.

**Examples:**
- New cell types exist beyond what's currently known
- A particular gene regulates the process being studied
- Two proteins physically interact
- A pathway functions in the organism of interest
- The biological effect size is detectable

#### Type B: Assumptions About Technical Capability
These are about whether technology can do what's needed. These CAN change during the project as methods improve.

**Examples:**
- A specific cell type can be isolated
- Sequencing will generate high-quality data
- An assay has sufficient throughput
- Computational analysis can distinguish signal from noise
- Gene editing will work in the system

**Claude should ask:**
1. What must be true about the biology for this to work?
2. What must the technology be able to do?
3. What about the experimental design—what assumptions are built in?
4. What about the analysis—can it deliver what's needed?
5. If everything works, can the findings be validated?
6. Will the findings be interpretable and meaningful?

### Phase 3: Risk Scoring (The Assumption Analysis Table)

For each assumption, Claude should help the user assign two scores:

#### Risk Level (1-5 scale):
- **1** = Very likely to be true/work (>90% confidence)
- **2** = Likely (70-90% confidence)
- **3** = Uncertain (40-70% confidence)
- **4** = Unlikely (10-40% confidence)
- **5** = Very unlikely (<10% confidence)

#### Time to Test (months):
How long before the user will know if this assumption is valid?

**Critical Rules:**
1. Be brutally honest—try to convince oneself of being WRONG, not right
2. Distinguish between biological vs. technical assumptions
3. Consider whether technical assumptions might improve over time
4. Note which assumptions depend on earlier assumptions succeeding

### Phase 4: Risk Profile Evaluation

Once the complete table is ready, Claude should analyze the risk profile:

#### Red Flags to Identify:
1. **The Late High-Risk Problem:** Risk level 4-5 assumption that won't read out until >18 months
2. **The Multiple Miracles:** More than 2-3 assumptions with risk level 4-5
3. **The Dependency Chain:** High-risk assumptions stacked in sequence
4. **The Ostrich Pattern:** Starting with low-risk work while avoiding the high-risk tests

#### Green Lights:
1. **Early Go/No-Go:** Highest-risk assumption testable in <6 months
2. **Multiple Candidates:** Project can succeed with several different outcomes
3. **Graceful Degradation:** If assumption X fails, assumption Y provides alternative path
4. **Risk Distribution:** High-risk assumptions balanced across timeline

**Rule of Thumb:** If you have a risk level 5 assumption three years out, pick another project.

### Phase 5: Risk Mitigation Strategies

For each high-risk assumption (level 4-5), Claude should help develop mitigation strategies:

#### Strategy 1: Move High-Risk Tests Earlier
**Question:** Can a quicker, cruder test be designed that answers most of what's needed?

**Example:** Instead of waiting 2 years to validate a new cell type exists, consider:
- Using existing markers as a proxy
- Testing in a simpler model system first
- Using computational predictions to increase confidence

#### Strategy 2: Multiple Candidates Approach
**Question:** Can multiple candidates be tested in parallel to increase likelihood of success?

**Example:** Instead of:
- Testing one kinase → Test a panel of 10 kinases
- Building one engineered organism → Build and test a library
- Pursuing one therapeutic target → Pursue 3 related targets

#### Strategy 3: Reframe the Question
**Question:** Can the project scope be adjusted to reduce critical assumptions while maintaining impact?

**Example from lecture:**
- **Original:** Identify NEW enteroendocrine cell types (high risk: they may not exist)
- **Reframed:** Better characterize KNOWN but incompletely understood cell types (lower risk)

#### Strategy 4: Change the System
**Question:** Is there a different biological system with similar scientific value but lower technical risk?

**Example from lecture:**
- **Original:** Intestinal epithelium (hard to manipulate genetically)
- **Alternative:** Liver (easier genetic manipulation options exist)

#### Strategy 5: Add Complementary Approaches
**Question:** Can a parallel approach be added that de-risks the main assumption?

**Example from lecture:**
- Add spatial transcriptomics to scRNA-seq
- This provides biogeographic context and validates cell type existence earlier

### Phase 6: Go/No-Go Experiment Design

For the top 3 highest-risk assumptions, Claude should help design the critical go/no-go experiments:

**For each, specify:**
1. **The Question:** Exactly what is being tested?
2. **The Experiment:** Most direct test possible (even if crude)
3. **Success Criteria:** What result means "go"?
4. **Failure Response:** What result means "pivot" or "stop"?
5. **Timeline:** How soon can this be run?
6. **Resources:** What is needed?

**Key Principle:** Cut right to the critical go/no-go experiment. Don't just start with easy stuff—the risk points aren't going away.

### Phase 7: Literature Validation

Claude should search PubMed to help calibrate risk assessments:

**Search for:**
1. **Precedents:** Has anyone done something similar? (Reduces technical risk)
2. **Biological Evidence:** What's known about the system? (Informs biological risk)
3. **Technical Benchmarks:** How well do the methods work in practice?
4. **Adjacent Successes:** Has anyone solved related problems?

**Questions to ask the user:**
- What specific searches would help calibrate risk?
- Are there particular papers that informed the assumptions?
- Are there technical benchmarks to look up?

### Phase 8: Revised Project Plan

Based on the risk analysis, Claude should help create a revised plan:

#### Option A: De-Risk the Current Plan
- Reorder experiments to test high-risk assumptions early
- Add complementary approaches
- Design multiple-candidate strategies

#### Option B: Reframe the Project
- Adjust scope while maintaining impact
- Change biological system
- Modify technical approach

#### Option C: Pick a Different Project
Sometimes the honest answer is: "This has too many miracles." That's valuable to know BEFORE investing years.

## Output Deliverable

Claude should produce a **2-page Risk Assessment Document**:

### Page 1: Assumption Analysis Table

| Assumption | Type* | Risk† | Time‡ | Notes |
|------------|-------|-------|-------|-------|
| [Assumption 1] | Bio/Tech | 1-5 | X mo | [Rationale for score] |
| [Assumption 2] | Bio/Tech | 1-5 | X mo | [Rationale for score] |
| ... | ... | ... | ... | ... |

*Bio = Biological reality, Tech = Technical capability  
†Risk: 1=very likely to 5=very unlikely  
‡Time to test in months

#### Risk Profile Summary:
- **Total Assumptions:** X
- **High Risk (4-5):** X assumptions
- **Late High Risk (>18mo):** X assumptions
- **Critical Path:** [Identify the chain of dependent assumptions]
- **Overall Assessment:** [Green/Yellow/Red light with explanation]

### Page 2: Risk Mitigation Plan

#### Top 3 High-Risk Assumptions:
For each:
1. **The Assumption:** [Stated clearly]
2. **Current Risk Level & Timeline:** X (risk) at Y months
3. **Why This Risk Exists:** [Explanation]
4. **Mitigation Strategy:** [From Strategies 1-5 above]
5. **Go/No-Go Experiment:**
   - Experiment design
   - Success criteria
   - Timeline
   - What you'll do if it fails

#### Revised Project Timeline:
```
Month 0-6:   [Early go/no-go experiments]
Month 6-12:  [Based on go/no-go results]
Month 12-18: [...]
Month 18+:   [...]
```

#### Contingency Plans:
- **If assumption X fails:** [Plan B]
- **If assumption Y fails:** [Plan C]
- **Multiple success paths:** [How project can succeed different ways]

#### Decision Points:
- **Month X:** Evaluate [assumptions A, B] → Go/Pivot/Stop decision
- **Month Y:** Evaluate [assumptions C, D] → Go/Pivot/Stop decision

## Practical Examples

### Example 1: ScRNA-Seq for Enteroendocrine Cells

**High-Risk Assumptions Identified:**
1. "New cell types can be validated experimentally" (Risk 5, 24 months)
2. "Knockout will yield biologically relevant phenotype" (Risk 5, 30 months)

**Problem:** Two risk-5 assumptions at 24+ months = RED FLAG

**Mitigation Applied:**
- Reframe to study known but poorly characterized cells (reduces Risk 5→3)
- Switch to liver instead of intestine (improves validation timeline: 30→18 months)
- Add spatial transcriptomics (provides earlier validation checkpoint at 16 months)

### Example 2: Bacterial Therapy for Chronic Kidney Disease

**High-Risk Assumption Identified:**
"Key uremic toxins leading to effects can be determined" (Risk 4, unknown timeline)

**Problem:** Critical assumption with unclear path to resolution

**Mitigation Applied:**
- Focus on known lead toxins (IS and PCS) rather than discovering new ones
- Add parallel track: test multiple toxin candidates
- Design study where learning toxin identity IS the outcome (multiple success paths)

## Key Principles to Remember

1. **Try to Convince Yourself You're Wrong:** The goal is critical evaluation, not confirmation bias.

2. **Ignore Everything But Key Risk Points:** Don't get distracted by easy tasks. The high-risk assumptions aren't going away.

3. **Early and Often:** Design go/no-go experiments at the earliest feasible moment.

4. **Be Candid About Risk:** When presenting ideas, acknowledging risk makes your case MORE convincing, not less.

5. **No Risk, No Interest:** The goal isn't zero risk—it's understood, quantified, manageable risk.

6. **Risk Can Change:** Technical assumptions may improve as methods advance. Build this into your planning.

7. **Compare Risk Profiles:** Evaluate multiple projects in parallel to compare risk profiles and make better choices.

8. **Watch for the Ostrich Pattern:** Are you avoiding the scary experiment? That's human nature, but a critical failure mode.

## Warning Signs

**Warning signs include:**
- Risk level 5 assumptions >2 years out
- More than 3 assumptions at risk level 4-5
- Highest-risk assumptions at the END of the timeline
- Rationalizing why high-risk assumptions will "probably work out"
- Planning to "start with the easy stuff" while avoiding risk tests
- Inability to articulate clear go/no-go criteria

**Good shape indicators:**
- Highest-risk tests happen in first 6 months
- Multiple paths to success exist
- Clear plans for what to do if key assumptions fail
- Risk is distributed across the timeline
- Testing assumptions, not confirming hopes

## Getting Started

Claude should begin with Phase 1 by asking for:
1. The project summary from Skill 1
2. Project timeline expectations
3. What concerns the user most about this project

Together, Claude and the user will build a rigorous risk assessment that dramatically improves the likelihood of success by helping avoid years of work on projects with insurmountable obstacles.

---

*Remember: Spending time on risk analysis is the most valuable investment a scientist can make. A well-understood risk profile enables moving forward with confidence or pivoting with clarity—both are valuable outcomes.*
