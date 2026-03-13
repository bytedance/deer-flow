---
name: ppt-html-generation
description: Use this skill when the user wants to create, generate, or design presentations with editable HTML slides. Produces a JSON artifact containing styled HTML slide fragments with charts, images (via fal.ai), and rich layouts. Unlike ppt-generation (which creates image-based PPTX), this skill generates editable, interactive HTML slides.
allowed-tools:
  - bash
  - read_file
  - write_file
  - present_files
---

# PPT HTML Generation Skill

## CRITICAL RULES — READ FIRST

1. **This skill generates HTML slides**, not image-based slides. Each slide is an HTML fragment with custom elements (`<slide-settings>`, `<row>`, `<column>`, `<chart>`).
2. **Your ONLY output is a JSON file** written to `/mnt/user-data/outputs/presentation.json`. The frontend renders these as interactive, editable slides.
3. **ALWAYS call `present_files`** after writing the presentation so the frontend can load it.
4. **Use the `generate.py` script** in this skill to generate slides. Do NOT write HTML manually.

## Overview

You are a Presentation Design Expert. Your job is to create professional, visually rich presentations by planning slide content and calling the generation script. The script handles:
- LLM-based HTML slide generation with theme-aware prompts
- fal.ai image generation for slide images and backgrounds
- Visual identity expansion for consistent styling across slides

## Workflow

### Step 1: Understand Requirements

Identify from the user's request:
- **Topic**: What the presentation is about
- **Slide count**: How many slides (default: 5-8)
- **Style**: dark-premium, glassmorphism, gradient-modern, editorial, minimal-swiss, keynote, neo-brutalist, 3d-isometric
- **Theme colors**: Background, text, and accent colors
- **Fonts**: Title and body fonts (default: Inter)

### Step 2: Create the Plan

Write the presentation outline to a JSON file (e.g., `/mnt/user-data/workspace/presentation-plan.json`) using the `write_file` tool.

The format MUST be:
```json
{
  "title": "Presentation Title",
  "theme": { ... },
  "imageOptions": { ... },
  "slides": [
    {
      "type": "title",
      "content": "# Welcome\n\nSubtitle here"
    }
  ]
}
```

### Step 3: Generate Slides

Run the script passing the file path to the `--plan` argument:

```bash
python /mnt/skills/public/ppt-html-generation/scripts/generate.py \
  --action generate \
  --plan /mnt/user-data/workspace/presentation-plan.json \
  --output /mnt/user-data/outputs/presentation.json
```

The script will:
1. Expand the theme into a visual identity description
2. Generate HTML for each slide using the LLM
3. Find `data-prompt` attributes in the HTML and generate images via fal.ai
4. Write the complete presentation JSON

### Step 4: Present

```bash
present_files ["/mnt/user-data/outputs/presentation.json"]
```

### Step 5: Update Existing Slides

To update a presentation with existing slides (template update mode):
1. Use `read_file` to read the current `/mnt/user-data/workspace/presentation-plan.json`.
2. Modify the specific slide's content in the JSON plan while keeping the rest exactly the same.
3. Write the updated JSON back to `/mnt/user-data/workspace/presentation-plan.json`.
4. Run the update script:

```bash
python /mnt/skills/public/ppt-html-generation/scripts/generate.py \
  --action update \
  --plan /mnt/user-data/workspace/presentation-plan.json \
  --existing /mnt/user-data/outputs/presentation.json \
  --output /mnt/user-data/outputs/presentation.json
```

## Style Guide

| Style | Best For | Colors |
|-------|----------|--------|
| **dark-premium** | Executive, luxury brands | Black backgrounds, luminous accents |
| **glassmorphism** | Tech, SaaS, AI products | Frosted glass, vibrant gradients |
| **gradient-modern** | Startups, creative agencies | Bold mesh gradients, fluid transitions |
| **editorial** | Annual reports, thought leadership | Magazine layouts, dramatic typography |
| **minimal-swiss** | Architecture, design firms | Grid-based, Helvetica-inspired |
| **keynote** | Product launches, keynotes | Apple-inspired, cinematic |
| **neo-brutalist** | Edgy brands, Gen-Z | Raw typography, high contrast |
| **3d-isometric** | Tech explainers, SaaS | Clean isometric illustrations |

## HTML Structure Reference

Slides use custom HTML elements:
- `<slide-settings>` — Background, transitions, header/footer
- `<h1>`, `<h2>`, `<h3>` — Headings with `textAlign` attribute
- `<p>` — Paragraphs with `textAlign` attribute
- `<row>` + `<column>` — Grid layouts with `columnwidths`
- `<img>` — Content images with `data-prompt` for AI generation
- `<chart>` — Bar, line, pie charts with `data-chart` JSON
- `<span data-pill>` — Pill/badge labels

## Notes

- The script uses Anthropic Claude (claude-sonnet-4-5-20250929) for HTML generation and fal.ai for image generation
- Theme colors are applied globally — do not hardcode them in slide HTML
- Images are generated via fal.ai and their URLs are inserted into the HTML
- The output JSON contains `title`, `theme`, and `slides` array with `index` and `slide` (HTML) per slide
