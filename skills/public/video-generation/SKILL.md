---
name: video-generation
description: Use this skill when the user requests to generate, create, animate, or produce videos. Handles all video creation workflows including text-to-video, image-to-video, product animation, character consistency, scene continuation, looping, and multi-clip production. Uses Seedance v1.5 by default, Kling 3.0 as mid-tier, Veo 3.1 for premium/dialogue.
---

# Video Generation Skill

## Overview

This skill generates high-quality videos through a structured, phased workflow. Video generation is expensive and slow — the workflow is designed to minimize wasted generations by confirming intent, generating reference frames first, and showing users what they'll get before burning API credits.

**Default model: Seedance v1.5** (most affordable). Upgrade to Kling 3.0 or Veo 3.1 only when the use case demands it.

---

## Model Selection

| Model | Flag | Cost | Best For |
|-------|------|------|----------|
| **Seedance v1.5** | `--model seedance` | ~$0.26/5s | Default. Text-to-video, image-to-video, product animation, loops |
| **Kling 3.0** | `--model kling` | Mid | Higher fidelity motion, 5s or 10s, complex scenes |
| **Veo 3.1** | `--model veo3` | Highest | On-screen dialogue/lip-sync, premium quality, always has audio |

**Model selection rules:**
- Use Seedance unless user explicitly requests Kling, Veo3, or dialogue/lip-sync
- Veo 3.1 is **required** when user wants a character to speak on-screen (lip-sync)
- Kling is a good middle ground when user wants "cinematic" or "high quality" without needing dialogue

---

## Audio

| Model | Audio Default | Control |
|-------|--------------|---------|
| Seedance v1.5 | ON by default | `--no-audio` to disable |
| Kling 3.0 | ON by default | `--no-audio` to disable |
| Veo 3.1 | Always ON | Control via prompt text only |

For **ElevenLabs sound effects** (post-generation): described in Phase 5 below.

---

## Workflow Phases

```
Phase 1: Clarify Intent          → Gather requirements, STOP for confirmation
Phase 2: Plan                    → Define style, clips, camera, elements
Phase 3: Generate Reference Frame → Show user the starting frame BEFORE generating video
Phase 4: Generate Video          → Execute with confirmed frame
Phase 5: Post-Processing         → Sound effects, looping, scene continuation
```

**Why phases matter:** Video generation costs real money and takes 1-3 minutes per clip. Never generate a video without first showing the user what the starting frame looks like.

---

## Phase 1: Clarify Intent

### MANDATORY STOP — Ask Before Doing Anything

Before planning anything, ask the user these questions. Do not assume answers.

**Core questions (always ask):**
1. What should happen in the video? (subject, action, mood)
2. How long? (4–12s for Seedance, 5 or 10s for Kling)
3. Aspect ratio? (16:9, 9:16, 1:1, etc.)
4. Do you have a reference image, product photo, or character photo to use?
5. Is this a single clip or part of a longer multi-clip video?

**Ask when relevant:**
- "Do you want the character to speak?" → Veo3 required
- "Do you want to loop this video?" → Same start/end frame technique
- "Do you want to continue from a previous clip?" → Scene continuation
- "Is this a product animation?" → Determines camera movement style
- "Do you want sound effects added after generation?" → ElevenLabs post-processing
- "Do you want consistent characters across multiple clips?" → Reference image workflow

> **[MANDATORY STOP]** Summarize your understanding and wait for user confirmation before proceeding to Phase 2.

---

## Phase 2: Plan

### 2A. Visual Style

Define clearly before any generation:

| Field | Example |
|-------|---------|
| Sub-genre | Cinematic live-action, anime, product commercial, documentary |
| Color & lighting | Warm golden hour, cool blue studio, high contrast noir |
| Camera energy | Slow and deliberate, handheld urgent, smooth drone glide |
| Pacing | Slow / moderate / fast |

### 2B. Recurring Elements

For each character, product, or environment that appears in multiple clips:

| Field | Description |
|-------|-------------|
| identifier | Name used to reference this element |
| appearance | Detailed text description |
| reference_image | Path to uploaded or generated reference image |

### 2C. Per-Clip Specification

For each clip, define:

| Field | Values/Notes |
|-------|-------------|
| duration | 4–12s (Seedance), 5 or 10s (Kling) |
| camera_movement | See Camera Movement Dictionary below |
| camera_speed | slow / moderate / fast / very_fast |
| subject_action | What the subject does during the clip |
| start_state | Subject/scene state at frame 0 |
| end_state | Subject/scene state at final frame — must differ from start_state |
| transition_description | 2–4 sentence detailed description of what happens (see requirements below) |
| audio_type | embedded / none / elevenlabs_sfx |
| dialogue | Text + character name (Veo3 only) |
| loop | yes / no |
| scene_continuation | yes / no (continues from previous clip's last frame) |

### transition_description Requirements

This field becomes the core of the video prompt. **One-liners produce poor results.**

Must include:
1. **Subject appearance** — key visual features that must stay consistent
2. **Movement trajectory** — how subject and/or camera moves through space
3. **State change** — what changes between start and end (pose, position, expression, state)
4. **Existence statements** — what is present throughout (prevents pop-in/pop-out)

| Insufficient | Sufficient |
|--------------|------------|
| "Person walks left" | "Woman in white dress enters from left edge of frame, walks steadily rightward at moderate pace, maintaining upright posture. Her brown hair flows slightly as she moves. She reaches the center of frame by the midpoint, and exits right edge by clip end." |
| "Product rotates" | "Black ceramic coffee mug sits on white marble surface. Camera arcs 360 degrees around the mug in a smooth slow orbit, staying at eye level. The mug remains perfectly centered throughout. Studio lighting creates consistent soft highlights on the mug surface as the camera rotates." |
| "Box opens" | "Closed cream-colored gift box sits centered on velvet surface. Elegant hands with manicured nails enter from bottom of frame and grasp the lid. The lid lifts smoothly upward, revealing a frosted glass jar nestled in champagne-colored tissue paper inside. The jar is visible from the first moment the lid begins to rise." |

### Camera Movement Dictionary

Use these precise descriptions in prompts for each movement type:

| Use Case | camera_movement | Prompt Language |
|----------|----------------|-----------------|
| Product 360° orbit | arc | "Camera arcs 360 degrees around the [product] in a smooth slow orbit, subject centered throughout" |
| Slow reveal | dolly_in | "Camera dollies slowly forward toward [subject], gradually filling the frame" |
| Following subject | tracking | "Camera tracks [subject] from behind/side, maintaining consistent distance as they move" |
| Establishing shot | drone_descend | "Camera descends slowly from high aerial view down to eye level, revealing [scene]" |
| Subtle life | handheld_subtle | "Very subtle handheld movement, barely perceptible breathing of the camera, subject mostly static" |
| Dramatic reveal | crane_up | "Camera cranes upward from low angle, revealing [scene] expanding above" |
| Static hero shot | static | "Camera completely static, locked off tripod shot" |
| Tension building | zoom_slow | "Slow digital zoom in on [subject], increasing from medium to close-up over clip duration" |

### Camera Speed Guidance

Map user language to prompt engineering:

| User Says | Prompt Language |
|-----------|----------------|
| "subtle / barely moving" | "imperceptibly slow movement, gentle drift" |
| "slow / relaxed" | "slow deliberate movement" |
| "normal" | "moderate pace" |
| "fast / dynamic" | "fast energetic movement" |
| "very fast / whip" | "rapid whip-like motion, high kinetic energy" |

---

## Phase 3: Generate Reference Frame

**MANDATORY before any video generation.** Show the user what frame 0 looks like.

### Why This Phase Exists

Video models are expensive (minutes of compute, real dollars). If the user doesn't like the scene, character, or environment, you find out now for a fraction of the cost.

### 3A. Consistency Strategy — Choose One

**Option A: User provides reference image**
- Use their photo as the reference for image-to-video
- No need to generate a reference frame; proceed to Phase 4

**Option B: Generate reference frame with image skill**
- Use the image-generation skill to create the starting frame
- Apply the visual style from Phase 2
- Use 16:9 or 9:16 (same as target video aspect ratio)
- Include: style, scene environment, subject appearance, framing
- Prompt ends with: "no text, no watermarks, no logos, no annotations"

**Option C: Character consistency with NanoBanana (multi-clip projects)**
- When user needs the same character across multiple clips
- Generate a character reference sheet first (full body + face close-up)
- Use reference sheet as input for all subsequent keyframe generations
- This is the primary consistency technique for Seedance and Kling

**Option D: Veo3 Ingredients (Veo3 only)**
- Pass reference images as `referenceImages` with `referenceType: "asset"`
- Veo3 will use these as style/character anchors
- Best for when user has existing product photos or character art

### 3B. Generate & Confirm

1. Generate reference frame
2. Show it to the user with `present_files`
3. Ask: "Does this look right? Any changes before I generate the video?"
4. Iterate on the frame if needed (much cheaper than iterating on video)
5. Only proceed to Phase 4 after explicit user confirmation

---

## Phase 4: Generate Video

### 4A. Prompt Construction

Build the video prompt as a structured natural language string:

```
[Visual style brief] + [Pacing] + [transition_description] + [Subject appearance] + [Camera movement + speed] + [Audio description]
```

**Example (product animation):**
```
"Cinematic commercial style. Slow, deliberate pacing. A sleek black ceramic coffee mug sits on a white marble surface. Camera arcs 360 degrees around the mug in a smooth slow orbit, staying at eye level. The mug remains perfectly centered throughout. Studio lighting creates consistent soft highlights. No background music. Sound of quiet ambient studio."
```

**Example (character walking, handheld):**
```
"Documentary-style realism. Moderate pacing. A young woman in a beige trench coat enters from the left side of a busy Tokyo street. She walks steadily rightward through the crowd, her dark hair slightly windswept. Camera follows her at shoulder height with gentle handheld movement. She glances sideways at a shop window mid-clip. Ambient city sounds, crowd murmur, footsteps on pavement."
```

**Example (dialogue, Veo3):**
```
"Cinematic close-up. Static camera. A man in his 40s with salt-and-pepper stubble sits at a coffee shop table. He looks directly at camera and says: 'The best ideas come when you least expect them.' Warm coffeehouse ambience, soft jazz in background, genuine confident tone."
```

### 4B. Execute Generation

**Save prompt to JSON first:**

```json
{
  "prompt": "[full natural language prompt constructed above]",
  "style": "[visual style]",
  "subject": "[subject description]",
  "camera": "[camera movement and speed]",
  "audio": "[audio description]"
}
```

Save to `/mnt/user-data/workspace/{descriptive-name}.json`

**Run generation script:**

```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/prompt-file.json \
  --reference-images /path/to/reference-frame.jpg \
  --output-file /mnt/user-data/outputs/output-video.mp4 \
  --aspect-ratio 16:9 \
  --model seedance \
  --duration 5
```

**Parameters:**
- `--prompt-file`: Required. Path to JSON prompt file.
- `--reference-images`: Optional. Triggers image-to-video when provided.
- `--output-file`: Required. Output path.
- `--aspect-ratio`: Seedance: 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 | Kling: 16:9, 9:16, 1:1
- `--model`: `seedance` (default) | `kling` | `veo3`
- `--duration`: Seedance: 4–12 | Kling: 5 or 10
- `--no-audio`: Disable audio (Seedance/Kling only)

> Do NOT read the python file. Just call it with the correct parameters.

### 4C. Special Generation Modes

**Loop Video (seamless loop):**
- Strategy: Use the same image as both start frame reference and end frame anchor
- In the prompt: "The video ends exactly where it begins, creating a seamless loop. [Subject] completes a full cycle of motion and returns to starting position/state."
- Works best with: product rotation, breathing animations, ambient environment, spinning objects

**Scene Continuation (continuous story):**
- Extract the last frame of the previous video as an image
- Use that extracted frame as `--reference-images` for the next clip
- In the prompt: "This scene continues directly from the previous shot. The [subject] is already in the position shown in the reference image and continues their action from that point."
- Use `ffmpeg` to extract last frame:
  ```bash
  ffmpeg -sseof -0.1 -i /mnt/user-data/outputs/clip1.mp4 -frames:v 1 /mnt/user-data/workspace/clip1_lastframe.jpg
  ```

**Start + End Frame Control:**
- Generate both a start frame and end frame as images
- Pass start frame as `--reference-images`
- Include end frame description explicitly in transition_description
- Note: Seedance and Kling accept only a start frame; describe the end state in the prompt

---

## Phase 5: Post-Processing

### 5A. ElevenLabs Sound Effects

When user wants sound effects added to a generated video:

1. Generate the video first (no audio, or with audio as base)
2. Identify the sound effects needed (e.g., "coffee being poured", "footsteps on gravel", "crowd applause")
3. Use ElevenLabs Sound Effects API to generate each effect:
   ```bash
   curl -X POST https://api.elevenlabs.io/v1/sound-generation \
     -H "xi-api-key: $ELEVENLABS_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"text": "coffee being poured into a ceramic mug", "duration_seconds": 3}' \
     --output /mnt/user-data/workspace/sfx_coffee.mp3
   ```
4. Mix the sound effect onto the video with ffmpeg:
   ```bash
   ffmpeg -i /mnt/user-data/outputs/video.mp4 \
     -i /mnt/user-data/workspace/sfx_coffee.mp3 \
     -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.8" \
     -c:v copy /mnt/user-data/outputs/video_with_sfx.mp4
   ```

### 5B. Video Stitching (Multi-Clip)

When assembling multiple clips into a single video:

```bash
# Create concat list
echo "file '/mnt/user-data/outputs/clip1.mp4'" > /mnt/user-data/workspace/concat_list.txt
echo "file '/mnt/user-data/outputs/clip2.mp4'" >> /mnt/user-data/workspace/concat_list.txt
echo "file '/mnt/user-data/outputs/clip3.mp4'" >> /mnt/user-data/workspace/concat_list.txt

# Concatenate
ffmpeg -f concat -safe 0 -i /mnt/user-data/workspace/concat_list.txt \
  -c copy /mnt/user-data/outputs/final_video.mp4
```

---

## Edge Case Handling Reference

| User Situation | Approach |
|----------------|----------|
| "Generate me a teacher in class" (no reference) | Phase 3 mandatory — generate reference frame first, confirm before video |
| Product photo → animation | Use product photo as `--reference-images`, arc camera movement |
| 360° product spin | `camera_movement: arc`, "Camera arcs 360 degrees around product, centered throughout, slow orbit" |
| Very fast camera / kinetic | "rapid whip-like motion, high kinetic energy, dynamic frame" |
| Subtle ambient movement | `handheld_subtle`, "imperceptibly slow movement, barely perceptible" |
| Character speaks on-screen | **Must use Veo3.** Include dialogue in prompt: `"Character says: '[text]'"` |
| Seamless loop | Same image as start + "completes full cycle, returns to starting state" in prompt |
| Continue from previous scene | Extract last frame with ffmpeg, use as start frame for next generation |
| Consistent character across clips | Generate character reference sheet, use as `--reference-images` in all clips |
| Add sound effects post-generation | ElevenLabs Sound Effects API → ffmpeg mix |
| User unsure what to generate | Always ask: subject, mood, duration, aspect ratio before anything |
| User dislikes the video | Re-generate with modified prompt or reference frame — do not change model first |

---

## Cost & Time Awareness

Always set expectations before generation:

| Model | Approx Cost | Approx Time |
|-------|------------|-------------|
| Seedance v1.5 (5s) | ~$0.26 | 60–90s |
| Seedance v1.5 (10s) | ~$0.52 | 2–3min |
| Kling 3.0 (5s) | ~$0.50+ | 60–120s |
| Kling 3.0 (10s) | ~$1.00+ | 2–4min |
| Veo 3.1 | Higher | 3–5min |

For multi-clip projects, tell the user upfront: "This will generate N clips which will take approximately X minutes."

---

## Prompt Engineering per Model

Each model responds differently to the same prompt text. Use these guidelines:

**Seedance v1.5:**
- Responds well to: camera movement instructions, physical descriptions, cinematic language
- Include: motion direction, subject physical details, environment description
- Audio: describe ambient sounds, music style — Seedance will synthesize them

**Kling 3.0:**
- More sensitive to: subject action verbs, emotional tone
- Include: emotional quality of movement, subtle facial expression cues
- Good for: human motion, expressive scenes

**Veo 3.1:**
- Best for: dialogue, lip-sync, complex multi-element scenes
- Include: dialogue in quotes with speaker name, tone of voice, setting details
- Audio: describe everything — dialogue, ambience, music — it all gets rendered
- Reference images as `referenceType: "asset"` for character/product consistency

---

## Output

After generation:
1. Present the video with `present_files` (video first, reference image second if applicable)
2. Give a one-line description of what was generated
3. Offer: iterate on prompt, change model, adjust camera, or continue to next scene