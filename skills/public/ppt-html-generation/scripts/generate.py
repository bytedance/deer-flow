"""
PPT HTML Slide Generator.

Generates HTML presentation slides using Anthropic Claude and fal.ai for images.
Outputs a JSON file containing styled HTML slide fragments.

Usage:
    python generate.py --action generate --plan '<JSON>' --output /path/to/output.json
    python generate.py --action update --plan '<JSON>' --existing /path/to/existing.json --output /path/to/output.json
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM setup (Anthropic Claude)
# ---------------------------------------------------------------------------

try:
    from anthropic import Anthropic
except ImportError:
    logger.error("anthropic not installed. Installing...")
    os.system(f"{sys.executable} -m pip install anthropic -q")
    from anthropic import Anthropic

try:
    import fal_client
except ImportError:
    logger.error("fal-client not installed. Installing...")
    os.system(f"{sys.executable} -m pip install fal-client -q")
    import fal_client

try:
    from bs4 import BeautifulSoup
except ImportError:
    os.system(f"{sys.executable} -m pip install beautifulsoup4 -q")
    from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Prompt modules
# ---------------------------------------------------------------------------

PROMPT_HEADER = """
You are an expert Presentation Designer.
Your task is to create a single HTML fragment for a slide based on the provided content.
"""

PROMPT_THEME_BASE = """
**THEME CONTEXT (Applied globally by the system — do NOT embed these in inline styles):**
- Title Font: {title_font}
- Body Font: {body_font}
- Colors: {colors}

The system automatically applies the above fonts and colors to all slides globally.
You do NOT need to set `    color`, `font-family`, or `background-color` in `<span style="...">` — the theme handles it.
"""

PROMPT_INPUT = """
**INPUT CONTENT (Slide {slide_index}):**
{section_content}
"""

PROMPT_HTML_SCHEMA_INFO = """
**HTML STRUCTURE DEFINITION (STRICTLY FOLLOW THIS):**

You must output a raw HTML string. Do NOT use `<html>`, `<head>`, or `<body>` tags.
Use ONLY the following tags to structure your content:

1.  **Slide Settings**: `<slide-settings>` (Optional, Must be first child)
    -   MUST use explicit closing tag: `<slide-settings ...></slide-settings>`.
    -   **Attributes**:
        -   `contentplacement="top" | "center" | "bottom"` — Vertical alignment.
        -   `background="CSS value"` (e.g. hex color or `linear-gradient(...)`)
        -   `imageurl="url"` — Background image URL.
        -   `imageplacement="fill" | "top" | "bottom" | "left" | "right"`
        -   `imagesize="10-60"` — Percentage of slide for background image strip.
        -   `transition="none" | "fade" | "slide-left" | "slide-right" | "slide-up" | "slide-down" | "flip-x" | "flip-y" | "scale" | "rotate" | "cube"`
        -   `data-prompt="..."` — To GENERATE a background image, provide a prompt here.
    -   Example: `<slide-settings contentplacement="center" background="linear-gradient(135deg, #667eea, #764ba2)" transition="fade"></slide-settings>`

2.  **Headings**: `<h1>` (Title), `<h2>` (Section), `<h3>` (Subtitle)
    -   **Attribute**: `textAlign="left" | "center" | "right"` (REQUIRED)

3.  **Paragraphs**: `<p>Text content...</p>`
    -   **Attribute**: `textAlign="left" | "center" | "right"` (REQUIRED)

4.  **Lists**: `<ul>` or `<ol>` -> `<li>` -> `<p>`. Each `<li>` MUST contain exactly one `<p>` tag.

5.  **Layouts**: `<row>` and `<column>` for grids. Both MUST use explicit closing tags.
    -   `columnwidths` on `<row>` (comma-separated fractions, e.g. "1,1", "1,2").
    -   `<row columnwidths="1,1"><column>...</column><column>...</column></row>`

6.  **Images**: `<img src="" data-prompt="..." alt="..." />`
    -   `data-prompt`: **REQUIRED** for AI generation. Describe the image in detail.

7.  **Charts**: `<chart>` with explicit closing tag.
    -   `data-chart-type`: "bar" | "line" | "pie"
    -   `data-chart`: Multi-series JSON.

8.  **Inline Formatting**: `<strong>`, `<em>`, `<u>`, `<code>`, `<span data-pill>`, `<a href="...">`, `<br>`

**CRITICAL**: Custom elements (`<slide-settings>`, `<chart>`, `<row>`, `<column>`) MUST use explicit closing tags.
"""

PROMPT_DESIGN_LAYOUT = """
**DESIGN INSTRUCTIONS:**
1.  Use `<slide-settings ...></slide-settings>` for background, transitions.
2.  Use `<h1>` for main titles, `<h2>` for section headers, `<h3>` for subtitles. Always specify `textAlign`.
3.  Use `<row columnwidths="1,1">` for side-by-side layouts. Mix 2-column and 3-column for variety.
4.  Use `<img>` with `data-prompt` for inline content images. For backgrounds, use `<slide-settings data-prompt="...">`.
    **Vary your image strategy.** Do NOT put a background image on every slide.
5.  Ensure `<li>` contains exactly one `<p>` tag.
6.  Use `<chart ...></chart>` for numerical data.

**THEME CSS RULE (CRITICAL):**
Do NOT duplicate theme colors in inline styles. Do NOT set `color`, `font-family`, or `background-color` — the theme handles it.
You MAY set `font-size`, `line-height`, `text-align`, and decorative properties.
"""

PROMPT_OUTPUT_FORMAT = """
**OUTPUT FORMAT:**
Return ONLY the raw HTML string. No markdown fences, no explanations.
"""

PROMPT_EXAMPLE = """
**EXAMPLE OUTPUT:**
<slide-settings contentplacement="center" background="linear-gradient(to right, #ece9e6, #ffffff)" transition="fade"></slide-settings>
<h1 textAlign="left">Market Analysis</h1>
<row columnwidths="1,1">
  <column>
    <h3 textAlign="left">Key Trends</h3>
    <ul>
      <li><p textAlign="left">Values are rising by <strong>20%</strong></p></li>
      <li><p textAlign="left">New demographics emerging</p></li>
    </ul>
  </column>
  <column>
    <img src="" data-prompt="A professional business chart showing upward growth trends, modern style" alt="Growth Chart" />
  </column>
</row>
"""

PROMPT_THEME_EXPANSION = """
You are a Creative Director.
Based on the provided Theme Context, expand it into a cohesive **Visual Identity Description** (approx 3-4 sentences).
Describe the recommended mood, container styles, and image aesthetics.

**THEME CONTEXT:**
- Content Style: {style}
- Colors: {colors}
- Fonts: {fonts}

**OUTPUT:**
Return ONLY the description paragraph. Do not use markdown.
"""

PROMPT_TEMPLATE_UPDATE = """
You are an expert Presentation Designer.
Your task is to take an EXISTING SLIDE TEMPLATE (HTML) and update its CONTENT based on the NEW INPUT provided.

**CRITICAL INSTRUCTIONS:**
1.  **PRESERVE LAYOUT & STYLE**: Keep all HTML tags, classes, inline styles, and attributes.
2.  **REPLACE CONTENT**: Replace text in headings, paragraphs, list items with NEW INPUT.
3.  **UPDATE IMAGES**: Update `data-prompt` attributes to reflect new content. Do NOT change `src` or `imageurl`.
4.  **PRESERVE CLOSING TAGS**: Custom elements MUST keep explicit closing tags.
5.  **NO NEW STRUCTURE**: Do not invent new layouts unless absolutely necessary.
6.  **OUTPUT FORMAT**: Return ONLY the updated raw HTML string.

**TEMPLATE HTML:**
{template_html}

**NEW INPUT CONTENT (Slide {slide_index}):**
{section_content}
"""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _clean_html_content(content: str) -> str:
    """Extract HTML from LLM response, removing markdown fences."""
    if not content:
        return ""
    if isinstance(content, list):
        content = "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    content = re.sub(r"^\s*```html\s*\n?", "", content, flags=re.IGNORECASE)
    content = re.sub(r"^\s*```\s*\n?", "", content, flags=re.IGNORECASE)
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


# ---------------------------------------------------------------------------
# Anthropic Claude LLM calls
# ---------------------------------------------------------------------------

def _get_model() -> Anthropic:
    """Get an Anthropic client instance."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    return Anthropic(api_key=api_key)


def _llm_generate(client: Anthropic, prompt: str) -> str:
    """Call Claude claude-sonnet-4-5-20250929 and return text response."""
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def _expand_theme(client: Anthropic, theme: dict, image_options: dict) -> str:
    """Expand theme into a visual identity description."""
    style = image_options.get("style", "Modern")
    colors = f"Background: {theme.get('bgColor', '#ffffff')}, Text: {theme.get('textColor', '#000000')}, Accent: {theme.get('secondaryColor', '#3b82f6')}"
    fonts = f"Title: {theme.get('titleFont', 'Sans-serif')}, Body: {theme.get('bodyFont', 'Sans-serif')}"

    prompt = PROMPT_THEME_EXPANSION.format(style=style, colors=colors, fonts=fonts)
    try:
        return _llm_generate(client, prompt).strip()
    except Exception as e:
        logger.warning(f"Theme expansion failed: {e}")
        return f"Use a {style} look with {colors} and {fonts}."


def _generate_slide_html(client: Anthropic, slide_index: int, section_content: str, theme: dict, visual_identity: str) -> str:
    """Generate HTML for a single slide."""
    title_font = theme.get("titleFont", "Sans-serif")
    body_font = theme.get("bodyFont", "Sans-serif")
    colors = f"BG: {theme.get('bgColor')}, Text: {theme.get('textColor')}"

    prompt = PROMPT_HEADER
    prompt += f"\n**VISUAL CONTEXT (For Content Tone):**\n{visual_identity}\n"
    prompt += PROMPT_THEME_BASE.format(title_font=title_font, body_font=body_font, colors=colors)
    prompt += PROMPT_INPUT.format(slide_index=slide_index, section_content=section_content)
    prompt += PROMPT_HTML_SCHEMA_INFO
    prompt += PROMPT_DESIGN_LAYOUT
    prompt += PROMPT_OUTPUT_FORMAT
    prompt += PROMPT_EXAMPLE

    try:
        result = _llm_generate(client, prompt)
        html = _clean_html_content(result)
        if not html:
            html = f"<h1>Slide {slide_index}</h1><p>{section_content}</p>"
        return html
    except Exception as e:
        logger.error(f"Failed to generate slide {slide_index}: {e}")
        return f"<h1>Slide {slide_index}</h1><p>Error generating slide</p>"


def _update_slide_html(client: Anthropic, slide_index: int, section_content: str, template_html: str) -> str:
    """Update an existing slide template with new content."""
    prompt = PROMPT_TEMPLATE_UPDATE.format(
        template_html=template_html,
        slide_index=slide_index,
        section_content=section_content,
    )
    try:
        result = _llm_generate(client, prompt)
        html = _clean_html_content(result)
        return html if html else template_html
    except Exception as e:
        logger.error(f"Failed to update slide {slide_index}: {e}")
        return template_html


# ---------------------------------------------------------------------------
# fal.ai image generation
# ---------------------------------------------------------------------------

async def _generate_images_for_html(html_content: str, theme: dict, image_options: dict) -> str:
    """Find data-prompt attributes in HTML, generate images via fal.ai, update src/imageurl."""
    if "data-prompt" not in html_content:
        return html_content

    soup = BeautifulSoup(html_content, "html.parser")

    # Find content images (<img>) and background images (<slide-settings>)
    img_tags = soup.find_all("img")
    slide_settings = soup.find("slide-settings")
    all_candidates = img_tags + ([slide_settings] if slide_settings and slide_settings.get("data-prompt") else [])

    if not all_candidates:
        return html_content

    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        logger.warning("FAL_KEY not set, skipping image generation")
        return html_content

    # Set FAL_KEY in env for the fal_client library
    os.environ["FAL_KEY"] = fal_key

    # Build style context
    style_parts = []
    if image_options.get("style"):
        style_parts.append(f"Visual Style: {image_options['style']}")
    colors = []
    if theme.get("bgColor"):
        colors.append(f"Background: {theme['bgColor']}")
    if theme.get("secondaryColor"):
        colors.append(f"Accent: {theme['secondaryColor']}")
    if colors:
        style_parts.append("Colors: " + ", ".join(colors))
    style_context = ". ".join(style_parts)

    model_id = image_options.get("model", "fal-ai/z-image/turbo")

    async def _gen_single(tag):
        prompt = tag.get("data-prompt")
        if not prompt:
            return
        is_bg = tag.name == "slide-settings"
        final_prompt = f"{prompt}. {style_context}" if style_context else prompt

        try:
            handler = await fal_client.submit_async(
                model_id,
                arguments={
                    "prompt": final_prompt,
                    "image_size": "landscape_16_9",
                    "num_inference_steps": 8,
                    "enable_safety_checker": True,
                },
            )
            result = await handler.get()
            if result and "images" in result and result["images"]:
                url = result["images"][0]["url"]
                if is_bg:
                    tag["imageurl"] = url
                else:
                    tag["src"] = url
                    tag["alt"] = prompt
                if tag.has_attr("data-prompt"):
                    del tag["data-prompt"]
                logger.info(f"  ✓ Generated image: {prompt[:50]}...")
            else:
                logger.warning(f"  ✗ No images returned for: {prompt[:50]}...")
                if not is_bg:
                    tag["src"] = "https://via.placeholder.com/800x600?text=Generation+Failed"
        except Exception as e:
            logger.error(f"  ✗ fal.ai error: {e}")
            if not is_bg:
                tag["src"] = "https://via.placeholder.com/800x600?text=Error"

    tasks = [_gen_single(tag) for tag in all_candidates if tag and tag.get("data-prompt")]
    if tasks:
        logger.info(f"Generating {len(tasks)} images via fal.ai...")
        await asyncio.gather(*tasks)

    return str(soup)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def action_generate(plan: dict, output_file: str):
    """Generate a complete presentation from a plan."""
    client = _get_model()
    theme = plan.get("theme", {})
    image_options = plan.get("imageOptions", {})
    slides_plan = plan.get("slides", [])

    if not slides_plan:
        logger.error("No slides in plan")
        sys.exit(1)

    # 1. Expand visual identity
    logger.info("Expanding visual identity...")
    visual_identity = _expand_theme(client, theme, image_options)
    logger.info(f"Visual identity: {visual_identity[:80]}...")

    # 2. Generate HTML for each slide
    slides = []
    for i, slide_spec in enumerate(slides_plan):
        logger.info(f"Generating slide {i}/{len(slides_plan)}...")
        content = slide_spec.get("content", "")
        html = _generate_slide_html(client, i, content, theme, visual_identity)

        # 3. Generate images via fal.ai
        html = asyncio.run(_generate_images_for_html(html, theme, image_options))

        slides.append({"index": i, "slide": html})
        logger.info(f"  ✓ Slide {i} ready")

    # 4. Build output
    output = {
        "title": plan.get("title", "Presentation"),
        "theme": theme,
        "slides": slides,
    }

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\nPresentation written to {output_file} ({len(slides)} slides)")
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return output


def action_update(plan: dict, existing_path: str, output_file: str):
    """Update existing slides with new content."""
    # Load existing presentation
    with open(existing_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

    existing_slides = existing.get("slides", [])
    new_slides_plan = plan.get("slides", [])
    theme = plan.get("theme", existing.get("theme", {}))
    image_options = plan.get("imageOptions", {})

    client = _get_model()
    slides = []

    for i, slide_spec in enumerate(new_slides_plan):
        content = slide_spec.get("content", "")

        if i < len(existing_slides):
            existing_content = existing_slides[i].get("content", "")
            if content == existing_content:
                # Content unchanged, reuse existing HTML
                logger.info(f"Slide {i} unchanged. Skipping generation.")
                html = existing_slides[i].get("slide", "")
            else:
                # Update existing slide
                logger.info(f"Updating slide {i}...")
                template_html = existing_slides[i].get("slide", "")
                html = _update_slide_html(client, i, content, template_html)
                # Generate images only if slide was updated
                html = asyncio.run(_generate_images_for_html(html, theme, image_options))
        else:
            # Generate new slide
            logger.info(f"Generating new slide {i}...")
            visual_identity = _expand_theme(client, theme, image_options)
            html = _generate_slide_html(client, i, content, theme, visual_identity)
            # Generate images for new slide
            html = asyncio.run(_generate_images_for_html(html, theme, image_options))

        # We must save the "content" back into the slide so we can compare it next time
        slides.append({"index": i, "content": content, "slide": html})

    output = {
        "title": plan.get("title", existing.get("title", "Presentation")),
        "theme": theme,
        "slides": slides,
    }

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"\nUpdated presentation written to {output_file} ({len(slides)} slides)")
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PPT HTML Slide Generator")
    parser.add_argument("--action", required=True, choices=["generate", "update"],
                        help="Action: generate or update")
    parser.add_argument("--plan", type=str, required=True,
                        help="JSON plan for slide generation")
    parser.add_argument("--output", type=str, default="/mnt/user-data/outputs/presentation.json",
                        help="Output JSON file path")
    parser.add_argument("--existing", type=str, default=None,
                        help="Existing presentation JSON (for update action)")
    args = parser.parse_args()

    # Check if plan is a file path or a direct JSON string
    if os.path.isfile(args.plan):
        logger.info(f"Loading plan from file: {args.plan}")
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
    else:
        logger.info("Loading plan from command-line string")
        plan = json.loads(args.plan)

    if args.action == "generate":
        action_generate(plan, args.output)
    elif args.action == "update":
        if not args.existing:
            parser.error("--existing is required for update action")
        action_update(plan, args.existing, args.output)


if __name__ == "__main__":
    main()
