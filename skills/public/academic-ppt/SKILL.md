---
name: academic-ppt
description: Use this skill when the user wants to create academic or scientific presentations. Unlike the image-based ppt-generation skill, this skill generates native editable PPTX files using python-pptx with proper text, LaTeX-rendered formulas, academic charts, speaker notes, and reference slides. Supports Beamer-like academic styles, thesis defense presentations, conference talks, research group meetings, and poster-style layouts. Trigger on queries like "academic presentation", "thesis defense PPT", "conference talk slides", "research presentation", or when the user needs editable scholarly slides.
---

# Academic PPT Generation Skill

## Overview

This skill generates **native editable PPTX** presentations optimized for academic use. Unlike the image-based `ppt-generation` skill, this produces real PowerPoint files where text, charts, and formulas are fully editable. It uses `python-pptx` for slide composition and supports LaTeX formula rendering, academic chart embedding, speaker notes, and reference pages.

## When to Use This Skill

**Use THIS skill (academic-ppt) when:**
- User needs an academic/scientific presentation
- User needs editable text content in slides
- User needs LaTeX formulas in slides
- User needs to embed matplotlib/data analysis charts
- User needs speaker notes
- User needs a reference/bibliography slide
- User needs thesis defense or conference talk slides

**Use `ppt-generation` skill instead when:**
- User wants a visually stunning, image-based presentation
- Content is marketing/business focused
- Editability is not a priority

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Editable Content** | All text, titles, and bullet points are native PPTX text objects |
| **Academic Styles** | Clean academic, Beamer-like, thesis defense, conference talk |
| **Formula Support** | LaTeX formulas rendered as high-DPI images and embedded |
| **Chart Embedding** | Embed matplotlib/seaborn charts from statistical analysis |
| **Speaker Notes** | Auto-generated presentation notes for each slide |
| **Reference Slide** | Auto-formatted bibliography slide |
| **Table Support** | Native PPTX tables with academic formatting |
| **Section Dividers** | Clear section break slides for long presentations |
| **Progress Indicators** | Optional slide number / total count |

## Presentation Styles

| Style | Description | Best For |
|-------|-------------|----------|
| **clean-academic** | White background, dark text, minimal decorations, serif headings | Journal club, seminars |
| **beamer-blue** | Blue header bar, structured layout similar to LaTeX Beamer | Conference talks, CS presentations |
| **beamer-red** | Red/maroon header, formal academic feel | Engineering, physics presentations |
| **thesis-defense** | Institution-branded feel, formal structure | Thesis/dissertation defense |
| **research-meeting** | Compact layout, more content per slide | Lab meetings, research discussions |
| **poster-style** | Large font, high contrast, minimal text | Poster presentations |

## Workflow

### Step 0.5: Paper-to-Talk Cognitive Transformation

A presentation is NOT a paper read aloud. Apply these transformations:

**CUT** from paper: lit review details (keep 2-3 refs), proof details (→ backup), most related work (keep closest competitor), implementation details, most ablations (→ backup)

**ADD** (not in paper): a curiosity hook, analogies/intuitive explanations, a demo or live example, a failure case ("what doesn't work" builds trust), a provocative future question

**TRANSFORM**: Abstract → 1-sentence subtitle | Introduction → Hook + Quake setup | Method → visual pipeline + key intuition | Results tables → 1-2 charts with One Number | Discussion → assertion titles | Conclusion → bookend callback

**Inverse Pyramid**: Papers give context first, results last. Great talks can do the opposite — start with the result ("We improved X by 23%"), explain how, then contextualize why. Audience hooks on the result and stays.

### Step 1: Understand Requirements

When a user requests an academic presentation, identify:

| Information | Description | Required |
|------------|-------------|----------|
| **Topic** | Research topic / paper title | Yes |
| **Type** | Conference talk, thesis defense, journal club, seminar | Yes |
| **Duration** | Presentation time (determines slide count) | Recommended |
| **Key Content** | Main sections and key points | Yes |
| **Charts/Figures** | Data visualizations to embed | Optional |
| **Formulas** | Key equations to include | Optional |
| **References** | Bibliography entries | Optional |
| **Style** | Academic style preference | Optional (default: clean-academic) |

### Step 1.3: Audience Adaptation

Adapt depth and structure to your audience:

| Audience | Depth | Jargon | Slides | Focus |
|----------|:-----:|:------:|:------:|-------|
| **Conference (peers)** | Deep | Full technical | 15-20 | Method details + results |
| **Department seminar** | Medium | Moderate | 25-35 | Context + method + implications |
| **Thesis defense** | Very deep | Full | 40-50 | Everything — committee tests depth |
| **Invited talk (broad)** | Shallow | Minimal | 20-30 | Motivation + intuition + impact |
| **Lightning talk** | Surface | Minimal | 5-7 | Hook + one key idea + result |

For technical audiences: start with method, prove it works. For general audiences: start with WHY it matters, show just enough method to build trust.

### Step 1.5: Presentation Narrative Design

A presentation is a performance with a narrative arc. Design the arc BEFORE creating slides.

**5-Act Structure**:

| Act | Slides | Purpose | Audience State |
|:---:|:------:|---------|---------------|
| **1. Hook** | 1-2 | Surprising question, failure case, or bold claim | "This is interesting" |
| **2. Context** | 3-5 | Only what's needed to follow your story | "I understand the problem" |
| **3. Journey** | 5-8 | Your approach — build intuition before details | "I see how this works" |
| **4. Proof** | 3-5 | Key results (not ALL results) | "I'm convinced" |
| **5. Impact** | 1-2 | Why this matters beyond your paper | "I want to learn more" |

Tension should RISE through Acts 1-2, RESOLVE in Act 3, be VALIDATED in Act 4, and ELEVATE in Act 5.

**"Bar Conversation" test**: Can you explain the talk in 3 sentences? Those 3 sentences are Acts 1, 3, and 5.

### Step 1.5.5: Cognitive Earthquake Design

The most memorable talks have ONE moment where the audience's mental model cracks and rebuilds:

**Phase A — Build the Old World** (3-5 slides): Establish current consensus. Audience nods along.
**Phase B — The Quake** (1-2 slides): ONE piece of evidence the old model can't explain. Audience: "Wait..."
**Phase C — The New World** (3-5 slides): YOUR framework explains both old AND new evidence. Audience: "Oh!"

Examples: Jobs → "Phone+iPod+Internet are NOT 3 devices" → ONE device. Attention paper → "RNNs work well" → "But can't attend to distant tokens" → Attention.

Implementation: Make the Quake slide visually distinct (darker background, single large element). Everything before = setup; everything after = payoff.

### Step 1.5.7: Emotional Rhythm

Alternate tension/relief like breathing:

| Block | Emotion | Pace | Density |
|:-----:|---------|:----:|:-------:|
| Hook | Curiosity | Fast | Low — one image |
| Problem | Tension | Medium | Medium |
| Insight | Excitement | **Slow — PAUSE** | Low — one statement |
| Method | Engagement | Medium | Medium-High |
| Results | Satisfaction | Medium | Medium |
| Conclusion | Elevation | Slow | Low — one takeaway |

After every HIGH-density slide, follow with LOW-density (breathing room). Mark 3 deliberate 3-5 second pauses: after Quake, after main result, before final takeaway.

### Step 1.5.9: Bookend Design

End where you began — creating a narrative circle:

- **Opening**: Pose a question, show a failure, or present a challenge
- **Closing**: Return to the SAME element and show the transformation

Example: Open → "GPT-4 gets this math problem wrong 94% of the time." Close → "CalcFormer gets it right."

Design first and last content slides as a visual pair: same layout/colors, KEY element changed (failure → success). **Full Circle Test**: Does the last slide make more sense BECAUSE of the first?

### Step 1.7: Talk-Type Specific Templates

**Conference Talk (15-20 min)**: Title+Hook (1) → Problem (2) → Key Insight (1) → Method Overview (2) → Key Detail (2-3) → Main Results (2) → Analysis/Ablation (2) → Conclusion (1) → Thank You (1) → Backup (5-7 hidden)

**Thesis Defense (45 min)**: Title (1) → Outline (1) → Background (5-7) → Related Work (3-4) → RQs/Hypotheses (1-2) → Full Method (8-12) → Results (8-10) → Discussion (3-4) → Limitations+Future (2) → Conclusion (1-2) → Thank You (1) → Backup (10+)

**Lightning Talk (5 min)**: Hook visual (1) → Insight sentence (1) → How it works diagram (1) → Results — one chart, one number (1) → Takeaway + link (1). No outline, no related work, no detailed method.

### Step 2: Create Presentation Plan

Create a structured plan as a JSON file:

```json
{
  "title": "Research Paper Title",
  "subtitle": "Conference Name / Venue",
  "authors": "Author Name¹, Co-Author Name²",
  "affiliations": "¹University A, ²University B",
  "date": "March 2026",
  "style": "beamer-blue",
  "slides": [
    {
      "slide_number": 1,
      "type": "title",
      "title": "Paper Title",
      "subtitle": "Conference Name 2026",
      "authors": "Author¹, Co-Author²",
      "affiliations": "¹Univ A, ²Univ B",
      "notes": "Welcome everyone. Today I will present our work on..."
    },
    {
      "slide_number": 2,
      "type": "outline",
      "title": "Outline",
      "items": ["Background & Motivation", "Related Work", "Our Approach", "Experiments", "Conclusion"],
      "notes": "Here is the outline of my talk..."
    },
    {
      "slide_number": 3,
      "type": "section",
      "title": "Background & Motivation"
    },
    {
      "slide_number": 4,
      "type": "content",
      "title": "Problem Statement",
      "bullets": [
        "Current methods suffer from X limitation",
        "Existing approaches cannot handle Y scenario",
        "Research gap: No work addresses Z"
      ],
      "notes": "Let me start by explaining the problem..."
    },
    {
      "slide_number": 5,
      "type": "figure",
      "title": "System Architecture",
      "figure_path": "/mnt/user-data/outputs/figures/architecture.png",
      "caption": "Figure 1: Overview of the proposed framework",
      "notes": "This figure shows our system architecture..."
    },
    {
      "slide_number": 6,
      "type": "formula",
      "title": "Loss Function",
      "formula_latex": "\\mathcal{L} = -\\sum_{i=1}^{N} y_i \\log(\\hat{y}_i)",
      "explanation": "Cross-entropy loss for classification",
      "notes": "Our loss function is defined as..."
    },
    {
      "slide_number": 7,
      "type": "table",
      "title": "Experimental Results",
      "headers": ["Method", "Accuracy", "F1", "Latency"],
      "rows": [
        ["Baseline A", "85.2%", "83.1%", "45ms"],
        ["Baseline B", "87.4%", "85.6%", "62ms"],
        ["**Ours**", "**91.3%**", "**89.7%**", "**38ms**"]
      ],
      "notes": "As shown in this table, our method outperforms..."
    },
    {
      "slide_number": 8,
      "type": "two_column",
      "title": "Comparison",
      "left_title": "Previous Work",
      "left_bullets": ["Limitation 1", "Limitation 2"],
      "right_title": "Our Approach",
      "right_bullets": ["Advantage 1", "Advantage 2"],
      "notes": "Compared to previous work..."
    },
    {
      "slide_number": 9,
      "type": "content",
      "title": "Conclusion & Future Work",
      "bullets": [
        "Contribution 1: We proposed...",
        "Contribution 2: We achieved...",
        "Future: We plan to extend..."
      ],
      "notes": "In conclusion..."
    },
    {
      "slide_number": 10,
      "type": "references",
      "title": "References",
      "references": [
        "[1] Author et al. Paper Title. Conference, 2024.",
        "[2] Author et al. Paper Title. Journal, 2023.",
        "[3] Author et al. Paper Title. Conference, 2023."
      ]
    },
    {
      "slide_number": 11,
      "type": "thank_you",
      "title": "Thank You",
      "subtitle": "Questions?",
      "contact": "email@university.edu"
    }
  ]
}
```

### Step 2.3: Slide Typography & Visual Standards

| Element | Size | Weight |
|---------|:----:|:------:|
| Slide title (assertion) | 28-32pt | Bold |
| Subtitle/section | 24pt | Semibold |
| Body text | 20-24pt | Regular |
| Chart labels | 16-18pt | Regular |
| Source/footnote | 12-14pt | Light |
| MINIMUM readable | 16pt | — |

Layout rules: Margins ≥5% on all sides. White space 40-50% of slide. Everything aligned to invisible grid. Same title position, same margins, same fonts on EVERY slide. Maximum 3-4 colors per chart. "Your method" always in the most salient accent color; baselines in muted gray.

### Step 2.5: Assertion-Evidence Slide Model

Replace bullet-point slides with the Assertion-Evidence model (Alley, 2013):

**Traditional** (weak): Title = "Results" → Body = 5 bullet points listing numbers.

**Assertion-Evidence** (strong): Title = full sentence claim ("Our method outperforms all baselines by 4+ points") → Body = one visual evidence (chart with significance brackets).

**Rules**: (1) Title = full sentence assertion, NOT a topic label. (2) Body = visual evidence (chart, diagram, equation), NOT bullets. (3) Max 1 assertion per slide. 2 points = 2 slides. (4) Assertions must be self-contained: reading ONLY slide titles in sequence should tell the complete story.

**Title-Only Storyboard Test**: Write just the titles. Do they tell a story?
- "LLMs fail at elementary arithmetic despite high benchmark scores" ✓
- "We embed a symbolic engine into the attention mechanism" ✓
- "CalcFormer achieves 23.7% improvement on math reasoning" ✓
vs. "Introduction" / "Method" / "Results" ✗ — rewrite these.

### Step 2.5.5: Guided Discovery Method

Don't TELL conclusions — LEAD the audience to discover them. Self-discovered conclusions are 10x more persuasive.

**Traditional** (you tell): Slide title states the conclusion → then data supports it.
**Guided Discovery** (they discover): Slide 1 shows data pattern → Slide 2 zooms into key region → Slide 3 explains WHY → audience felt they figured it out.

**"Question Before Answer" rule**: For every key insight, pose it as a question first, pause 2-3 seconds, then reveal. The pause activates the audience's own reasoning.

### Step 2.7: Cognitive Load Control

Working memory holds ~4 items (Cowan, 2001). Every slide must respect this:

| Element | Maximum |
|---------|:-------:|
| Key messages | 1 per slide |
| Text lines | 4-5 |
| Words per line | 8-10 |
| Data series in chart | 4-5 |
| Colors | 3-4 |
| Total words on slide | 30-40 |

**6-Second Rule**: Audience must grasp the main point within 6 seconds. If longer → simplify.

**Squint Test**: Squint at slide from 2 meters. Can you identify title → main element → detail? If not → fix contrast/sizing.

### Step 2.7.5: Visual Attention Timeline

Design WHERE the audience looks at each moment. Every slide needs ONE clear focal point.

**Attention hierarchy** (what gets noticed first): (1) Largest element → (2) Highest contrast → (3) Most isolated → (4) Motion

**Practical rule**: For each slide, answer: "Eye goes to _____ first, then _____, then _____." If unclear → simplify.

Place assertion title at top (noticed first), visual evidence in center (largest area), source/footnote at bottom-right (noticed last).

### Step 2.9: Analogy Bridging

Bridge complex concepts to familiar ones: "[Complex concept] is like [familiar concept], except [key difference]."

Examples: "Attention is like a spotlight the model points at input parts" / "Dropout is like removing random roads — remaining routes become robust"

Rules: (1) Familiar concept must be universally understood. (2) Mapping must be structurally correct. (3) State limits: "Unlike [analogy], [concept] also [difference]."

**Analogy Slide**: Left = familiar (everyday illustration), Right = your concept (technical diagram), connected by arrow. One sentence: "[Familiar] → [Technical]: [insight]"

### Step 2.8: Structured Speaker Notes

Format per slide:
```
[TIMING: ~1.5 min | Cumulative: 8/15 min]
[TRANSITION]: "So we've seen the problem. Now let me show you our approach."
[MAIN POINTS]: Key phrases for this slide (not a full script)
[POINTER CUE]: → Point to the blue module in diagram
[TRANSITION TO NEXT]: "Now that you have the intuition, let me show the formal definition."
```

Include for every content slide: timing, transition from previous, main talking points, pointer/gesture cues, transition to next.

### Step 3: Generate the PPTX

```bash
pip install python-pptx matplotlib numpy Pillow
```

```bash
python /mnt/skills/public/academic-ppt/scripts/academic_pptx.py \
  --plan-file /mnt/user-data/workspace/presentation-plan.json \
  --output-file /mnt/user-data/outputs/presentation.pptx \
  --style beamer-blue
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--plan-file` | Yes | Path to the presentation plan JSON file |
| `--output-file` | Yes | Path for output PPTX file |
| `--style` | No | Style preset (default: clean-academic) |
| `--widescreen` | No | Use 16:9 aspect ratio (default: true) |

> [!NOTE]
> Do NOT read the Python file, just call it with the parameters.

### Step 4: Embed Charts (Optional)

If the user has generated charts from `statistical-analysis` or `chart-visualization`, reference them in the plan:

```json
{
  "type": "figure",
  "title": "Results Comparison",
  "figure_path": "/mnt/user-data/outputs/figures/roc_curve.png",
  "caption": "Figure 3: ROC curves for all models"
}
```

### Step 4.3: Slide-Optimized Data Visualization

Paper figures ≠ slide figures. Simplify for projection:

| Paper Figure | Slide Adaptation |
|-------------|-----------------|
| 6 baselines in table | Top 2-3 + yours (audience can't process 6) |
| Dense scatter (1000 pts) | Trend line + CI band only |
| Multi-panel (a,b,c,d) | One panel per slide, progressive reveal |
| Complex architecture | Simplified 3-block overview |
| Full results table | Highlight YOUR row, gray out rest |

**"One Number" Rule**: If showing quantitative results, the audience should remember ONE number. Make it the largest text on the slide (e.g., giant "23.7%" with small supporting text).

### Step 4.5: Progressive Reveal

For complex content, build understanding step by step using multiple slides:

- **Architecture**: Slide 1: input → encoder (rest grayed). Slide 2: + attention (rest grayed). Slide 3: full pipeline.
- **Results table**: Slide 1: baseline rows only. Slide 2: reveal your method's row — audience experiences the improvement.
- **Equations**: Slide 1: plain English intuition. Slide 2: the equation. Slide 3: each term highlighted.

Implementation: use multiple slides with incremental content (not PPTX animation — unreliable across platforms). Each "reveal step" = one additional slide with new element highlighted and previous elements present.

### Step 5: Present Output

```bash
# Share the generated presentation
present_files /mnt/user-data/outputs/presentation.pptx
```

### Step 5.5: Backup Slides for Q&A

After "Thank You", always include hidden backup slides anticipating likely questions:

1. **Detailed ablation** — "What if you remove component X?"
2. **Additional datasets** — "Have you tested on Y?"
3. **Computational cost** — "How fast/slow is this?"
4. **Failure cases** — "When does it fail?" (shows intellectual honesty)
5. **Comparison with specific related work** — "How vs. [recent paper]?"
6. **Mathematical details** — Full derivation simplified in main talk
7. **Future work specifics** — Concrete next steps

Label clearly: "Backup: Ablation Details", "Backup: Computational Cost", etc.

## Slide Type Reference

| Type | Description | Required Fields |
|------|-------------|----------------|
| `title` | Title slide with authors/affiliation | `title`, `authors` |
| `outline` | Table of contents / outline | `title`, `items` |
| `section` | Section divider slide | `title` |
| `content` | Bullet point content slide | `title`, `bullets` |
| `figure` | Image/chart slide | `title`, `figure_path` |
| `formula` | LaTeX formula slide | `title`, `formula_latex` |
| `table` | Data table slide | `title`, `headers`, `rows` |
| `two_column` | Two-column comparison | `title`, `left_*`, `right_*` |
| `references` | Bibliography slide | `title`, `references` |
| `thank_you` | Closing slide | `title` |

## Duration Guidelines

| Duration | Recommended Slides | Pace |
|---------|-------------------|------|
| 5 min (lightning talk) | 5-7 slides | ~1 min/slide |
| 15 min (conference talk) | 12-18 slides | ~1 min/slide |
| 20 min (journal club) | 15-25 slides | ~1 min/slide |
| 30 min (seminar) | 25-35 slides | ~1 min/slide |
| 45 min (thesis defense) | 35-50 slides | ~1 min/slide |

## Integration with Other Skills

- **statistical-analysis**: Generate charts → embed as figures in slides
- **academic-writing**: Extract key content from paper sections → create presentation
- **literature-review**: Generate Related Work summary → create background slides
- **chart-visualization**: Create specialized charts → embed in slides
- **data-analysis**: Extract data insights → create results slides

## Notes

- All text in the generated PPTX is editable — users can fine-tune after generation
- LaTeX formulas are rendered as high-resolution images (300 DPI)
- Charts are embedded at their original resolution
- Speaker notes are included for every content slide
- The reference slide auto-formats entries with consistent styling
- For Chinese presentations, all text supports CJK characters
- Slide numbers are automatically added to all slides (except title/thank-you)
