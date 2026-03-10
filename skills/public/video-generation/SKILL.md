---
name: video-generation
description: Use this skill when the user requests to generate, create, or imagine videos. Supports structured prompts and reference image for guided generation. Uses Seedance v1.5 by default (most affordable), Kling 3.0 as mid-tier, or Veo 3.1 for premium quality.
---

# Video Generation Skill

## Overview

This skill generates high-quality videos using structured prompts and a Python script. By default it uses **Seedance v1.5** (via Fal.ai) which is the most affordable and supports text-to-video, image-to-video, and audio generation. Use **Kling 3.0** for mid-tier quality, or **Veo 3.1** for premium quality when explicitly requested.

## Model Selection

| Model | Flag | Cost | API Key | Best For |
|-------|------|------|---------|----------|
| **Seedance v1.5** (default) | `--model seedance` | Lowest (~$0.26/5s) | `FAL_KEY` | Most affordable, 4-12s duration, wide aspect ratio support, audio |
| **Kling 3.0** | `--model kling` | Mid | `FAL_KEY` | Proven quality, 5 or 10s duration, toggleable audio |
| **Veo 3.1** | `--model veo3` | Highest | `GEMINI_API_KEY` | Premium quality, always generates audio, when user explicitly asks |

**Rule: Always use Seedance unless the user specifically mentions Kling, Veo3, Gemini video, or Google video.**

## Audio Generation

All models support generating video with synchronized audio:

- **Seedance v1.5**: Audio is **enabled by default**. Use `--no-audio` to disable. Include sound descriptions in your prompt for best results.
- **Kling 3.0**: Audio is **enabled by default**. Use `--no-audio` to disable. When enabled, include sound descriptions in your prompt for best results (e.g., "birds chirping", "footsteps on gravel", "crowd murmuring").
- **Veo 3.1**: Audio is **always on** (no API toggle). Control audio through the prompt text — describe dialogue, sound effects, and ambient audio directly in the prompt.

## Core Capabilities

- Create structured JSON prompts for AIGC video generation
- Support reference image as guidance (image-to-video with Seedance/Kling, or asset reference with Veo3)
- Text-to-video generation from prompts alone
- Generate videos with synchronized audio (all models)
- Generate videos through automated Python script execution

## Workflow

### Step 1: Understand Requirements

When a user requests video generation, identify:

- Subject/content: What should be in the video
- Style preferences: Art style, mood, color palette
- Technical specs: Aspect ratio, composition, lighting
- Reference image: Any image to guide generation
- Model preference: Use Seedance by default, Kling if requested, Veo3 only if explicitly requested
- Duration: 4-12 seconds (Seedance), 5 or 10 seconds (Kling), default 5
- You don't need to check the folder under `/mnt/user-data`

### Step 2: Create Structured Prompt

Generate a structured JSON file in `/mnt/user-data/workspace/` with naming pattern: `{descriptive-name}.json`

### Step 3: Create Reference Image (Optional when image-generation skill is available)

Generate reference image for the video generation.

- If only 1 image is provided, use it as the guided frame of the video

### Step 4: Execute Generation

Call the Python script:
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/prompt-file.json \
  --reference-images /path/to/ref1.jpg \
  --output-file /mnt/user-data/outputs/generated-video.mp4 \
  --aspect-ratio 16:9 \
  --model seedance \
  --duration 5
```

Parameters:

- `--prompt-file`: Absolute path to JSON prompt file (required)
- `--reference-images`: Absolute paths to reference image (optional). Triggers image-to-video mode for Seedance/Kling.
- `--output-file`: Absolute path to output video file (required)
- `--aspect-ratio`: Aspect ratio of the generated video (optional, default: 16:9). Seedance: 21:9, 16:9, 4:3, 1:1, 3:4, 9:16. Kling: 16:9, 9:16, 1:1.
- `--model`: Video model to use (optional, default: seedance). Options: `seedance`, `kling`, `veo3`
- `--duration`: Video duration in seconds (optional, default: 5). Seedance: 4-12. Kling: 5 or 10.
- `--no-audio`: Disable audio generation (optional, Seedance/Kling only). By default audio is enabled. Veo3 always generates audio.

[!NOTE]
Do NOT read the python file, instead just call it with the parameters.

## Video Generation Example

User request: "Generate a short video clip depicting the opening scene from The Chronicles of Narnia"

Step 1: Search for the opening scene online

Step 2: Create a JSON prompt file:

```json
{
  "title": "The Chronicles of Narnia - Train Station Farewell",
  "background": {
    "description": "World War II evacuation scene at a crowded London train station. Steam and smoke fill the air as children are being sent to the countryside to escape the Blitz.",
    "era": "1940s wartime Britain",
    "location": "London railway station platform"
  },
  "characters": ["Mrs. Pevensie", "Lucy Pevensie"],
  "camera": {
    "type": "Close-up two-shot",
    "movement": "Static with subtle handheld movement",
    "angle": "Profile view, intimate framing",
    "focus": "Both faces in focus, background soft bokeh"
  }
}
```

Step 3: Use the image-generation skill to generate the reference image

Step 4: Generate with Seedance (default):
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/narnia-farewell-scene.json \
  --reference-images /mnt/user-data/outputs/narnia-farewell-scene-01.jpg \
  --output-file /mnt/user-data/outputs/narnia-farewell-scene-01.mp4 \
  --aspect-ratio 16:9 \
  --duration 8
```

Or with Kling:
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/narnia-farewell-scene.json \
  --reference-images /mnt/user-data/outputs/narnia-farewell-scene-01.jpg \
  --output-file /mnt/user-data/outputs/narnia-farewell-scene-01.mp4 \
  --aspect-ratio 16:9 \
  --model kling \
  --duration 10
```

Or if user explicitly requested Veo3:
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/narnia-farewell-scene.json \
  --reference-images /mnt/user-data/outputs/narnia-farewell-scene-01.jpg \
  --output-file /mnt/user-data/outputs/narnia-farewell-scene-01.mp4 \
  --aspect-ratio 16:9 \
  --model veo3
```

> Do NOT read the python file, just call it with the parameters.

## Output Handling

After generation:

- Videos are typically saved in `/mnt/user-data/outputs/`
- Share generated videos (come first) with user as well as generated image if applicable, using `present_files` tool
- Provide brief description of the generation result
- Offer to iterate if adjustments needed

## Notes

- Always use English for prompts regardless of user's language
- JSON format ensures structured, parsable prompts
- Reference image enhance generation quality significantly
- Iterative refinement is normal for optimal results
- Seedance is the default — use Kling if requested, Veo3 only when explicitly asked
- Seedance supports 4-12 second videos; Kling supports 5 or 10 seconds; Veo3 duration is determined by the model
