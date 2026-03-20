# SKILL: Intuition Pumps for Scientific Problem Ideation

## Overview
This skill helps scientists generate high-quality research ideas by providing systematic prompts ("intuition pumps") and identifying common ideation traps. Based on the framework that most biological and chemical science projects involve **perturbing a system, measuring it, and analyzing the data**, this skill guides users through structured ideation that can significantly impact how they spend years of their career.

## Core Framework

### The Three Pillars of Scientific Work
Research advances generally fall into one of these categories, each with two dimensions:

**PERTURBATION**
- *Logic*: Novel ways to manipulate biological systems (e.g., using CRISPR for deep mutational scanning)
- *Technology*: New tools for manipulation (e.g., developing base editors, creating whole-genome CRISPR libraries)

**MEASUREMENT**  
- *Logic*: Novel applications of existing measurement tools (e.g., using tissue clearing to study liver fibrosis)
- *Technology*: New measurement capabilities (e.g., developing tissue-clearing techniques, super-resolution microscopy)

**THEORY/COMPUTATION**
- *Logic*: Using computational tools to make discoveries (e.g., applying AlphaFold to identify protein functions)
- *Technology*: Building new algorithms or models (e.g., developing machine learning architectures for biological data)

Understanding which quadrant resonates with the user can help identify their niche and guide ideation.

## The Skill Workflow

### Phase 1: Initial Discovery Questions (5-10 minutes)

Before diving into intuition pumps, Claude should gather context by asking the user:

1. **What is the user's general research area or field?** (e.g., immunology, synthetic biology, neuroscience, protein engineering)

2. **What excites the user most about science?**
   - Building new tools/technologies?
   - Discovering fundamental principles?
   - Solving practical problems?
   - Understanding dynamic processes?

3. **What are the user's existing strengths?** (Select all that apply)
   - Specific techniques (please list)
   - Computational skills
   - Access to unique systems/models
   - Domain expertise in a particular area

4. **Current constraints:**
   - Time horizon for this project? (months/years)
   - Resources available?
   - Must it connect to existing work, or can the user start fresh?

5. **On a scale of 1-5, how would the user rate their current idea?**
   - Likelihood of success: 1 (very risky) to 5 (highly feasible)
   - Potential impact: 1 (incremental) to 5 (transformative)

### Phase 2: Applying Intuition Pumps

Based on the user's responses, Claude should guide them through relevant intuition pumps from this list:

#### Intuition Pump #1: Make It Systematic
**Prompt:** Take any one-off perturbation or measurement and make it systematic.

**Examples:**
- Instead of mutating one enzyme, measure kinetic parameters across an entire enzyme family
- Instead of one CRISPR mutant → genome-wide screen with transcriptomic readout
- Instead of imaging one condition → high-throughput imaging across thousands of conditions

**Prompt for User:** What one-off experiment in your field could become a systematic survey?

#### Intuition Pump #2: Identify Technology Limitations
**Prompt:** What are the fundamental limitations of technologies you use? These limitations are opportunities.

**Examples:**
- Microscopy can't resolve beyond diffraction limit → super-resolution microscopy
- DNA synthesis can't make complete genomes → develop assembly methods
- Genetic screens have precise input but imprecise output → develop high-dimensional readouts
- We do single gene KOs but networks are complex → develop combinatorial perturbation methods

**Prompt for User:** What technology limitation frustrates you most? How might you turn that limitation into an opportunity?

#### Intuition Pump #3: The "I Can't Imagine" Test
**Prompt:** I can't imagine a future in which we don't have ____, but it doesn't exist yet.

**Examples:**
- The ability to design highly efficient enzymes like we design other proteins
- The ability to deliver genome editing payloads to any cell type in vivo
- 3D tomographic imaging of live cells at molecular resolution
- Proteome-scale sequencing with the throughput of RNA-seq

**Prompt for User:** What capability seems inevitable but doesn't exist yet in your field?

#### Intuition Pump #4: Static vs. Dynamic Understanding
**Prompt:** We understand biological "parts lists" but rarely understand dynamic processes.

**Key Insight:** Most observations are single-timepoint, single-perturbation format. But biological systems are dynamic—like humans flowing through Grand Central Station or money through financial systems.

**Examples:**
- Understanding growth factor signaling like we understand turning a key in a car engine
- Time-resolved cell atlases with lineage tracing through entire development
- Following metabolite flux through pathways in real-time

**Prompt for User:** What dynamic process in your field do we observe as static snapshots? How might you capture the full temporal or spatial dynamics?

#### Intuition Pump #5: Pick a New Axis
**Prompt:** We almost always use time as the x-axis for dynamic processes. What other coordinate could you use?

**Example:** Instead of time, use "infection progression" markers to enable monitoring asynchronous cells

**Prompt for User:** What non-temporal coordinate could reveal new biology in your system?

#### Intuition Pump #6: Create a Technology Platform
**Prompt:** Instead of answering one question, could you build a platform that enables many questions?

**Examples:**
- Antibodies for intracellular targets (not just extracellular)
- AI that predicts perturbations needed to reach desired cell states
- Universal genome delivery vehicles

**Prompt for User:** What platform would transform how your field asks questions?

#### Intuition Pump #7: Dogs That Don't Bark
**Prompt:** Why doesn't something exist or occur? Absence can be as informative as presence.

**Examples:**
- Why are there no Gram-negative bacteria on human skin?
- Why do some catalytically inactive enzymes persist through evolution?
- Why don't certain cell types exist in certain tissues?

**Prompt for User:** What absence puzzles you in your field?

### Phase 3: Avoiding Common Traps

After generating ideas, we must evaluate them critically. Here are the most common traps:

#### Trap #1: The Truffle Hound
**Warning:** Don't become so good at one system or technique that you fail to ask questions of biological import.

**Bad:** "What is the role of p190 RhoGAP in wing development?"  
**Better:** "How do signaling pathways and cytoskeleton coordinate to control wing development?"

**Self-Check:** Is the question driven by biological curiosity or by what the user is technically capable of?

#### Trap #2: Applying Existing Tool to New System
**Warning:** "Let's use CRISPR in my organism" can be valuable but risks crowding and incrementalism.

**When It Works:** The user is enabling a field that truly needs this capability
**When It Fails:** The tool is already widely applied; the contribution will be incremental

**Self-Check:** Will this tool application open new biological questions, or just extend existing observations? Claude should help the user evaluate this honestly.

#### Trap #3: Jumping on the First Idea
**Warning:** Treating ideas with reverence instead of skepticism. Confirmation bias sets in quickly.

**Better Approach:** Users should treat new ideas like leeches trying to steal their time. Look for the warts. Develop several ideas in parallel and comparison shop.

**Self-Check:** Has the user critically evaluated at least 3-5 alternative approaches?

#### Trap #4: Too Many Fixed Parameters
**Warning:** Fixing too many parameters at the outset creates a poor technique-application match.

**Example of Over-Constraining:** "I will use spatial transcriptomics to study antigen-presenting cell and T cell interactions in the tumor microenvironment."
- This fixes: technique (spatial transcriptomics), cell types, and context
- If any assumption fails, the project fails

**Self-Check:** Has the user fixed more than 2 parameters before starting?

#### Trap #5: Too Few Fixed Parameters
**Warning:** "I want to do impactful work in cell engineering" → paralysis

**Resolution:** Constraints engender creativity. Fix ONE parameter at a time and let creativity flow.

**Self-Check:** Does the user have at least one concrete constraint to work with?

### Phase 4: Literature Integration

To ensure the idea has appropriate scope and hasn't been thoroughly explored, Claude should ask:

1. **What are 2-3 key questions or gaps the idea addresses?**

2. **What should be searched in PubMed to:**
   - Understand the current state of the field?
   - Identify related approaches?
   - Find empirical knowledge from adjacent domains that could inform the approach?

Claude should use PubMed to:
- Assess how general/specific the problem is
- Identify relevant methodological advances
- Find analogous systems or approaches in other fields
- Determine the degree of competition

### Phase 5: Idea Refinement and Output

After working through intuition pumps, avoiding traps, and reviewing literature, Claude should help the user:

1. **Crystallize the Idea:**
   - Biological question
   - Technical approach (perturbation/measurement/theory: logic vs. technology)
   - What's novel about this angle?

2. **Articulate Fixed vs. Floating Parameters:**
   - What MUST remain constant in the approach?
   - What can be flexible if obstacles arise?

3. **Identify Key Assumptions:**
   - What must be true for this to work?
   - Which assumptions are about biology vs. technology capabilities?

4. **Sketch Alternative Paths:**
   - If the primary approach fails, what's Plan B?
   - Can the project be designed to succeed regardless of outcome?

## Output Deliverable

At the end of this skill, Claude should produce a **2-page Problem Ideation Document** containing:

### Page 1: Core Idea
- **Title:** Concise project name
- **The Question:** What biological question is being asked?
- **The Approach:** How will it be answered? (Specify perturbation/measurement/computation: logic vs. technology)
- **What's Novel:** The unique angle
- **Why It Matters:** Potential impact (generality × learning, or technology development)
- **Intuition Pump(s) Used:** Which prompted this idea

### Page 2: Critical Analysis
- **Fixed vs. Floating Parameters:**
  - Fixed: What must stay constant
  - Floating: What can adapt

- **Key Assumptions & Risk Assessment:**
  - Biological assumptions (risk level 1-5)
  - Technical assumptions (risk level 1-5)

- **Traps Avoided:** Which pitfalls were navigated around?

- **Alternative Approaches:** Plan B and Plan C

- **Literature Context:**
  - 3-5 key papers that inform or relate to this work
  - Degree of competition (low/medium/high)
  - The user's edge/advantage

- **Next Steps:** First 3 concrete experiments or analyses

## Key Principles to Remember

1. **Reversal of Polarity:** Treat ideas with skepticism, not reverence. Look for flaws before falling in love.

2. **Comparison Shopping:** Develop multiple ideas in parallel. The act of comparison improves decision-making.

3. **Fix One Parameter at a Time:** Constraints engender creativity, but too many constraints prevent it.

4. **Think in Ensembles:** The user is picking a family of possible projects, not a singular path. Flexibility is essential.

5. **Balance Logic and Technology:** Novel biology can come from new tools OR clever application of existing tools.

6. **Systematic Over One-Off:** High-throughput and systematic approaches often reveal more than single observations.

7. **Dynamic Over Static:** Biological systems are dynamic. How can process be captured rather than snapshot?

## Getting Started

When the user is ready, Claude should guide them through the Phase 1 questions to begin the systematic ideation process. The key message: spending extra time on problem choice is the highest-leverage activity in science. A well-chosen problem executed reasonably well will have more impact than a mediocre problem executed brilliantly.

---

*This skill is based on the problem choice framework developed by Michael A. Fischbach and Christopher T. Walsh, as described in "Problem choice and decision trees in science and engineering" (Cell, 2024).*
