---
name: ppt-generation
description: Use this skill when the user requests to generate, create, or make presentations (PPT/PPTX). Creates either image-based PPTs or text-only PPTs depending on API availability.
---

# PPT Generation Skill

## Overview

This skill supports two PPT generation paths:

- Path A: image-based PPT generation using the `image-generation` skill. This path requires `GEMINI_API_KEY`.
- Path B: text-based PPT generation using `python-pptx`. This path does not require any external API key.

Use Path B whenever `GEMINI_API_KEY` is not available or when the user wants a simple text-only deck.

## Core Rules

1. Do not assume `GEMINI_API_KEY` is configured.
2. Check `GEMINI_API_KEY` first. If it is missing, use Path B.
3. If Path A fails for API-related reasons, fall back to Path B in the same task.
4. Always return a real `.pptx` file to the user.

## Path Selection

Run:

```bash
echo $GEMINI_API_KEY
```

- If the key exists, you may use Path A.
- If the key is empty, use Path B.

## Path A: Image-Based PPT

Use this path only when `GEMINI_API_KEY` is available.

### Step 1

Create a presentation plan JSON in `/mnt/user-data/workspace/` with:

- `title`
- `style`
- `style_guidelines`
- `aspect_ratio`
- `slides`

### Step 2

Generate slide images sequentially with the image-generation skill. Each later slide should reference the previous slide image to keep style consistency.

### Step 3

Compose the final PPT:

```bash
python /mnt/skills/public/ppt-generation/scripts/generate.py \
  --plan-file /mnt/user-data/workspace/presentation-plan.json \
  --slide-images /mnt/user-data/outputs/slide-01.jpg /mnt/user-data/outputs/slide-02.jpg \
  --output-file /mnt/user-data/outputs/presentation.pptx
```

### Step 4

Present the generated file:

```text
present_files(filepaths=["/mnt/user-data/outputs/presentation.pptx"])
```

## Path B: Text-Based PPT Fallback

Use this path by default when `GEMINI_API_KEY` is unavailable.

### Step 1

Create a simple presentation plan JSON in `/mnt/user-data/workspace/presentation-plan.json`.

Required shape:

```json
{
  "title": "Presentation Title",
  "slides": [
    {
      "type": "title",
      "title": "Main Title",
      "subtitle": "Subtitle"
    },
    {
      "type": "content",
      "title": "Slide Title",
      "key_points": ["Point 1", "Point 2", "Point 3"]
    }
  ]
}
```

### Step 2

Generate the text-only PPT:

```bash
python /mnt/skills/public/ppt-generation/scripts/generate_text.py \
  --plan-file /mnt/user-data/workspace/presentation-plan.json \
  --output-file /mnt/user-data/outputs/presentation.pptx
```

### Step 3

Present the generated file:

```text
present_files(filepaths=["/mnt/user-data/outputs/presentation.pptx"])
```

## Output Handling

After generation:

- The PPTX file must exist under `/mnt/user-data/outputs/`.
- Share the PPTX using `present_files`.
- Briefly describe what was generated.
- Offer follow-up edits if the user wants content or styling changes.

## Notes

- Prefer Path B when the environment is uncertain.
- Do not claim success unless a `.pptx` file was actually created.
- Keep Path A and Path B behavior inside this skill rather than moving PPT logic into unrelated middleware or UI code.
