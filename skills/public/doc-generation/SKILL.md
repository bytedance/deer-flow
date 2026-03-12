---
name: doc-generation
description: Use this skill when the user wants to create, generate, or write professional documents, reports, guides, or articles. Produces pixel-perfect HTML documents or structured Markdown files suitable for viewing, editing, and PDF export.
allowed-tools:
  - bash
  - read_file
  - write_file
  - present_files
---

# Document Generation Skill

## CRITICAL RULES — READ FIRST

1. **Your output is a single file** — either HTML (`.html`) or Markdown (`.md`) — written to `/mnt/user-data/outputs/`.
2. **ALWAYS call `present_files`** after writing the document.
3. **Use the `generate.py` script** for generation. Do NOT write documents manually.
4. **For HTML mode**: The output is a static, print-quality HTML document. No JavaScript, no interactivity.
5. **For Markdown mode**: The output is CommonMark-compliant Markdown.

## Overview

You are an elite Document Design Specialist. Your job is to craft professional documents by planning the structure and calling the generation script. The script handles LLM-based content generation with format-specific system prompts.

## Workflow

### Step 1: Understand Requirements

Identify from the user's request:
- **Topic**: What the document is about
- **Format**: HTML (for rich visual documents) or Markdown (for structured text)
- **Type**: Report, guide, article, proposal, memo, whitepaper, etc.
- **Length**: Short (1-2 pages), Medium (3-5 pages), Long (6+ pages)
- **Uploaded files**: Any reference documents to base content on

### Step 2: Create the Plan

Write the document outline to a JSON file (e.g., `/mnt/user-data/workspace/document-plan.json`) using the `write_file` tool.

The format MUST be:
```json
{
  "title": "AI Trends Report 2026",
  "format": "html",
  "style": "professional",
  "sections": [
    {
      "heading": "Executive Summary",
      "instructions": "A brief overview of the AI landscape in 2026..."
    }
  ]
}
```

### Step 3: Generate Document

Run the script passing the file path to the `--plan` argument:

```bash
python /mnt/skills/public/doc-generation/scripts/generate.py \
  --action generate \
  --format html \
  --plan /mnt/user-data/workspace/document-plan.json \
  --output /mnt/user-data/outputs/document.html
```

For Markdown:
```bash
python /mnt/skills/public/doc-generation/scripts/generate.py \
  --action generate \
  --format markdown \
  --plan /mnt/user-data/workspace/document-plan.json \
  --output /mnt/user-data/outputs/document.md
```

### Step 4: Present

```bash
present_files ["/mnt/user-data/outputs/document.html"]
```

### Step 5: Update Existing Document

For targeted updates, **do NOT regenerate the whole document**. Instead, edit the output file directly:

1. **Direct Editing (Preferred):** If the user asks for a specific change (e.g., "rewrite the introduction", "fix a typo", "add a paragraph to market analysis"):
   - Use `read_file` to read the final document (e.g., `/mnt/user-data/outputs/document.html`).
   - Use the `bash` tool (e.g., `sed`) or `write_file` to surgically alter the specific section in the document.
   - Do not touch the plan or `generate.py`.

2. **Full Regeneration (Major Overhauls Only):** If the user asks to fundamentally restructure the document (e.g., "rewrite the entire document in a different tone"):
   - Use `read_file` on `/mnt/user-data/workspace/document-plan.json`.
   - Modify the plan sections.
   - Run `generate.py` again to overwrite the previous document completely.

## Format Guidelines

### HTML Mode
- Pixel-perfect, print-quality documents
- Flat design only — no `box-shadow`, `text-shadow`, or gradients
- No buttons, clickable elements, or hover effects (designed for paper/PDF)
- Use flexbox layouts with percentage widths
- Fixed container width of 816px (US Letter)
- All styles embedded inline or in `<style>` blocks

### Markdown Mode
- CommonMark-compliant Markdown only
- Clear hierarchy using `#`, `##`, `###`
- Bullet lists, numbered lists, task lists
- Tables for structured data
- No HTML tags mixed in

## Notes

- The script uses Anthropic Claude (claude-sonnet-4-5-20250929) for content generation
- For HTML documents, the script supports fal.ai image generation via `data-prompt` attributes
- Images from uploaded files are preserved if URLs are provided in the plan
- The document is generated as a single complete file
