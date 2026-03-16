"""
Generate a text-based PowerPoint presentation from a plan JSON file.
Uses python-pptx only — no external tools or API keys required.
"""
import argparse
import json
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


# Theme: dark background with white text
BG_COLOR = RGBColor(0x1A, 0x1A, 0x2E)
ACCENT_COLOR = RGBColor(0x00, 0xB4, 0xD8)
TITLE_COLOR = RGBColor(0xFF, 0xFF, 0xFF)
BODY_COLOR = RGBColor(0xCC, 0xCC, 0xCC)


def set_slide_background(slide, color: RGBColor):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_title_slide(prs: Presentation, title: str, subtitle: str = ""):
    layout = prs.slide_layouts[6]  # blank
    slide = prs.slides.add_slide(layout)
    set_slide_background(slide, BG_COLOR)

    # Title
    txBox = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11.33), Inches(1.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = TITLE_COLOR

    # Accent line
    slide.shapes.add_connector(1, Inches(1), Inches(4.2), Inches(5), Inches(4.2))

    # Subtitle
    if subtitle:
        txBox2 = slide.shapes.add_textbox(Inches(1), Inches(4.4), Inches(11.33), Inches(0.8))
        tf2 = txBox2.text_frame
        p2 = tf2.paragraphs[0]
        p2.text = subtitle
        p2.font.size = Pt(24)
        p2.font.color.rgb = ACCENT_COLOR


def add_content_slide(prs: Presentation, title: str, key_points: list[str]):
    layout = prs.slide_layouts[6]  # blank
    slide = prs.slides.add_slide(layout)
    set_slide_background(slide, BG_COLOR)

    # Title
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(12.33), Inches(0.9))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(32)
    p.font.bold = True
    p.font.color.rgb = ACCENT_COLOR

    # Divider line
    slide.shapes.add_connector(1, Inches(0.5), Inches(1.35), Inches(12.83), Inches(1.35))

    # Body
    txBox2 = slide.shapes.add_textbox(Inches(0.5), Inches(1.6), Inches(12.33), Inches(5.4))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True

    for i, point in enumerate(key_points):
        if i == 0:
            p = tf2.paragraphs[0]
        else:
            p = tf2.add_paragraph()
        p.text = f"▸  {point}"
        p.font.size = Pt(20)
        p.font.color.rgb = BODY_COLOR
        p.space_after = Pt(8)


def generate_ppt(plan_file: str, output_file: str) -> str:
    # Allow UTF-8 with BOM for better compatibility across editors/OSes.
    with open(plan_file, "r", encoding="utf-8-sig") as f:
        plan = json.load(f)

    import os
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    for slide_info in plan.get("slides", []):
        slide_type = slide_info.get("type", "content")
        title = slide_info.get("title", "")
        subtitle = slide_info.get("subtitle", "")
        key_points = slide_info.get("key_points", [])

        if slide_type == "title" or (not key_points and subtitle):
            add_title_slide(prs, title, subtitle)
        else:
            add_content_slide(prs, title, key_points)

    prs.save(output_file)
    return f"Successfully generated presentation with {len(plan.get('slides', []))} slides to {output_file}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate text-based PPTX from plan JSON")
    parser.add_argument("--plan-file", required=True, help="Path to JSON presentation plan file")
    parser.add_argument("--output-file", required=True, help="Output path for PPTX file")
    args = parser.parse_args()

    try:
        print(generate_ppt(args.plan_file, args.output_file))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
