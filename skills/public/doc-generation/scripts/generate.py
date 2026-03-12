"""
Document Generator.

Generates professional HTML or Markdown documents using Anthropic Claude.
Supports optional fal.ai image injection for HTML documents.
Outputs a single file suitable for viewing, editing, and PDF export.

Usage:
    python generate.py --action generate --format html --plan '<JSON>' --output /path/to/document.html
    python generate.py --action generate --format markdown --plan '<JSON>' --output /path/to/document.md
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


try:
    from anthropic import Anthropic
except ImportError:
    logger.error("anthropic not installed. Installing...")
    os.system(f"{sys.executable} -m pip install anthropic -q")
    from anthropic import Anthropic

try:
    import fal_client
except ImportError:
    os.system(f"{sys.executable} -m pip install fal-client -q")
    import fal_client

try:
    from bs4 import BeautifulSoup
except ImportError:
    os.system(f"{sys.executable} -m pip install beautifulsoup4 -q")
    from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

HTML_SYSTEM_PROMPT = """
You are an elite Document Design Specialist.
Your mission is to craft a pixel-perfect, static, professional HTML document suitable for high-quality printing or PDF conversion.

**THE ARCHITECT'S BRIEF:**
You must adhere to the following plan:
**Title:** {title}
**Content Plan:** {content_plan}

---

**DOCUMENT VISUAL STANDARDS (STRICT):**
Documents are meant to be printed or exported to PDF. Follow these design constraints:

1.  **Flat Design Only:** Do **NOT** use `box-shadow`, `text-shadow`, or gradients.
2.  **Design for paper:** Do **NOT** create any buttons or clickable/hoverable items.
3.  **White Paper Standard:** The `body` background must be **White (#ffffff)**.
    - You MAY use colored backgrounds for headers, sidebars, or callout boxes.

---

**CSS & STYLING STRATEGY:**

1.  **Write Standard CSS:** Place all styles in a `<style>` block within the `<head>`.
2.  **No Manual Inline:** Do NOT write inline styles unless necessary.
3.  **Fixed-Position Fluidity:**
    - Root container: `width: 100%` and `max-width: 100%`.
    - **No Breakpoints:** Do NOT use `@media` queries to change layout.
    - All containers MUST use percentages (e.g., `width: 30%`).
4.  **Layout Structure (STRICT FLEXBOX):**
    - Use `display: flex; flex-wrap: nowrap;` for multi-column rows.
    - Use `box-sizing: border-box;` on all elements.
5.  **Typography:**
    - Apply `font-family`, `font-size`, `color`, `font-weight` DIRECTLY to text tags.
    - Use `word-wrap: break-word` for long headers.
6.  **Color Precision:** ALWAYS use HEX codes. Do NOT use `rgb()` or `hsl()`.

---

**GENERAL CONSTRAINTS:**
1.  **Single File:** No external .css files.
2.  **Static & Flat:**
    - NO JavaScript or `<script>` tags.
    - NO CSS animations, transitions, or `:hover` effects.

**ASSET HANDLING & IMAGE GENERATION:**
- **Never** leave an image source empty or use generic placeholders.
- **Existing Images:** If an image URL is provided in the plan, use it directly.
- **AI Image Generation:** To request a NEW image be generated, use:
  `<img src="" data-prompt="Highly detailed description of the image..." alt="description" />`
  The system post-processes this tag and uses fal.ai to generate and inject the image URL.

---

**OUTPUT FORMAT:**
Output the complete HTML document starting with `<!DOCTYPE html>`. No markdown fences, no explanations.
"""

MARKDOWN_SYSTEM_PROMPT = """
You are an elite Markdown Document Writer specializing in Notion-like, visually rich documents.
Your mission is to craft a clean, well-structured, and highly readable Markdown document using
Markdown formatting alone (no HTML).

**THE ARCHITECT'S BRIEF:**
**Title:** {title}
**Content Plan:** {content_plan}

---

## EMOJI RULES

- Emojis MUST be written in **colon format** (e.g., `:sparkles:`, `:white_check_mark:`, `:warning:`)
- Use emojis in section headings and callouts

---

## MARKDOWN STYLING RULES

- **Bold** for key concepts, labels, and takeaways
- *Italic* for emphasis or secondary clarification
- ***Bold + Italic*** for critical warnings

### Callouts (Notion-style)
Use blockquotes for callouts:
> :information_source: **Note** — Important context
> :warning: **Warning** — Common mistakes
> :bulb: **Tip** — Helpful suggestions

### Dividers
Use `---` to separate major sections. Do NOT overuse.

---

## CONTENT RULES

1. Use **CommonMark-compliant Markdown only**
2. Clear hierarchy using `#`, `##`, `###`
3. Use bullet lists, numbered lists, task lists
4. Tables when they improve clarity
5. Fenced code blocks with language tags

You MUST NOT use: HTML, inline styles, or CSS.

---

## IMAGE RULES

- Use `![alt text](url)` syntax only for existing URLs
- Do NOT invent image URLs
- Place images after relevant section headers

---

## OUTPUT FORMAT (STRICT)

Output ONLY the raw Markdown content. No explanations, no fences around the whole document.
"""


# ---------------------------------------------------------------------------
# Anthropic Claude LLM
# ---------------------------------------------------------------------------

def _get_model() -> Anthropic:
    """Get an Anthropic client instance."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    return Anthropic(api_key=api_key)


def _llm_generate(client: Anthropic, system_prompt: str, user_prompt: str) -> str:
    """Call Claude claude-sonnet-4-5-20250929 with system + user prompt."""
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    return response.content[0].text


def _clean_html(content: str) -> str:
    """Extract HTML from LLM response."""
    if not content:
        return ""
    content = re.sub(r"^\s*```html\s*\n?", "", content, flags=re.IGNORECASE)
    content = re.sub(r"^\s*```\s*\n?", "", content, flags=re.IGNORECASE)
    if content.endswith("```"):
        content = content[:-3]
    content = re.sub(r"^###\s*HTML\s*\n", "", content, flags=re.IGNORECASE)
    return content.strip()


def _clean_markdown(content: str) -> str:
    """Extract Markdown from LLM response."""
    if not content:
        return ""
    content = re.sub(r"^\s*```markdown\s*\n?", "", content, flags=re.IGNORECASE)
    content = re.sub(r"^\s*```\s*\n?", "", content, flags=re.IGNORECASE)
    if content.endswith("```"):
        content = content[:-3]
    content = re.sub(r"^###\s*MARKDOWN\s*\n", "", content, flags=re.IGNORECASE)
    return content.strip()


# ---------------------------------------------------------------------------
# fal.ai image generation for HTML documents
# ---------------------------------------------------------------------------

async def _generate_images(content: str) -> str:
    """Find data-prompt img tags, generate via fal.ai, and inject URLs."""
    if "data-prompt" not in content:
        return content

    soup = BeautifulSoup(content, "html.parser")
    candidates = [tag for tag in soup.find_all("img") if tag.get("data-prompt")]

    if not candidates:
        return content

    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        logger.warning("FAL_KEY not set, skipping image generation")
        return content

    # Set FAL_KEY in env for the fal_client library
    os.environ["FAL_KEY"] = fal_key

    model_id = "fal-ai/z-image/turbo"

    async def _gen_single(tag):
        prompt = tag.get("data-prompt")
        try:
            handler = await fal_client.submit_async(
                model_id,
                arguments={
                    "prompt": prompt,
                    "image_size": "landscape_16_9",
                    "num_inference_steps": 8,
                    "enable_safety_checker": True,
                },
            )
            result = await handler.get()
            if result and "images" in result and result["images"]:
                url = result["images"][0]["url"]
                tag["src"] = url
                tag["alt"] = tag.get("alt", prompt[:60])
                del tag["data-prompt"]
                logger.info(f"  ✓ Generated image: {prompt[:50]}...")
            else:
                logger.warning(f"  ✗ No images returned for: {prompt[:50]}...")
                tag["src"] = "https://via.placeholder.com/800x450?text=Image+Generation+Failed"
        except Exception as e:
            logger.error(f"  ✗ fal.ai error for '{prompt[:50]}...': {e}")
            tag["src"] = "https://via.placeholder.com/800x450?text=Error"

    logger.info(f"Generating {len(candidates)} images via fal.ai...")
    await asyncio.gather(*[_gen_single(tag) for tag in candidates])

    return str(soup)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def action_generate(plan: dict, fmt: str, output_file: str):
    """Generate a document from a plan."""
    client = _get_model()

    title = plan.get("title", "Document")
    sections = plan.get("sections", [])
    user_request = plan.get("userRequest", "")

    # Build content plan string from sections
    content_plan_parts = []
    for i, section in enumerate(sections):
        heading = section.get("heading", f"Section {i + 1}")
        instructions = section.get("instructions", "")
        content_plan_parts.append(f"{i + 1}. **{heading}**: {instructions}")
    content_plan = "\n".join(content_plan_parts)

    # Select system prompt
    if fmt == "html":
        system_prompt = HTML_SYSTEM_PROMPT.format(title=title, content_plan=content_plan)
    else:
        system_prompt = MARKDOWN_SYSTEM_PROMPT.format(title=title, content_plan=content_plan)

    # Build user prompt
    if user_request:
        user_prompt = user_request
    else:
        user_prompt = f"Create a comprehensive {fmt.upper()} document titled '{title}' following the content plan above."

    # Add any uploaded content context
    if plan.get("extractedContent"):
        user_prompt += f"\n\n**Extracted Content from Uploaded Files:**\n{plan['extractedContent']}"

    logger.info(f"Generating {fmt.upper()} document: '{title}'...")
    logger.info(f"Sections: {len(sections)}")

    # Generate via Claude
    result = _llm_generate(client, system_prompt, user_prompt)

    # Clean output based on format
    if fmt == "html":
        content = _clean_html(result)
        if not content.startswith("<!DOCTYPE") and not content.startswith("<html"):
            content = f'<!DOCTYPE html>\n<html>\n<head><meta charset="UTF-8"><title>{title}</title></head>\n<body>\n{content}\n</body>\n</html>'
        # Post-process: generate images via fal.ai
        content = asyncio.run(_generate_images(content))
    else:
        content = _clean_markdown(result)

    # Write output
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"\nDocument written to {output_file} ({len(content)} chars)")
    print(content[:2000])  # Print preview
    if len(content) > 2000:
        print(f"\n... ({len(content) - 2000} more characters)")
    return content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Document Generator")
    parser.add_argument("--action", required=True, choices=["generate"],
                        help="Action: generate")
    parser.add_argument("--format", required=True, choices=["html", "markdown"],
                        help="Output format: html or markdown")
    parser.add_argument("--plan", type=str, required=True,
                        help="JSON plan for document generation")
    parser.add_argument("--output", type=str, default="/mnt/user-data/outputs/document.html",
                        help="Output file path")
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
        action_generate(plan, args.format, args.output)


if __name__ == "__main__":
    main()
