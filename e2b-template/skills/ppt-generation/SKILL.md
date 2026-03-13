---
name: ppt-generation
description: Use this skill when the user requests to generate, create, or make presentations (PPT/PPTX). Creates visually rich slides by generating images for each slide and composing them into a PowerPoint file.
---

# PPT Generation Skill

## Overview

This skill generates professional PowerPoint presentations by creating AI-generated images for each slide and composing them into a PPTX file. The workflow includes planning the presentation structure with a consistent visual style, generating slide images sequentially (using the previous slide as a reference for style consistency), and assembling them into a final presentation.

## Core Capabilities

- Plan and structure multi-slide presentations with unified visual style
- Support multiple presentation styles: Business, Academic, Minimal, Apple Keynote, Creative
- Generate unique AI images for each slide using image-generation skill
- Maintain visual consistency by using previous slide as reference image
- Compose images into a professional PPTX file

## Presentation Styles

Choose one of the following styles when creating the presentation plan:

| Style | Description | Best For |
|-------|-------------|----------|
| **glassmorphism** | Frosted glass panels with blur effects, floating translucent cards, vibrant gradient backgrounds, depth through layering | Tech products, AI/SaaS demos, futuristic pitches |
| **dark-premium** | Rich black backgrounds (#0a0a0a), luminous accent colors, subtle glow effects, luxury brand aesthetic | Premium products, executive presentations, high-end brands |
| **gradient-modern** | Bold mesh gradients, fluid color transitions, contemporary typography, vibrant yet sophisticated | Startups, creative agencies, brand launches |
| **neo-brutalist** | Raw bold typography, high contrast, intentional "ugly" aesthetic, anti-design as design, Memphis-inspired | Edgy brands, Gen-Z targeting, disruptive startups |
| **3d-isometric** | Clean isometric illustrations, floating 3D elements, soft shadows, tech-forward aesthetic | Tech explainers, product features, SaaS presentations |
| **editorial** | Magazine-quality layouts, sophisticated typography hierarchy, dramatic photography, Vogue/Bloomberg aesthetic | Annual reports, luxury brands, thought leadership |
| **minimal-swiss** | Grid-based precision, Helvetica-inspired typography, bold use of negative space, timeless modernism | Architecture, design firms, premium consulting |
| **keynote** | Apple-inspired aesthetic with bold typography, dramatic imagery, high contrast, cinematic feel | Keynotes, product reveals, inspirational talks |

## Workflow

### Step 1: Understand Requirements

When a user requests presentation generation, identify:

- Topic/subject: What is the presentation about
- Number of slides: How many slides are needed (default: 5-10)
- **Style**: business / academic / minimal / keynote / creative
- Aspect ratio: Standard (16:9) or classic (4:3)
- Content outline: Key points for each slide
- You don't need to check the folder under `/mnt/user-data`

### Step 2: Create Presentation Plan

Create a JSON file in `/mnt/user-data/workspace/` with the presentation structure. **Important**: Include the `style` field to define the overall visual consistency.

```json
{
  "title": "Presentation Title",
  "style": "keynote",
  "style_guidelines": {
    "color_palette": "Deep black backgrounds, white text, single accent color (blue or orange)",
    "typography": "Bold sans-serif headlines, clean body text, dramatic size contrast",
    "imagery": "High-quality photography, full-bleed images, cinematic composition",
    "layout": "Generous whitespace, centered focus, minimal elements per slide"
  },
  "aspect_ratio": "16:9",
  "slides": [
    {
      "slide_number": 1,
      "type": "title",
      "title": "Main Title",
      "subtitle": "Subtitle or tagline",
      "visual_description": "Detailed description for image generation"
    },
    {
      "slide_number": 2,
      "type": "content",
      "title": "Slide Title",
      "key_points": ["Point 1", "Point 2", "Point 3"],
      "visual_description": "Detailed description for image generation"
    }
  ]
}
```

### Step 3: Generate Slide Images Sequentially

**IMPORTANT**: Generate slides **strictly one by one, in order**. Do NOT parallelize or batch image generation. Each slide depends on the previous slide's output as a reference image. Generating slides in parallel will break visual consistency and is not allowed.

1. Read the image-generation skill: `/mnt/skills/public/image-generation/SKILL.md`

2. **For the FIRST slide (slide 1)**, create a prompt that establishes the visual style:

```json
{
  "prompt": "Professional presentation slide. [style_guidelines from plan]. Title: 'Your Title'. [visual_description]. This slide establishes the visual language for the entire presentation.",
  "style": "[Based on chosen style - e.g., Apple Keynote aesthetic, dramatic lighting, cinematic]",
  "composition": "Clean layout with clear text hierarchy, [style-specific composition]",
  "color_palette": "[From style_guidelines]",
  "typography": "[From style_guidelines]"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-01-prompt.json \
  --output-file /mnt/user-data/outputs/slide-01.jpg \
  --aspect-ratio 16:9
```

3. **For subsequent slides (slide 2+)**, use the PREVIOUS slide as a reference image:

```json
{
  "prompt": "Professional presentation slide continuing the visual style from the reference image. Maintain the same color palette, typography style, and overall aesthetic. Title: 'Slide Title'. [visual_description]. Keep visual consistency with the reference.",
  "style": "Match the style of the reference image exactly",
  "composition": "Similar layout principles as reference, adapted for this content",
  "color_palette": "Same as reference image",
  "consistency_note": "This slide must look like it belongs in the same presentation as the reference image"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-02-prompt.json \
  --reference-images /mnt/user-data/outputs/slide-01.jpg \
  --output-file /mnt/user-data/outputs/slide-02.jpg \
  --aspect-ratio 16:9
```

4. **Continue for all remaining slides**, always referencing the previous slide:

```bash
# Slide 3 references slide 2
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-03-prompt.json \
  --reference-images /mnt/user-data/outputs/slide-02.jpg \
  --output-file /mnt/user-data/outputs/slide-03.jpg \
  --aspect-ratio 16:9

# Slide 4 references slide 3
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/slide-04-prompt.json \
  --reference-images /mnt/user-data/outputs/slide-03.jpg \
  --output-file /mnt/user-data/outputs/slide-04.jpg \
  --aspect-ratio 16:9
```

### Step 4: Compose PPT

After all slide images are generated, call the composition script:

```bash
python /mnt/skills/public/ppt-generation/scripts/generate.py \
  --plan-file /mnt/user-data/workspace/presentation-plan.json \
  --slide-images /mnt/user-data/outputs/slide-01.jpg /mnt/user-data/outputs/slide-02.jpg /mnt/user-data/outputs/slide-03.jpg \
  --output-file /mnt/user-data/outputs/presentation.pptx
```

Parameters:

- `--plan-file`: Absolute path to the presentation plan JSON file (required)
- `--slide-images`: Absolute paths to slide images in order (required, space-separated)
- `--output-file`: Absolute path to output PPTX file (required)

[!NOTE]
Do NOT read the python file, just call it with the parameters.

## Complete Example: Glassmorphism Style (最现代前卫)

User request: "Create a presentation about AI product launch"

### Step 1: Create presentation plan

Create `/mnt/user-data/workspace/ai-product-plan.json`:
```json
{
  "title": "Introducing Nova AI",
  "style": "glassmorphism",
  "style_guidelines": {
    "color_palette": "Vibrant purple-to-cyan gradient background (#667eea→#00d4ff), frosted glass panels with 15-20% white opacity, electric accents",
    "typography": "SF Pro Display style, bold 700 weight white titles with subtle text-shadow, clean 400 weight body text, excellent contrast on glass",
    "imagery": "Abstract 3D glass spheres, floating translucent geometric shapes, soft luminous orbs, depth through layered transparency",
    "layout": "Centered frosted glass cards with 32px rounded corners, 48-64px padding, floating above gradient, layered depth with soft shadows",
    "effects": "Backdrop blur 20-40px on glass panels, subtle white border glow, soft colored shadows matching gradient, light refraction effects",
    "visual_language": "Apple Vision Pro / visionOS aesthetic, premium depth through transparency, futuristic yet approachable, 2024 design trends"
  },
  "aspect_ratio": "16:9",
  "slides": [
    {
      "slide_number": 1,
      "type": "title",
      "title": "Introducing Nova AI",
      "subtitle": "Intelligence, Reimagined",
      "visual_description": "Stunning gradient background flowing from deep purple (#667eea) through magenta to cyan (#00d4ff). Center: large frosted glass panel with strong backdrop blur, containing bold white title 'Introducing Nova AI' and lighter subtitle. Floating 3D glass spheres and abstract shapes around the card creating depth. Soft glow emanating from behind the glass panel. Premium visionOS aesthetic. The glass card has subtle white border (1px rgba 255,255,255,0.3) and soft purple-tinted shadow."
    },
    {
      "slide_number": 2,
      "type": "content",
      "title": "Why Nova?",
      "key_points": ["10x faster processing", "Human-like understanding", "Enterprise-grade security"],
      "visual_description": "Same purple-cyan gradient background. Left side: floating frosted glass card with title 'Why Nova?' in bold white, three key points below with subtle glass pill badges. Right side: abstract 3D visualization of neural network as interconnected glass nodes with soft glow. Floating translucent geometric shapes (icosahedrons, tori) adding depth. Consistent glassmorphism aesthetic with previous slide."
    },
    {
      "slide_number": 3,
      "type": "content",
      "title": "How It Works",
      "key_points": ["Natural language input", "Multi-modal processing", "Instant insights"],
      "visual_description": "Gradient background consistent with previous slides. Central composition: three stacked frosted glass cards at slight angles showing the workflow steps, connected by soft glowing lines. Each card has an abstract icon. Floating glass orbs and light particles around the composition. Title 'How It Works' in bold white at top. Depth created through card layering and transparency."
    },
    {
      "slide_number": 4,
      "type": "content",
      "title": "Built for Scale",
      "key_points": ["1M+ concurrent users", "99.99% uptime", "Global infrastructure"],
      "visual_description": "Same gradient background. Asymmetric layout: right side features large frosted glass panel with metrics displayed in bold typography. Left side: abstract 3D globe made of glass panels and connection lines, representing global scale. Floating data visualization elements as small glass cards with numbers. Soft ambient glow throughout. Premium tech aesthetic."
    },
    {
      "slide_number": 5,
      "type": "conclusion",
      "title": "The Future Starts Now",
      "subtitle": "Join the waitlist",
      "visual_description": "Dramatic finale slide. Gradient background with slightly increased vibrancy. Central frosted glass card with bold title 'The Future Starts Now' and call-to-action subtitle. Behind the card: burst of soft light rays and floating glass particles creating celebration effect. Multiple layered glass shapes creating depth. The most visually impactful slide while maintaining style consistency."
    }
  ]
}
```

### Step 2: Read image-generation skill

Read `/mnt/skills/public/image-generation/SKILL.md` to understand how to generate images.

### Step 3: Generate slide images sequentially with reference chaining

**Slide 1 - Title (establishes the visual language):**

Create `/mnt/user-data/workspace/nova-slide-01.json`:
```json
{
  "prompt": "Ultra-premium presentation title slide with glassmorphism design. Background: smooth flowing gradient from deep purple (#667eea) through magenta (#f093fb) to cyan (#00d4ff), soft and vibrant. Center: large frosted glass panel with strong backdrop blur effect, rounded corners 32px, containing bold white sans-serif title 'Introducing Nova AI' (72pt, SF Pro Display style, font-weight 700) with subtle text shadow, subtitle 'Intelligence, Reimagined' below in lighter weight. The glass panel has subtle white border (1px rgba 255,255,255,0.25) and soft purple-tinted drop shadow. Floating around the card: 3D glass spheres with refraction, translucent geometric shapes (icosahedrons, abstract blobs), creating depth and dimension. Soft luminous glow emanating from behind the glass panel. Small floating particles of light. Apple Vision Pro / visionOS UI aesthetic. Professional presentation slide, 16:9 aspect ratio. Hyper-modern, premium tech product launch feel.",
  "style": "Glassmorphism, visionOS aesthetic, Apple Vision Pro UI style, premium tech, 2024 design trends",
  "composition": "Centered glass card as focal point, floating 3D elements creating depth at edges, 40% negative space, clear visual hierarchy",
  "lighting": "Soft ambient glow from gradient, light refraction through glass elements, subtle rim lighting on 3D shapes",
  "color_palette": "Purple gradient #667eea, magenta #f093fb, cyan #00d4ff, frosted white rgba(255,255,255,0.15), pure white text #ffffff",
  "effects": "Backdrop blur on glass panels, soft drop shadows with color tint, light refraction, subtle noise texture on glass, floating particles"
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/nova-slide-01.json \
  --output-file /mnt/user-data/outputs/nova-slide-01.jpg \
  --aspect-ratio 16:9
```

**Slide 2 - Content (MUST reference slide 1 for consistency):**

Create `/mnt/user-data/workspace/nova-slide-02.json`:
```json
{
  "prompt": "Presentation slide continuing EXACT visual style from reference image. SAME purple-to-cyan gradient background, SAME glassmorphism aesthetic, SAME typography style. Left side: frosted glass card with backdrop blur containing title 'Why Nova?' in bold white (matching reference font style), three feature points as subtle glass pill badges below. Right side: abstract 3D neural network visualization made of interconnected glass nodes with soft cyan glow, floating in space. Floating translucent geometric shapes (matching style from reference) adding depth. The frosted glass has identical treatment: white border, purple-tinted shadow, same blur intensity. CRITICAL: This slide must look like it belongs in the exact same presentation as the reference image - same colors, same glass treatment, same overall aesthetic.",
  "style": "MATCH REFERENCE EXACTLY - Glassmorphism, visionOS aesthetic, same visual language",
  "composition": "Asymmetric split: glass card left (40%), 3D visualization right (40%), breathing room between elements",
  "color_palette": "EXACTLY match reference: purple #667eea, cyan #00d4ff gradient, same frosted white treatment, same text white",
  "consistency_note": "CRITICAL: Must be visually identical in style to reference image. Same gradient colors, same glass blur intensity, same shadow treatment, same typography weight and style. Viewer should immediately recognize this as the same presentation."
}
```

```bash
python /mnt/skills/public/image-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/nova-slide-02.json \
  --reference-images /mnt/user-data/outputs/nova-slide-01.jpg \
  --output-file /mnt/user-data/outputs/nova-slide-02.jpg \
  --aspect-ratio 16:9
```

**Slides 3-5: Continue the same pattern, each referencing the previous slide**

Key consistency rules for subsequent slides:
- Always include "continuing EXACT visual style from reference image" in prompt
- Specify "SAME gradient background", "SAME glass treatment", "SAME typography"
- Include `consistency_note` emphasizing style matching
- Reference the immediately previous slide image

### Step 4: Compose final PPT

```bash
python /mnt/skills/public/ppt-generation/scripts/generate.py \
  --plan-file /mnt/user-data/workspace/nova-plan.json \
  --slide-images /mnt/user-data/outputs/nova-slide-01.jpg /mnt/user-data/outputs/nova-slide-02.jpg /mnt/user-data/outputs/nova-slide-03.jpg /mnt/user-data/outputs/nova-slide-04.jpg /mnt/user-data/outputs/nova-slide-05.jpg \
  --output-file /mnt/user-data/outputs/nova-presentation.pptx
```

## Style-Specific Guidelines

### Glassmorphism Style (推荐 - 最现代前卫)
```json
{
  "style": "glassmorphism",
  "style_guidelines": {
    "color_palette": "Vibrant gradient backgrounds (purple #667eea to pink #f093fb, or cyan #4facfe to blue #00f2fe), frosted white panels with 20% opacity, accent colors that pop against the gradient",
    "typography": "SF Pro Display or Inter font style, bold 600-700 weight titles, clean 400 weight body, white text with subtle drop shadow for readability on glass",
    "imagery": "Abstract 3D shapes floating in space, soft blurred orbs, geometric primitives with glass material, depth through overlapping translucent layers",
    "layout": "Floating card panels with backdrop-blur effect, generous padding (48-64px), rounded corners (24-32px radius), layered depth with subtle shadows",
    "effects": "Frosted glass blur (backdrop-filter: blur 20px), subtle white border (1px rgba 255,255,255,0.2), soft glow behind panels, floating elements with drop shadows",
    "visual_language": "Premium tech aesthetic like Apple Vision Pro UI, depth through transparency, light refracting through glass surfaces"
  }
}
```

### Dark Premium Style
```json
{
  "style": "dark-premium",
  "style_guidelines": {
    "color_palette": "Deep black base (#0a0a0a to #121212), luminous accent color (electric blue #00d4ff, neon purple #bf5af2, or gold #ffd700), subtle gray gradients for depth (#1a1a1a to #0a0a0a)",
    "typography": "Elegant sans-serif (Neue Haas Grotesk or Suisse Int'l style), dramatic size contrast (72pt+ headlines, 18pt body), letter-spacing -0.02em for headlines, pure white (#ffffff) text",
    "imagery": "Dramatic studio lighting, rim lights and edge glow, cinematic product shots, abstract light trails, premium material textures (brushed metal, matte surfaces)",
    "layout": "Generous negative space (60%+), asymmetric balance, content anchored to grid but with breathing room, single focal point per slide",
    "effects": "Subtle ambient glow behind key elements, light bloom effects, grain texture overlay (2-3% opacity), vignette on edges",
    "visual_language": "Luxury tech brand aesthetic (Bang & Olufsen, Porsche Design), sophistication through restraint, every element intentional"
  }
}
```

### Gradient Modern Style
```json
{
  "style": "gradient-modern",
  "style_guidelines": {
    "color_palette": "Bold mesh gradients (Stripe/Linear style: purple-pink-orange #7c3aed→#ec4899→#f97316, or cool tones: cyan-blue-purple #06b6d4→#3b82f6→#8b5cf6), white or dark text depending on background intensity",
    "typography": "Modern geometric sans-serif (Satoshi, General Sans, or Clash Display style), variable font weights, oversized bold headlines (80pt+), comfortable body text (20pt)",
    "imagery": "Abstract fluid shapes, morphing gradients, 3D rendered abstract objects, soft organic forms, floating geometric primitives",
    "layout": "Dynamic asymmetric compositions, overlapping elements with blend modes, text integrated with gradient flows, full-bleed backgrounds",
    "effects": "Smooth gradient transitions, subtle noise texture (3-5% for depth), soft shadows with color tint matching gradient, motion blur suggesting movement",
    "visual_language": "Contemporary SaaS aesthetic (Stripe, Linear, Vercel), energetic yet professional, forward-thinking tech vibes"
  }
}
```

### Neo-Brutalist Style
```json
{
  "style": "neo-brutalist",
  "style_guidelines": {
    "color_palette": "High contrast primaries: stark black, pure white, with bold accent (hot pink #ff0080, electric yellow #ffff00, or raw red #ff0000), optional: Memphis-inspired pastels as secondary",
    "typography": "Ultra-bold condensed type (Impact, Druk, or Bebas Neue style), UPPERCASE headlines, extreme size contrast, intentionally tight or overlapping letter-spacing",
    "imagery": "Raw unfiltered photography, intentional visual noise, halftone patterns, cut-out collage aesthetic, hand-drawn elements, stickers and stamps",
    "layout": "Broken grid, overlapping elements, thick black borders (4-8px), visible structure, anti-whitespace (dense but organized chaos)",
    "effects": "Hard shadows (no blur, offset 8-12px), pixelation accents, scan lines, CRT screen effects, intentional 'mistakes'",
    "visual_language": "Anti-corporate rebellion, DIY zine aesthetic meets digital, raw authenticity, memorable through boldness"
  }
}
```

### 3D Isometric Style
```json
{
  "style": "3d-isometric",
  "style_guidelines": {
    "color_palette": "Soft contemporary palette: muted purples (#8b5cf6), teals (#14b8a6), warm corals (#fb7185), with cream or light gray backgrounds (#fafafa), consistent saturation across elements",
    "typography": "Friendly geometric sans-serif (Circular, Gilroy, or Quicksand style), medium weight headlines, excellent readability, comfortable 24pt body text",
    "imagery": "Clean isometric 3D illustrations, consistent 30° isometric angle, soft clay-render aesthetic, floating platforms and devices, cute simplified objects",
    "layout": "Central isometric scene as hero, text balanced around 3D elements, clear visual hierarchy, comfortable margins (64px+)",
    "effects": "Soft drop shadows (20px blur, 30% opacity), ambient occlusion on 3D objects, subtle gradients on surfaces, consistent light source (top-left)",
    "visual_language": "Friendly tech illustration (Slack, Notion, Asana style), approachable complexity, clarity through simplification"
  }
}
```

### Editorial Style
```json
{
  "style": "editorial",
  "style_guidelines": {
    "color_palette": "Sophisticated neutrals: off-white (#f5f5f0), charcoal (#2d2d2d), with single accent color (burgundy #7c2d12, forest #14532d, or navy #1e3a5f), occasional full-color photography",
    "typography": "Refined serif for headlines (Playfair Display, Freight, or Editorial New style), clean sans-serif for body (Söhne, Graphik), dramatic size hierarchy (96pt headlines, 16pt body), generous line-height 1.6",
    "imagery": "Magazine-quality photography, dramatic crops, full-bleed images, portraits with intentional negative space, editorial lighting (Vogue, Bloomberg Businessweek style)",
    "layout": "Sophisticated grid system (12-column), intentional asymmetry, pull quotes as design elements, text wrapping around images, elegant margins",
    "effects": "Minimal effects - let photography and typography shine, subtle image treatments (slight desaturation, film grain), elegant borders and rules",
    "visual_language": "High-end magazine aesthetic, intellectual sophistication, content elevated through design restraint"
  }
}
```

### Minimal Swiss Style
```json
{
  "style": "minimal-swiss",
  "style_guidelines": {
    "color_palette": "Pure white (#ffffff) or off-white (#fafaf9) backgrounds, true black (#000000) text, single bold accent (Swiss red #ff0000, Klein blue #002fa7, or signal yellow #ffcc00)",
    "typography": "Helvetica Neue or Aktiv Grotesk, strict type scale (12/16/24/48/96), medium weight for body, bold for emphasis only, flush-left ragged-right alignment",
    "imagery": "Objective photography, geometric shapes, clean iconography, mathematical precision, intentional empty space as compositional element",
    "layout": "Strict grid adherence (baseline grid visible in spirit), modular compositions, generous whitespace (40%+ of slide), content aligned to invisible grid lines",
    "effects": "None - purity of form, no shadows, no gradients, no decorative elements, occasional single hairline rules",
    "visual_language": "International Typographic Style, form follows function, timeless modernism, Dieter Rams-inspired restraint"
  }
}
```

### Keynote Style (Apple风格)
```json
{
  "style": "keynote",
  "style_guidelines": {
    "color_palette": "Deep blacks (#000000 to #1d1d1f), pure white text, signature blue (#0071e3) or gradient accents (purple-pink for creative, blue-teal for tech)",
    "typography": "San Francisco Pro Display, extreme weight contrast (bold 80pt+ titles, light 24pt body), negative letter-spacing on headlines (-0.03em), optical alignment",
    "imagery": "Cinematic photography, shallow depth of field, dramatic lighting (rim lights, spot lighting), product hero shots with reflections, full-bleed imagery",
    "layout": "Maximum negative space, single powerful image or statement per slide, content centered or dramatically offset, no clutter",
    "effects": "Subtle gradient overlays, light bloom and glow on key elements, reflection on surfaces, smooth gradient backgrounds",
    "visual_language": "Apple WWDC keynote aesthetic, confidence through simplicity, every pixel considered, theatrical presentation"
  }
}
```

## Output Handling

After generation:

- The PPTX file is saved in `/mnt/user-data/outputs/`
- Share the generated presentation with user using `present_files` tool
- Also share the individual slide images if requested
- Provide brief description of the presentation
- Offer to iterate or regenerate specific slides if needed

## Notes

### Critical Quality Guidelines

**Prompt Engineering for Professional Results:**
- Always use English for image prompts regardless of user's language
- Be EXTREMELY specific about visual details - vague prompts produce generic results
- Include exact hex color codes (e.g., #667eea not "purple")
- Specify typography details: font weight (400/700), size hierarchy, letter-spacing
- Describe effects precisely: "backdrop blur 20px", "drop shadow 8px blur 30% opacity"
- Reference real design systems: "visionOS aesthetic", "Stripe website style", "Bloomberg Businessweek layout"

**Visual Consistency (Most Important):**
- **Generate slides sequentially** - each slide MUST reference the previous one
- The first slide is critical - it establishes the visual language for the entire presentation
- In every subsequent slide prompt, explicitly state: "continuing EXACT visual style from reference image"
- Use SAME, EXACT, MATCH keywords emphatically in prompts to enforce consistency
- Include a `consistency_note` field in every JSON prompt after slide 1
- If a slide looks inconsistent, regenerate it with STRONGER reference emphasis

**Design Principles for Modern Aesthetics:**
- Embrace negative space - 40-60% empty space creates premium feel
- Limit elements per slide - one focal point, one message
- Use depth through layering (shadows, transparency, z-depth)
- Typography hierarchy: massive headlines (72pt+), comfortable body (18-24pt)
- Color restraint: one primary palette, 1-2 accent colors maximum

**Common Mistakes to Avoid:**
- ❌ Generic prompts like "professional slide" - be specific
- ❌ Too many elements/text per slide - cluttered = unprofessional
- ❌ Inconsistent colors between slides - always reference previous slide
- ❌ Skipping the reference image parameter - this breaks visual consistency
- ❌ Using different design styles within one presentation
- ❌ Generating slides in parallel - slides MUST be generated one at a time in order (slide 1 → 2 → 3 ...), never concurrently

**Recommended Styles for Different Contexts:**
- Tech product launch → `glassmorphism` or `gradient-modern`
- Luxury/premium brand → `dark-premium` or `editorial`
- Startup pitch → `gradient-modern` or `minimal-swiss`
- Executive presentation → `dark-premium` or `keynote`
- Creative agency → `neo-brutalist` or `gradient-modern`
- Data/analytics → `minimal-swiss` or `3d-isometric`
