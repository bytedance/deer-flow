# Commercial Short-Form Ad & Multi-Shot Video Workflow

This is an optional template for commercial product ads, vertical short-form videos (Instagram Reels, TikTok, YouTube Shorts), report-to-video explainers, and 15–30s multi-shot short films. Always preserve the user's requested subject, verified facts, duration, aspect ratio, and target language; do not import placeholder brands or scenes from the worked example into unrelated videos.

## Choose a Production Track

| Track | Best For | Pipeline |
| --- | --- | --- |
| **Track A: Single-Pass 15s Beat-Synced Ad (`9:16`)** | Creator-style product ads with one cohesive continuous arc and native synchronized audio (ideal on BytePlus Agent Plan Seedance 2.5, which supports `4`–`30`s duration and multi-image references) | `scripts/preflight.py` → `scripts/generate.py` (`480p` Flash draft → `720p`/`1080p` Pro final) |
| **Track B: Multi-Shot 15–30s Commercial or Explainer Film** | Multi-scene product stories, Deep Research / PPT-to-video explainers, or providers with shorter per-clip limits | `image-generation` reference keyframes → parallel `scripts/generate.py` clips (via sub-agents when available) → `scripts/stitch.sh` (`ffmpeg` assembly) |

## Step 1: Confirm Inputs Before Writing Prompts

Before drafting prompts, collect any missing items in **one concise numbered message** (skip items the user already provided):

1. **Verified facts**: product name, color, material, and 2–3 key selling points (or key verified claims from the research report/brief — never fabricate specs, prices, or performance claims).
2. **Target market & language**: defaults to **US / English** if unspecified (state the default explicitly).
3. **Scene & action**: e.g., morning run, commute, cafe, studio desk, home. Honor any scene the user specifies instead of substituting unboxing or generic review formats.
4. **Voiceover & CTA**: both default to **off** (no prices, discounts, free-shipping, or urgency claims unless the user supplies exact approved copy).

## Step 2: Safety & Asset Gate (Mandatory)

1. **No unauthorized real faces or third-party IP**: do not use unconsented photos of real people, public figures, named third-party brands/IP, or copyrighted music.
2. **Reference image face check**: inspect user-provided product images before submission. If an image contains an identifiable human face without explicit consent or masking, ask the user for a product-only or face-masked image.
3. **Local image references**: `scripts/generate.py` submits local images via `--reference-images` with recognized extensions (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`).

## Step 3: Track A — 15-Second Beat-Synced Arc (120 BPM, 4/4)

Every bar equals 2 seconds (1 beat = 0.5s). Aim for 6–8 shots with visible motion in the first 2 seconds, at least one product detail macro shot, and a clean 3-second hero hold at the end:

| Time | Bars | Narrative Role | Camera & Visual Guidance |
| --- | --- | --- | --- |
| `0s-2s` | Bar 1 | Scroll-stop hook | Low-angle close-up or macro with immediate motion (foot strike, pour, door push), backlit |
| `2s-4s` | Bar 2 | Scene entry | 35mm medium tracking shot; creator steps into light, establishing environment |
| `4s-8s` | Bars 3–4 | Product in use (two 2s shots) | One active wearing/usage shot + one material/texture macro detail shot |
| `8s-10s` | Bar 5 | Tempo lift (two 1s shots) | Fast rhythmic cuts landing on snare/clap; whip pan or low rhythmic tracking |
| `10s-12s` | Bar 6 | Emotional peak | 85mm shallow DOF medium shot; creator and product share a clean hero frame |
| `12s-15s` | Bars 7–8 | Product hero hold | Clean locked-off product frame + brand caption; music resolves on final downbeat |

If the user asks for a different duration or aspect ratio, honor the user's request and adjust the shot timecodes to match the requested duration.

### Renderable Style Vocabulary

Use concrete, camera-renderable descriptions rather than vague praise:

- **Film stock & grade (pick one, keep constant across the whole film)**:
  - `Kodak Portra 400 warm skin tones, soft highlight roll-off`
  - `Fujifilm Pro 400H pastel greens, lifted shadows`
  - `clean editorial grade, neutral whites, gentle contrast`
- **Focal lengths**: `24mm` low-angle, `35mm` tracking, `50mm` medium close-up, `85mm f/1.4` shallow depth of field, `100mm macro`.
- **Lighting (name a concrete light source in every shot)**: `golden-hour backlight with lens flare`, `soft window light`, `overcast diffused daylight`, `on-camera soft flash`.
- **Camera movement (one move per shot)**: `handheld micro-jitter`, `slow push-in`, `lateral tracking`, `whip pan`, `locked-off`.
- **Performance**: convey mood through physical action (`exhales and looks toward the rising sun`), never abstract labels (`happy expression`).

### Hard Prompt Rules (Enforced by `scripts/preflight.py`)

- **All production directions in English**: the 6 section headers and scene/camera/audio directions must be in English; only `【captions】` and optional spoken dialogue use the target-market language.
- **Plain text only**: save to `/mnt/user-data/workspace/commercial_ad_15s.txt`. Do not wrap `SHOT LIST` lines in Markdown bullets or JSON.
- **Strict 6-section structure**:
  1. `CHARACTER DIRECTION`
  2. `REFERENCE MAP` (`@Image 1`, `@Image 2`, ... matching `--reference-images` order)
  3. `ENVIRONMENT`
  4. `AUDIO DIRECTION` (must declare `SPEECH INVENTORY: ...`)
  5. `SHOT LIST` (contiguous integer timecodes from `0s` to target duration; each line includes `(music cue)`, optional `<SFX>`, and optional `【caption】`)
  6. `CONTINUITY AND PRODUCT CONSISTENCY`
- **Budgets & bans**:
  - Max **3** captions (`【...】`), each <= **6 English words** or <= **10 Chinese characters**.
  - Optional speech: max **18 English words** or <= **35 Chinese characters** total; prefix with `Voiceover:` or `On-camera dialogue (lip-synced):` and omit `{ }` when `SPEECH INVENTORY:` declares 0 speech lines.
  - Zero banned hype adjectives (`epic`, `beautiful`, `stunning`, `amazing`, `masterpiece`, `8K`, `ultra-realistic`, `award-winning`, `emotional`, `happy expression`, `唯美`, `震撼`, `史诗感`, `超高清`, `氛围感拉满`), zero camera brands (`ARRI`, `Alexa`, `Sony FX`, `Canon C300`, `RED Komodo`, `RED V-Raptor`), zero negative music cues (`no music`, `ambient only`, `music fades to silence`), and zero emoji.

### Prompt Template

```text
CHARACTER DIRECTION
[2-3 sentences: new target-market creator; age cues, facial features, approximate height/build, posture, hair, and wardrobe that does not compete with the product.]
REFERENCE MAP
@Image 1 = [role, e.g. product side view / hero color]
@Image 2 = [role, e.g. sole and material detail]
Reference only the product shown in the images; ignore any blurred or masked regions, they are not part of the product.
ENVIRONMENT
[location, time of day, 1-2 renderable atmosphere elements, consistent film stock and grade for the whole film]
AUDIO DIRECTION
Continuous original BGM at 120 BPM, [groove], [instrumentation], with its own original melody, chords and bassline, playing from 0s to 15s as the loud foreground layer (music roughly 80, SFX 20). Energy arc: intro hit at 0s, groove by 2s, lift at 8s, peak at 10s, final downbeat at 14s. Every cut lands on a downbeat or snare. SPEECH INVENTORY: 0 on-camera lip-synced lines and 0 voiceover lines.
SHOT LIST
0s-2s (shot 1, cut on downbeat of bar 1): [lens + one move] + [one action with product @Image 1] + [lighting] + (music cue) <SFX>
2s-4s (shot 2, cut on downbeat of bar 2): ...
12s-15s (shot 8, cut on downbeat of bar 7): [product hero hold @Image 1] + 【caption】 + (music resolves on final downbeat)
CONTINUITY AND PRODUCT CONSISTENCY
[keep product color, logo, construction and proportions identical across shots; same wardrobe and grade]
```

### Worked Example (Morning Run — Fictional Sneaker Placeholder)

Product details below are fictional placeholders for structure demonstration only; replace them with verified user product facts.

```text
CHARACTER DIRECTION
A new US creator in her late twenties with an oval face, almond-shaped dark brown eyes, straight soft brows, a narrow straight nose, full lips and a gently rounded jaw; about 170 cm, lean runner's build with long legs, relaxed upright posture. Shoulder-length chestnut hair in a low ponytail; she wears a fitted charcoal running top and black shorts so the sneakers stay the focus.
REFERENCE MAP
@Image 1 = product side view, anthracite knit upper and white sole, hero color reference
@Image 2 = product top and sole detail, knit texture and tread reference
Reference only the product shown in the images; ignore any blurred or masked regions, they are not part of the product.
ENVIRONMENT
A quiet residential running path lined with trees and low white villas at sunrise, light morning haze and dew on the asphalt. Kodak Portra 400 look with warm skin tones and soft highlight roll-off for the whole film.
AUDIO DIRECTION
Continuous original BGM at 120 BPM, light four-on-the-floor indie-electronic groove with crisp claps, warm sub bass and a bright plucked synth melody, its own original melody, chords and bassline, playing from 0s to 15s as the loud foreground layer (music roughly 80, SFX 20). Energy arc: kick and bass enter at 0s, full groove by 2s, filter lift at 8s, peak at 10s, final downbeat at 14s. Every cut lands on a downbeat or clap. SPEECH INVENTORY: 0 on-camera lip-synced lines and 0 voiceover lines.
SHOT LIST
0s-2s (shot 1, cut on downbeat of bar 1): 24mm low-angle close-up, locked-off; her foot in the anthracite sneaker @Image 1 lands on the dew-covered asphalt and pushes off, golden-hour backlight with a soft lens flare. (kick and sub bass enter on the downbeat) <rubber sole tapping wet asphalt>
2s-4s (shot 2, cut on downbeat of bar 2): 35mm lateral tracking medium shot; she runs into a beam of low sunlight between two villas, ponytail swinging, warm backlight rimming her shoulders. (full groove with claps) <light footsteps> 【Morning, on repeat】
4s-6s (shot 3, cut on downbeat of bar 3): 50mm handheld micro-jitter medium close-up; she pauses on a curb and tightens the laces of the sneaker @Image 1, soft side light from the low sun. (groove continues, plucked synth melody) <lace pull>
6s-8s (shot 4, cut on downbeat of bar 4): 100mm macro slow push-in on the knit upper and sole @Image 2 as her foot flexes mid-stride, sunlight grazing the knit texture. (groove continues) <soft fabric flex>
8s-9s (shot 5, cut on clap of bar 5): 35mm whip pan following her stride past a row of trees, dappled light flickering. (filter lift begins) <whoosh>
9s-10s (shot 6, cut on clap of bar 5 beat 3): 24mm low tracking shot of both sneakers @Image 1 striking the path in rhythm, backlight flare. (lift builds) <two quick footsteps>
10s-12s (shot 7, cut on downbeat of bar 6): 85mm f/1.4 shallow depth medium shot; she slows to a walk, exhales and looks toward the rising sun, golden-hour backlight. (peak of the groove) <breath>
12s-15s (shot 8, cut on downbeat of bar 7): 50mm locked-off product hero; the sneaker @Image 1 rests on a sunlit stone step, path softly out of focus behind, warm low sunlight. 【Aeris Dasher Lite】 (melody resolves on the final downbeat at 14s, last note rings out)
CONTINUITY AND PRODUCT CONSISTENCY
Keep the sneaker's anthracite knit, white sole, logo placement and proportions identical in every shot; keep her wardrobe, hair and the Portra 400 grade constant.
```

## Step 4: Run Preflight & Confirm Before Rendering

Save the prompt to the workspace directory, run `scripts/preflight.py` in `block` mode, and fix any reported errors until it exits `0`:

```bash
python /mnt/skills/public/video-generation/scripts/preflight.py \
  --prompt-file /mnt/user-data/workspace/commercial_ad_15s.txt \
  --image-count 2 \
  --duration 15
```

Show the finalized prompt to the user and obtain explicit confirmation before starting paid video rendering.

## Step 5: Two-Stage Draft (`480p`) → Final (`720p`/`1080p`) Render

Reuse `scripts/generate.py` directly. With BytePlus Agent Plan (Seedance 2.5), render a fast `480p` preview with `dreamina-seedance-2.5-flash` first, verify framing and motion, then render the approved `720p` (or `1080p`) deliverable with `dreamina-seedance-2.5`:

```bash
# Stage 1: Fast 480p draft preview
VIDEO_GENERATION_PROVIDER=byteplus_agentplan \
BYTEPLUS_AGENTPLAN_VIDEO_MODEL=dreamina-seedance-2.5-flash \
BYTEPLUS_AGENTPLAN_VIDEO_RESOLUTION=480p \
BYTEPLUS_AGENTPLAN_VIDEO_DURATION=15 \
  python /mnt/skills/public/video-generation/scripts/generate.py \
    --prompt-file /mnt/user-data/workspace/commercial_ad_15s.txt \
    --reference-images /mnt/user-data/uploads/product_1.jpg /mnt/user-data/uploads/product_2.jpg \
    --output-file /mnt/user-data/outputs/commercial_ad_15s_draft_480p.mp4 \
    --aspect-ratio 9:16
```

```bash
# Stage 2: Final 720p render (after user approves draft)
VIDEO_GENERATION_PROVIDER=byteplus_agentplan \
BYTEPLUS_AGENTPLAN_VIDEO_MODEL=dreamina-seedance-2.5 \
BYTEPLUS_AGENTPLAN_VIDEO_RESOLUTION=720p \
BYTEPLUS_AGENTPLAN_VIDEO_DURATION=15 \
  python /mnt/skills/public/video-generation/scripts/generate.py \
    --prompt-file /mnt/user-data/workspace/commercial_ad_15s.txt \
    --reference-images /mnt/user-data/uploads/product_1.jpg /mnt/user-data/uploads/product_2.jpg \
    --output-file /mnt/user-data/outputs/commercial_ad_15s_final_720p.mp4 \
    --aspect-ratio 9:16
```

## Step 6: Track B — Multi-Shot 15–30s Production & Stitching

Use this track for multi-scene 15–30s commercial ads, product launch trailers, or turning a Deep Research report / slide deck into a short narrated explainer video:

1. **Plan 3–4 scene beats (5–10s each)** with one shared visual bible (subject/product identity, wardrobe, color grade, aspect ratio, and audio style).
2. **Create consistent reference keyframes (optional but strongly recommended)**: load the `image-generation` skill to generate 2–4 matching keyframe/product reference images (with BytePlus Agent Plan, the same `BYTEPLUS_AGENTPLAN_API_KEY` powers Seedream 5.0 Pro / 5.5 image generation).
3. **Validate & generate clips in parallel**:
   - When using the 6-section beat-synced format per clip, validate each clip prompt with `scripts/preflight.py --duration <clip_seconds>`.
   - Launch parallel sub-agents (in batches of <= 3) or sequential calls to `scripts/generate.py` using identical `--aspect-ratio` and resolution settings across all clips (render `480p` drafts first when iterating, then `720p`/`1080p` finals).
4. **Assemble the final video with `scripts/stitch.sh`**:
   - Default `--mode normalize` re-encodes to H.264/AAC (`-movflags +faststart`) for clean cuts across independently generated AI clips; pass `--fps 24` (or `30`) if you need a fixed frame rate.
   - Use `--mode copy` only when every clip already shares identical codec, resolution, frame rate, and audio stream layout.

```bash
bash /mnt/skills/public/video-generation/scripts/stitch.sh \
  --output-file /mnt/user-data/outputs/campaign_final_720p.mp4 \
  --inputs \
    /mnt/user-data/outputs/scene_01_hook.mp4 \
    /mnt/user-data/outputs/scene_02_product.mp4 \
    /mnt/user-data/outputs/scene_03_hero.mp4 \
  --mode normalize \
  --fps 24
```

Only present the stitched video after `scripts/stitch.sh` exits with status `0`; if stitching fails or `ffmpeg` is unavailable, the script prints the error to stderr and preserves any existing destination file.
