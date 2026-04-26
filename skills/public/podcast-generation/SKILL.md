---
name: podcast-generation
description: Use this skill when the user requests to generate, create, or produce podcasts from text content. Converts written content into a two-host conversational podcast audio format with natural dialogue.
---

# Podcast Generation Skill

## Overview

This skill generates high-quality podcast audio from text content. The workflow includes creating a structured JSON script (conversational dialogue) and executing audio generation through text-to-speech synthesis.

## Core Capabilities

- Convert any text content (articles, reports, documentation) into podcast scripts
- Generate natural two-host conversational dialogue (male and female hosts)
- Synthesize speech audio using text-to-speech
- Mix audio chunks into a final podcast MP3 file
- Support both English and Chinese content

## Workflow

### Step 1: Understand Requirements

When a user requests podcast generation, identify:

- Source content: The text/article/report to convert into a podcast
- Language: English or Chinese (based on content)
- Output location: Where to save the generated podcast
- You don't need to check the folder under `/mnt/user-data`

### Step 2: Create Structured Script JSON

Generate a structured JSON script file in `/mnt/user-data/workspace/` with naming pattern: `{descriptive-name}-script.json`

The JSON structure:
```json
{
  "locale": "en",
  "lines": [
    {"speaker": "male", "paragraph": "dialogue text"},
    {"speaker": "female", "paragraph": "dialogue text"}
  ]
}
```

### Step 3: Execute Generation

Call the Python script:
```bash
python /mnt/skills/public/podcast-generation/scripts/generate.py \
  --script-file /mnt/user-data/workspace/script-file.json \
  --output-file /mnt/user-data/outputs/generated-podcast.mp3 \
  --transcript-file /mnt/user-data/outputs/generated-podcast-transcript.md
```

Parameters:

- `--script-file`: Absolute path to JSON script file (required)
- `--output-file`: Absolute path to output MP3 file (required)
- `--transcript-file`: Absolute path to output transcript markdown file (optional, but recommended)

> [!IMPORTANT]
> - Execute the script in one complete call. Do NOT split the workflow into separate steps.
> - The script handles all TTS API calls and audio generation internally.
> - Do NOT read the Python file, just call it with the parameters.
> - Always include `--transcript-file` to generate a readable transcript for the user.

## Script JSON Format

The script JSON file must follow this structure:

```json
{
  "title": "The History of Artificial Intelligence",
  "locale": "en",
  "lines": [
    {"speaker": "male", "paragraph": "Hello Deer! Welcome back to another episode."},
    {"speaker": "female", "paragraph": "Hey everyone! Today we have an exciting topic to discuss."},
    {"speaker": "male", "paragraph": "That's right! We're going to talk about..."}
  ]
}
```

Fields:
- `title`: Title of the podcast episode (optional, used as heading in transcript)
- `locale`: Language code - "en" for English or "zh" for Chinese
- `lines`: Array of dialogue lines
  - `speaker`: Either "male" or "female"
  - `paragraph`: The dialogue text for this speaker

## Script Writing Guidelines

When creating the script JSON, follow these guidelines:

### Format Requirements
- Only two hosts: male and female, alternating naturally
- Target runtime: approximately 10 minutes of dialogue (around 40-60 lines)
- Start with the male host saying a greeting that includes "Hello Deer"

### Tone & Style
- Natural, conversational dialogue - like two friends chatting
- Use casual expressions and conversational transitions
- Avoid overly formal language or academic tone
- Include reactions, follow-up questions, and natural interjections

### Content Guidelines
- Frequent back-and-forth between hosts
- Keep sentences short and easy to follow when spoken
- Plain text only - no markdown formatting in the output
- Translate technical concepts into accessible language
- No mathematical formulas, code, or complex notation
- Make content engaging and accessible for audio-only listeners
- Exclude meta information like dates, author names, or document structure

## Podcast Generation Example

User request: "Generate a podcast about the history of artificial intelligence"

Step 1: Create script file `/mnt/user-data/workspace/ai-history-script.json`:
```json
{
  "title": "The History of Artificial Intelligence",
  "locale": "en",
  "lines": [
    {"speaker": "male", "paragraph": "Hello Deer! Welcome back to another fascinating episode. Today we're diving into something that's literally shaping our future - the history of artificial intelligence."},
    {"speaker": "female", "paragraph": "Oh, I love this topic! You know, AI feels so modern, but it actually has roots going back over seventy years."},
    {"speaker": "male", "paragraph": "Exactly! It all started back in the 1950s. The term artificial intelligence was actually coined by John McCarthy in 1956 at a famous conference at Dartmouth."},
    {"speaker": "female", "paragraph": "Wait, so they were already thinking about machines that could think back then? That's incredible!"},
    {"speaker": "male", "paragraph": "Right? The early pioneers were so optimistic. They thought we'd have human-level AI within a generation."},
    {"speaker": "female", "paragraph": "But things didn't quite work out that way, did they?"},
    {"speaker": "male", "paragraph": "No, not at all. The 1970s brought what's called the first AI winter..."}
  ]
}
```

Step 2: Execute generation:
```bash
python /mnt/skills/public/podcast-generation/scripts/generate.py \
  --script-file /mnt/user-data/workspace/ai-history-script.json \
  --output-file /mnt/user-data/outputs/ai-history-podcast.mp3 \
  --transcript-file /mnt/user-data/outputs/ai-history-transcript.md
```

This will generate:
- `ai-history-podcast.mp3`: The audio podcast file
- `ai-history-transcript.md`: A readable markdown transcript of the podcast

## Specific Templates

Read the following template file only when matching the user request.

- [Tech Explainer](templates/tech-explainer.md) - For converting technical documentation and tutorials

## Output Format

The generated podcast follows the "Hello Deer" format:
- Two hosts: one male, one female
- Natural conversational dialogue
- Starts with "Hello Deer" greeting
- Target duration: approximately 10 minutes
- Alternating speakers for engaging flow

## Output Handling

After generation:

- Podcasts and transcripts are saved in `/mnt/user-data/outputs/`
- Share both the podcast MP3 and transcript MD with user using `present_files` tool
- Provide brief description of the generation result (topic, duration, hosts)
- Offer to regenerate if adjustments needed

## Requirements

The following environment variables must be set:
- `VOLCENGINE_TTS_APPID`: Volcengine TTS application ID
- `VOLCENGINE_TTS_ACCESS_TOKEN`: Volcengine TTS access token
- `VOLCENGINE_TTS_CLUSTER`: Volcengine TTS cluster (optional, defaults to "volcano_tts")

## Notes

- **Always execute the full pipeline in one call** - no need to test individual steps or worry about timeouts
- The script JSON should match the content language (en or zh)
- Technical content should be simplified for audio accessibility in the script
- Complex notations (formulas, code) should be translated to plain language in the script
- Long content may result in longer podcasts
