#!/usr/bin/env python3
"""
cover.py — Generate cover.html from tokens.json.

Usage:
    python3 cover.py --tokens tokens.json --out cover.html

Reads tokens.json["cover_pattern"] and renders the matching HTML cover.
Cover fonts are loaded live via Google Fonts @import (no local caching).
Exit codes: 0 success, 1 bad args/missing file, 3 render error
"""

import argparse
import json
import sys


# ── Google Fonts loader ────────────────────────────────────────────────────────
def _gfonts_import(t: dict) -> str:
    """Return a CSS @import for the document's Google Fonts, if available."""
    url = t.get("gfonts_import", "")
    if url:
        return f"@import url('{url}');"
    return ""


# ── Shared CSS head (required by all patterns) ─────────────────────────────────
def _base_css(t: dict) -> str:
    """Critical reset + shared variables. Never remove these rules."""
    return f"""
{_gfonts_import(t)}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{
    width: 794px; height: 1123px;
    overflow: hidden;
    background: {t['cover_bg']};
    font-family: '{t['font_body']}', 'Helvetica Neue', Helvetica, Arial, sans-serif;
}}
.page {{
    position: relative;
    width: 794px; height: 1123px;
    background: {t['cover_bg']};
    overflow: hidden;
}}
"""


# ── Dot-grid SVG helper ─────────────────────────────────────────────────────────
def _dot_grid(x0, y0, cols, rows, *, gap, r, color, opacity) -> str:
    """Render a dot-grid as an absolutely positioned SVG element."""
    dots = []
    for row in range(rows):
        for col in range(cols):
            cx = x0 + col * gap
            cy = y0 + row * gap
            dots.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>')
    return (
        f'<svg style="position:absolute;top:0;left:0;width:794px;height:1123px;'
        f'pointer-events:none;opacity:{opacity}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(dots) + "</svg>"
    )


# ── Cross-hatch SVG helper ──────────────────────────────────────────────────────
def _cross_hatch(color, opacity, spacing=32, stroke_w=0.5) -> str:
    lines = []
    for i in range(-20, 60):
        x = i * spacing
        lines.append(f'<line x1="{x}" y1="0" x2="{x + 1200}" y2="1200" stroke="{color}" stroke-width="{stroke_w}"/>')
    return (
        f'<svg style="position:absolute;top:0;left:0;width:794px;height:1123px;'
        f'pointer-events:none;opacity:{opacity};overflow:hidden" xmlns="http://www.w3.org/2000/svg">'
        + "".join(lines) + "</svg>"
    )


# ── Pattern 1: Full-bleed block ────────────────────────────────────────────────
def _pattern_fullbleed(t: dict) -> str:
    dot_grid = _dot_grid(
        x0=500, y0=40, cols=10, rows=20, gap=24, r=1.8,
        color=t["accent"], opacity=0.12
    )
    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f"""
        <div style="font-size:14px;color:{t['muted']};letter-spacing:0.01em;
                    max-width:480px;line-height:1.5;margin-bottom:40px;">
            {t['subtitle']}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
.label {{
    font-size: 9px; font-weight: 500; letter-spacing: 0.22em;
    color: {t['accent']}; text-transform: uppercase; margin-bottom: 28px;
}}
.title {{
    font-family: '{t['font_display']}', 'Times New Roman', Georgia, serif;
    font-weight: 900; font-size: 60px; line-height: 1.0;
    color: {t['text_light']}; letter-spacing: -0.015em;
    margin-bottom: 10px; max-width: 560px;
    word-wrap: break-word;
}}
.rule {{
    width: 52%; height: 1.5px;
    background: linear-gradient(to right, {t['accent']}, transparent);
    margin: 24px 0 20px;
}}
.content {{
    position: absolute; left: 68px; right: 60px;
    top: 0; bottom: 0;
    display: flex; flex-direction: column; justify-content: center;
    padding-top: 60px;
}}
.footer {{
    position: absolute; bottom: 0; left: 0; right: 0;
    height: 70px;
    background: rgba(0,0,0,0.22);
    display: flex; align-items: center;
    justify-content: space-between;
    padding: 0 68px;
}}
.footer-author {{ font-size: 11px; color: rgba(240,237,230,0.75); letter-spacing:0.04em; }}
.footer-date   {{ font-size: 11px; color: {t['muted']}; letter-spacing: 0.04em; }}
</style>
</head>
<body>
<div class="page">
    <!-- top-right accent strip -->
    <div style="position:absolute;top:0;right:0;width:35%;height:4px;background:{t['accent']};"></div>
    <!-- left vertical accent bar (gradient fade) -->
    <div style="position:absolute;left:48px;top:18%;width:3px;height:60%;
                background:linear-gradient(to bottom,{t['accent']},transparent);"></div>
    <!-- dot grid background texture -->
    {dot_grid}

    <div class="content">
        <div class="label">{t.get('doc_type','Document').upper()} &nbsp;·&nbsp; {t.get('date','')}</div>
        <div class="title">{t['title']}</div>
        <div class="rule"></div>
        {subtitle_block}
    </div>

    <div class="footer">
        <div class="footer-author">{t.get('author','')}</div>
        <div class="footer-date">{t.get('date','')}</div>
    </div>
</div>
</body></html>"""


# ── Pattern 2: Split panel ─────────────────────────────────────────────────────
def _pattern_split(t: dict) -> str:
    dot_grid = _dot_grid(
        x0=360, y0=120, cols=10, rows=18, gap=22, r=2,
        color="#CCCCCC", opacity=0.25
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
.left-panel {{
    position: absolute; top: 0; left: 0;
    width: 330px; height: 1123px;
    background: {t['cover_bg']};
    display: flex; flex-direction: column;
    justify-content: center;
    padding: 0 44px;
}}
.right-panel {{
    position: absolute; top: 0; left: 330px;
    width: 464px; height: 1123px;
    background: {t['page_bg']};
}}
.divider {{
    position: absolute; top: 0; left: 329px;
    width: 3px; height: 1123px;
    background: {t['accent']};
}}
.left-top-bar {{
    position: absolute; top: 0; left: 0;
    width: 330px; height: 4px;
    background: {t['accent']};
}}
.title {{
    font-family: '{t['font_display']}', 'Times New Roman', serif;
    font-weight: 900; font-size: 34px; line-height: 1.2;
    color: {t['text_light']}; margin-bottom: 18px;
    word-wrap: break-word;
}}
.rule {{
    width: 55%; height: 1.5px;
    background: {t['accent']};
    margin-bottom: 14px;
}}
.subtitle {{
    font-size: 12px; color: rgba(220,220,220,0.65);
    line-height: 1.5; margin-bottom: 32px;
}}
.author {{
    font-size: 11px; color: {t['text_light']}; margin-bottom: 4px;
}}
.date {{ font-size: 10px; color: {t['muted']}; }}
.right-label {{
    position: absolute; bottom: 60px; right: 44px;
    font-size: 9px; letter-spacing: 0.18em;
    color: {t['muted']}; text-transform: uppercase;
}}
</style>
</head>
<body>
<div class="page">
    <div class="left-top-bar"></div>
    <div class="left-panel">
        <div class="title">{t['title']}</div>
        <div class="rule"></div>
        {'<div class="subtitle">' + t['subtitle'] + '</div>' if t.get('subtitle') else ''}
        <div class="author">{t.get('author','')}</div>
        <div class="date">{t.get('date','')}</div>
    </div>
    <div class="right-panel">
        {dot_grid}
    </div>
    <div class="divider"></div>
    <div class="right-label">{t.get('doc_type','').upper()}</div>
</div>
</body></html>"""


# ── Pattern 3: Typographic ─────────────────────────────────────────────────────
def _pattern_typographic(t: dict) -> str:
    words = t['title'].split()
    first = words[0] if words else ""
    rest  = " ".join(words[1:]) if len(words) > 1 else ""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {t['page_bg']}; }}
.page {{ background: {t['page_bg']}; }}
.content {{
    position: absolute; left: 60px; top: 0; bottom: 0; right: 60px;
    display: flex; flex-direction: column; justify-content: center;
}}
.first-word {{
    font-family: '{t['font_display']}', 'Times New Roman', serif;
    font-weight: 900; font-size: 72px; line-height: 1.0;
    color: {t['accent']}; letter-spacing: -0.02em;
}}
.rest-words {{
    font-family: '{t['font_display']}', 'Times New Roman', serif;
    font-weight: 900; font-size: 72px; line-height: 1.0;
    color: {t['dark']}; letter-spacing: -0.02em;
    margin-bottom: 12px;
}}
.rule {{
    width: 100%; height: 1.5px;
    background: linear-gradient(to right, {t['accent']}, {t['accent']}40);
    margin: 28px 0 20px;
}}
.meta-row {{
    display: flex; justify-content: space-between; align-items: baseline;
}}
.author  {{ font-size: 13px; color: {t['dark']}; letter-spacing: 0.02em; }}
.date    {{ font-size: 12px; color: {t['muted']}; }}
.subtitle {{ font-size: 13px; color: {t['muted']}; margin-top: 8px; max-width: 500px; }}
</style>
</head>
<body>
<div class="page">
    <div class="content">
        <div class="first-word">{first}</div>
        {'<div class="rest-words">' + rest + '</div>' if rest else ''}
        <div class="rule"></div>
        <div class="meta-row">
            <div class="author">{t.get('author','')}</div>
            <div class="date">{t.get('date','')}</div>
        </div>
        {'<div class="subtitle">' + t['subtitle'] + '</div>' if t.get('subtitle') else ''}
    </div>
</div>
</body></html>"""


# ── Pattern 4: Dark atmospheric ────────────────────────────────────────────────
def _pattern_atmospheric(t: dict) -> str:
    dot_grid = _dot_grid(
        x0=60, y0=60, cols=16, rows=22, gap=20, r=1.5,
        color=t["accent"], opacity=0.08
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
.glow {{
    position: absolute;
    top: -100px; right: -80px;
    width: 500px; height: 500px;
    background: radial-gradient(circle, {t['accent']}2E 0%, transparent 68%);
    border-radius: 50%;
}}
.glow2 {{
    position: absolute;
    bottom: -40px; left: 10%;
    width: 300px; height: 300px;
    background: radial-gradient(circle, {t['accent']}14 0%, transparent 70%);
    border-radius: 50%;
}}
.content {{
    position: absolute; left: 64px; right: 80px;
    top: 0; bottom: 0;
    display: flex; flex-direction: column; justify-content: center;
}}
.label {{
    font-size: 9px; letter-spacing: 0.22em;
    color: {t['accent']}; text-transform: uppercase; margin-bottom: 32px;
}}
.title {{
    font-family: '{t['font_display']}', 'Times New Roman', serif;
    font-weight: 900; font-size: 50px; line-height: 1.05;
    color: {t['text_light']}; max-width: 520px;
    word-wrap: break-word; margin-bottom: 12px;
}}
.rule {{ width: 48px; height: 2px; background: {t['accent']}; margin: 24px 0 20px; }}
.subtitle {{
    font-size: 13px; color: {t['muted']}; line-height: 1.6;
    max-width: 400px; margin-bottom: 40px;
}}
.footer {{
    position: absolute; bottom: 0; left: 0; right: 0; height: 64px;
    border-top: 1px solid rgba(255,255,255,0.06);
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 64px;
}}
.footer-l {{ font-size: 10.5px; color: rgba(240,237,230,0.6); }}
.footer-r {{ font-size: 10.5px; color: {t['muted']}; }}
</style>
</head>
<body>
<div class="page">
    <div class="glow"></div>
    <div class="glow2"></div>
    {dot_grid}
    <div style="position:absolute;top:0;right:0;width:30%;height:3px;background:{t['accent']};"></div>
    <div class="content">
        <div class="label">{t.get('doc_type','').upper()} &nbsp;·&nbsp; {t.get('date','')}</div>
        <div class="title">{t['title']}</div>
        <div class="rule"></div>
        {'<div class="subtitle">' + t['subtitle'] + '</div>' if t.get('subtitle') else ''}
    </div>
    <div class="footer">
        <div class="footer-l">{t.get('author','')}</div>
        <div class="footer-r">{t.get('date','')}</div>
    </div>
</div>
</body></html>"""


# ── Pattern 5: Minimal — thick left bar, generous whitespace ───────────────────
def _pattern_minimal(t: dict) -> str:
    """
    Ultra-restrained: white background, 8px left accent bar, oversized light-weight
    title, nothing else but a hairline rule and minimal metadata. The bar is the only
    color on the page — everything else is black on white.
    """
    # Pick text color for page (minimal uses page_bg which is near-white)
    text_dark = t.get("dark", "#111111")
    muted     = t.get("muted", "#999999")
    accent    = t["accent"]

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {t['page_bg']}; }}
.page {{ background: {t['page_bg']}; }}

/* Left accent bar — the only color element */
.bar {{
    position: absolute;
    top: 0; left: 0;
    width: 8px; height: 1123px;
    background: {accent};
}}

/* Main content column — offset from bar */
.content {{
    position: absolute;
    left: 64px; right: 64px;
    top: 0; bottom: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-bottom: 40px;
}}

.eyebrow {{
    font-size: 9px;
    font-weight: 500;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: {accent};
    margin-bottom: 36px;
}}

.title {{
    font-family: '{t['font_display']}', Georgia, 'Times New Roman', serif;
    font-weight: 300;
    font-size: 72px;
    line-height: 1.0;
    color: {text_dark};
    letter-spacing: -0.02em;
    max-width: 580px;
    word-wrap: break-word;
    margin-bottom: 0;
}}

.rule {{
    width: 56px;
    height: 1px;
    background: {text_dark};
    margin: 36px 0 24px;
    opacity: 0.2;
}}

.subtitle {{
    font-size: 13px;
    font-weight: 300;
    color: {muted};
    line-height: 1.7;
    max-width: 460px;
    margin-bottom: 28px;
}}

.meta {{
    font-size: 10px;
    letter-spacing: 0.06em;
    color: {muted};
    margin-top: 4px;
}}
</style>
</head>
<body>
<div class="page">
    <div class="bar"></div>
    <div class="content">
        <div class="eyebrow">{t.get('doc_type','').upper()}</div>
        <div class="title">{t['title']}</div>
        <div class="rule"></div>
        {subtitle_block}
        <div class="meta">{t.get('author','')}{('  ·  ' + t.get('date','')) if t.get('date') else ''}</div>
    </div>
</div>
</body></html>"""


# ── Pattern 6: Stripe — bold horizontal bands ──────────────────────────────────
def _pattern_stripe(t: dict) -> str:
    """
    Page divided into three bold horizontal bands:
    - Top band (accent, ~18%): document type label
    - Middle band (dark, ~52%): large title in white
    - Bottom band (page bg, ~30%): author / date / subtitle
    Hard geometry, no gradients, no textures. Newspaper / brand poster aesthetic.
    """
    top_h    = 200   # accent band
    mid_h    = 580   # dark band
    bot_y    = top_h + mid_h  # 780

    accent   = t["accent"]
    dark     = t.get("cover_bg", "#1A1A2E")
    light    = t.get("page_bg", "#FAFAF8")
    text_l   = t.get("text_light", "#FFFFFF")
    muted    = t.get("muted", "#888888")

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {light}; }}
.page {{ background: {light}; }}

/* Three bands */
.band-top {{
    position: absolute; top: 0; left: 0;
    width: 794px; height: {top_h}px;
    background: {accent};
    display: flex; align-items: flex-end;
    padding: 0 64px 24px;
}}
.band-mid {{
    position: absolute; top: {top_h}px; left: 0;
    width: 794px; height: {mid_h}px;
    background: {dark};
    display: flex; flex-direction: column; justify-content: center;
    padding: 0 64px;
}}
.band-bot {{
    position: absolute; top: {bot_y}px; left: 0;
    width: 794px; height: {1123 - bot_y}px;
    background: {light};
    display: flex; flex-direction: column; justify-content: center;
    padding: 0 64px;
}}

/* Top band — doc type in large caps */
.eyebrow {{
    font-family: '{t['font_display']}', sans-serif;
    font-size: 11px; font-weight: 700;
    letter-spacing: 0.32em; text-transform: uppercase;
    color: {dark}; opacity: 0.85;
}}

/* Mid band — title */
.title {{
    font-family: '{t['font_display']}', 'Times New Roman', Georgia, serif;
    font-weight: 900;
    font-size: 62px;
    line-height: 0.97;
    color: {text_l};
    letter-spacing: -0.02em;
    max-width: 620px;
    word-wrap: break-word;
}}

/* Thin horizontal separator between mid and bot */
.sep {{
    position: absolute; top: {bot_y}px; left: 0;
    width: 794px; height: 2px;
    background: {accent};
}}

/* Bottom band */
.author {{
    font-size: 13px; font-weight: 500;
    color: {t.get('dark','#111')}; margin-bottom: 4px;
}}
.date   {{ font-size: 11px; color: {muted}; margin-bottom: 12px; }}
.subtitle {{
    font-size: 12px; color: {muted}; line-height: 1.6;
    max-width: 540px;
}}
</style>
</head>
<body>
<div class="page">
    <div class="band-top">
        <div class="eyebrow">{t.get('doc_type','').upper()}</div>
    </div>
    <div class="band-mid">
        <div class="title">{t['title']}</div>
    </div>
    <div class="sep"></div>
    <div class="band-bot">
        <div class="author">{t.get('author','')}</div>
        <div class="date">{t.get('date','')}</div>
        {subtitle_block}
    </div>
</div>
</body></html>"""


# ── Pattern 7: Diagonal — angled color split ───────────────────────────────────
def _pattern_diagonal(t: dict) -> str:
    """
    SVG polygon cuts the page diagonally: upper-left in dark cover color,
    lower-right in light page bg. Title sits on the dark area, metadata on light.
    One angled edge — no gradients, no curves.
    """
    dark_bg  = t.get("cover_bg", "#1B2A4A")
    light_bg = t.get("page_bg", "#FAFCFF")
    accent   = t["accent"]
    text_l   = t.get("text_light", "#F8FAFF")
    text_d   = t.get("dark", "#0F1A2E")
    muted    = t.get("muted", "#7A8A99")

    # Polygon: full upper-left to ~60% down on right side
    # Points: top-left, top-right, (794, 620), (0, 820)
    poly = "0,0 794,0 794,620 0,820"

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle-lt">{t["subtitle"]}</div>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {light_bg}; }}
.page {{ background: {light_bg}; overflow: hidden; }}

/* Title block — upper dark area */
.content-dark {{
    position: absolute;
    left: 64px; right: 64px;
    top: 180px;
    z-index: 2;
}}
.eyebrow {{
    font-size: 9px; font-weight: 500;
    letter-spacing: 0.26em; text-transform: uppercase;
    color: {accent}; margin-bottom: 28px;
}}
.title {{
    font-family: '{t['font_display']}', 'Helvetica Neue', sans-serif;
    font-weight: 900;
    font-size: 58px;
    line-height: 1.0;
    color: {text_l};
    letter-spacing: -0.018em;
    max-width: 560px;
    word-wrap: break-word;
    margin-bottom: 16px;
}}
.rule-accent {{
    width: 52px; height: 3px;
    background: {accent};
    margin-top: 28px;
}}

/* Metadata — lower light area */
.content-light {{
    position: absolute;
    left: 64px; right: 64px;
    bottom: 80px;
    z-index: 2;
}}
.author {{
    font-size: 12px; font-weight: 500;
    color: {text_d}; margin-bottom: 4px;
}}
.date   {{ font-size: 11px; color: {muted}; margin-bottom: 12px; }}
.subtitle-lt {{
    font-size: 12px; color: {muted}; line-height: 1.6;
    max-width: 480px;
}}
</style>
</head>
<body>
<div class="page">
    <!-- Diagonal dark polygon -->
    <svg style="position:absolute;top:0;left:0;width:794px;height:1123px;z-index:1"
         xmlns="http://www.w3.org/2000/svg">
        <polygon points="{poly}" fill="{dark_bg}"/>
        <!-- Accent edge line along the diagonal -->
        <line x1="0" y1="820" x2="794" y2="620"
              stroke="{accent}" stroke-width="2.5"/>
    </svg>

    <div class="content-dark">
        <div class="eyebrow">{t.get('doc_type','').upper()}&nbsp; · &nbsp;{t.get('date','')}</div>
        <div class="title">{t['title']}</div>
        <div class="rule-accent"></div>
    </div>

    <div class="content-light">
        <div class="author">{t.get('author','')}</div>
        {subtitle_block}
    </div>
</div>
</body></html>"""


# ── Pattern 8: Frame — elegant inset border ────────────────────────────────────
def _pattern_frame(t: dict) -> str:
    """
    Classic formal layout: outer thin border line inset ~28px from page edges,
    inner accent strip at top and bottom inside the frame.
    Title centered in the frame space, classical serif typography.
    Used for: academic papers, formal reports, legal docs, annual reports.
    """
    bg      = t.get("cover_bg", "#FAF8F3")
    accent  = t["accent"]
    dark    = t.get("dark", "#2A1A0A")
    muted   = t.get("muted", "#9A8A78")

    pad = 28   # frame inset from page edge
    inner_w = 794 - 2 * pad
    inner_h = 1123 - 2 * pad

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {bg}; }}
.page {{ background: {bg}; }}

/* Outer frame rectangle */
.frame {{
    position: absolute;
    top: {pad}px; left: {pad}px;
    width: {inner_w}px; height: {inner_h}px;
    border: 1.2px solid {dark};
    opacity: 0.35;
}}

/* Accent strips inside top and bottom of frame */
.frame-top-accent {{
    position: absolute;
    top: {pad + 10}px; left: {pad + 10}px;
    width: {inner_w - 20}px; height: 3px;
    background: {accent};
}}
.frame-bot-accent {{
    position: absolute;
    bottom: {pad + 10}px; left: {pad + 10}px;
    width: {inner_w - 20}px; height: 3px;
    background: {accent};
}}

/* Corner ornament squares */
.corner {{
    position: absolute;
    width: 8px; height: 8px;
    background: {accent};
    opacity: 0.6;
}}
.tl {{ top: {pad - 4}px;  left: {pad - 4}px; }}
.tr {{ top: {pad - 4}px;  right: {pad - 4}px; }}
.bl {{ bottom: {pad - 4}px; left: {pad - 4}px; }}
.br {{ bottom: {pad - 4}px; right: {pad - 4}px; }}

/* Main content centered in frame */
.content {{
    position: absolute;
    left: {pad + 56}px; right: {pad + 56}px;
    top: 0; bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
}}

.eyebrow {{
    font-size: 8.5px;
    font-weight: 500;
    letter-spacing: 0.30em;
    text-transform: uppercase;
    color: {accent};
    margin-bottom: 44px;
}}

.rule-top {{
    width: 60px; height: 1px;
    background: {dark};
    opacity: 0.3;
    margin-bottom: 28px;
}}

.title {{
    font-family: '{t['font_display']}', Georgia, 'Times New Roman', serif;
    font-weight: 400;
    font-size: 44px;
    line-height: 1.25;
    color: {dark};
    letter-spacing: 0.01em;
    max-width: 540px;
    word-wrap: break-word;
    margin-bottom: 0;
}}

.rule-mid {{
    width: 40px; height: 1.5px;
    background: {accent};
    margin: 28px 0 20px;
}}

.subtitle {{
    font-size: 13px;
    font-weight: 300;
    font-style: italic;
    color: {muted};
    line-height: 1.6;
    max-width: 400px;
    margin-bottom: 20px;
}}

.meta {{
    font-size: 10px;
    letter-spacing: 0.08em;
    color: {muted};
    margin-top: 8px;
}}
</style>
</head>
<body>
<div class="page">
    <div class="frame"></div>
    <div class="frame-top-accent"></div>
    <div class="frame-bot-accent"></div>
    <div class="corner tl"></div>
    <div class="corner tr"></div>
    <div class="corner bl"></div>
    <div class="corner br"></div>

    <div class="content">
        <div class="eyebrow">{t.get('doc_type','').upper()}</div>
        <div class="rule-top"></div>
        <div class="title">{t['title']}</div>
        <div class="rule-mid"></div>
        {subtitle_block}
        <div class="meta">{t.get('author','')}{('  ·  ' + t.get('date','')) if t.get('date') else ''}</div>
    </div>
</div>
</body></html>"""


# ── Pattern 9: Editorial — oversized ghost letter + bold type ──────────────────
def _pattern_editorial(t: dict) -> str:
    """
    Magazine / editorial feel:
    - Oversized first-letter of title as a ghost background element (8–12% opacity)
    - Bold category label at top in accent
    - Title in very large condensed weight, flush-left
    - Thin full-width rule separating title from metadata
    - Author / date bottom-left, page type bottom-right
    Designed for editorial reports, annual reviews, magazine-format content.
    """
    bg      = t.get("cover_bg", "#FFFFFF")
    accent  = t["accent"]
    dark    = t.get("dark", "#0A0A0A")
    muted   = t.get("muted", "#777777")
    text_l  = t.get("text_light", "#FFFFFF")

    # Ghost letter — first character of title
    ghost = t['title'][0].upper() if t['title'] else "A"

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    # Determine if background is dark (use light text) or light (use dark text)
    is_dark_bg = (
        bg.startswith("#0") or bg.startswith("#1") or bg.startswith("#2")
    )
    title_color = text_l if is_dark_bg else dark  # noqa: F841
    body_color  = text_l if is_dark_bg else dark

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {bg}; }}
.page {{ background: {bg}; }}

/* Ghost letter — background texture */
.ghost {{
    position: absolute;
    right: -60px; top: -40px;
    font-family: '{t['font_display']}', 'Arial Black', sans-serif;
    font-weight: 900;
    font-size: 680px;
    line-height: 1;
    color: {dark};
    opacity: 0.055;
    user-select: none;
    letter-spacing: -0.05em;
}}

/* Top bar: accent stripe */
.topbar {{
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 5px;
    background: {accent};
}}

/* Category label */
.category {{
    position: absolute;
    top: 40px; left: 60px;
    font-size: 9px; font-weight: 700;
    letter-spacing: 0.30em; text-transform: uppercase;
    color: {accent};
}}

/* Main title block */
.content {{
    position: absolute;
    left: 60px; right: 60px;
    top: 0; bottom: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-bottom: 80px;
}}

.title {{
    font-family: '{t['font_display']}', 'Arial Black', Impact, sans-serif;
    font-weight: 900;
    font-size: 80px;
    line-height: 0.92;
    color: {body_color};
    letter-spacing: -0.03em;
    max-width: 620px;
    word-wrap: break-word;
    text-transform: uppercase;
}}

.subtitle {{
    font-size: 14px;
    font-weight: 400;
    color: {muted};
    line-height: 1.6;
    max-width: 500px;
    margin-top: 20px;
}}

/* Full-width rule above footer */
.footer-rule {{
    position: absolute;
    bottom: 80px; left: 60px; right: 60px;
    height: 1px;
    background: {body_color};
    opacity: 0.15;
}}

/* Footer row */
.footer {{
    position: absolute;
    bottom: 44px; left: 60px; right: 60px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}
.footer-author {{ font-size: 11px; color: {muted}; letter-spacing: 0.04em; }}
.footer-date   {{ font-size: 10px; color: {muted}; letter-spacing: 0.04em; }}
</style>
</head>
<body>
<div class="page">
    <div class="ghost">{ghost}</div>
    <div class="topbar"></div>
    <div class="category">{t.get('doc_type','').upper()}</div>

    <div class="content">
        <div class="title">{t['title']}</div>
        {subtitle_block}
    </div>

    <div class="footer-rule"></div>
    <div class="footer">
        <div class="footer-author">{t.get('author','')}</div>
        <div class="footer-date">{t.get('date','')}</div>
    </div>
</div>
</body></html>"""


# ── Pattern 10: Magazine — elegant centered with optional hero image ────────────
def _pattern_magazine(t: dict) -> str:
    """
    Upscale centered layout: company name + accent rule at top, large serif title,
    decorative rule, italic subtitle, optional hero image, abstract block, author.
    Used for: annual reports, strategic documents, formal publications.
    """
    bg       = t.get("cover_bg", "#F2F0EC")
    accent   = t["accent"]
    dark     = t.get("dark", "#0D1A2B")
    muted    = t.get("muted", "#888888")
    org      = t.get("doc_type", "").upper()
    img_url  = t.get("cover_image", "")

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    image_block = ""
    if img_url:
        image_block = f"""
        <div style="text-align:center;margin:32px 0 28px;">
            <img src="{img_url}" style="max-width:340px;max-height:220px;
                 object-fit:cover;display:inline-block;"/>
        </div>"""

    abstract_block = ""
    if t.get("abstract"):
        abstract_block = f"""
        <div style="font-size:11px;line-height:1.7;color:{muted};
                    text-align:justify;max-width:560px;margin:0 auto 0;">
            <span style="font-weight:700;color:{accent};">Abstract:</span>
            {t['abstract']}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {bg}; }}
.page {{ background: {bg}; display:flex; flex-direction:column;
         align-items:center; justify-content:center; padding:60px 80px; }}

.org-name {{
    font-size: 9px; font-weight: 500; letter-spacing: 0.30em;
    text-transform: uppercase; color: {dark}; text-align:center;
    margin-bottom: 10px;
}}
.org-rule {{
    width: 56px; height: 2px; background: {accent};
    margin: 0 auto 52px;
}}
.title {{
    font-family: '{t['font_display']}', Georgia, 'Times New Roman', serif;
    font-weight: 700; font-size: 52px; line-height: 1.08;
    color: {dark}; text-align: center; letter-spacing: -0.015em;
    max-width: 560px; word-wrap: break-word; margin-bottom: 18px;
}}
.title-rule {{
    width: 44px; height: 2.5px; background: {accent};
    margin: 0 auto 20px;
}}
.subtitle {{
    font-family: '{t['font_display']}', Georgia, serif;
    font-style: italic; font-size: 14px; color: {muted};
    text-align: center; line-height: 1.5; max-width: 440px;
    margin: 0 auto;
}}
.separator {{
    width: 100%; max-width: 620px; height: 1px;
    background: {dark}; opacity: 0.12;
    margin: 28px auto;
}}
.author-name {{
    font-family: '{t['font_display']}', Georgia, serif;
    font-size: 16px; font-weight: 700; color: {accent};
    text-align: center; margin-bottom: 6px;
}}
.date-line {{
    font-size: 11px; color: {muted}; text-align: center;
    letter-spacing: 0.03em;
}}
</style>
</head>
<body>
<div class="page">
    <div class="org-name">{org}</div>
    <div class="org-rule"></div>
    <div class="title">{t['title']}</div>
    <div class="title-rule"></div>
    {subtitle_block}
    {image_block}
    {abstract_block}
    {'<div class="separator"></div>' if (t.get('abstract') or img_url) else '<div style="margin:28px 0;"></div>'}
    <div class="author-name">{t.get('author','')}</div>
    <div class="date-line">{t.get('date','')}</div>
</div>
</body></html>"""


# ── Pattern 11: Darkroom — dark magazine variant ────────────────────────────────
def _pattern_darkroom(t: dict) -> str:
    """
    Dark-background centered layout. Same structure as magazine but inverted:
    deep navy page, white/silver text, accent rules in lighter tone.
    Used for: premium reports, tech annual reviews, dark-themed documents.
    """
    bg       = t.get("cover_bg", "#151C27")
    accent   = t["accent"]
    text_l   = t.get("text_light", "#F0EDE6")
    muted    = t.get("muted", "#8A9AB0")
    org      = t.get("doc_type", "").upper()
    img_url  = t.get("cover_image", "")

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    image_block = ""
    if img_url:
        image_block = f"""
        <div style="text-align:center;margin:32px 0 28px;">
            <img src="{img_url}" style="max-width:340px;max-height:220px;
                 object-fit:cover;display:inline-block;
                 filter:grayscale(20%) brightness(0.9);"/>
        </div>"""

    abstract_block = ""
    if t.get("abstract"):
        abstract_block = f"""
        <div style="font-size:11px;line-height:1.7;color:{muted};
                    text-align:justify;max-width:560px;margin:0 auto 0;">
            <span style="font-weight:700;color:{accent};">Abstract:</span>
            {t['abstract']}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {bg}; }}
.page {{ background: {bg}; display:flex; flex-direction:column;
         align-items:center; justify-content:center; padding:60px 80px; }}

.org-name {{
    font-size: 9px; font-weight: 500; letter-spacing: 0.30em;
    text-transform: uppercase; color: {text_l}; text-align:center;
    opacity: 0.75; margin-bottom: 10px;
}}
.org-rule {{
    width: 56px; height: 2px; background: {text_l};
    opacity: 0.35; margin: 0 auto 52px;
}}
.title {{
    font-family: '{t['font_display']}', Georgia, 'Times New Roman', serif;
    font-weight: 700; font-size: 52px; line-height: 1.08;
    color: {text_l}; text-align: center; letter-spacing: -0.015em;
    max-width: 560px; word-wrap: break-word; margin-bottom: 18px;
}}
.title-rule {{
    width: 44px; height: 2.5px; background: {text_l};
    opacity: 0.35; margin: 0 auto 20px;
}}
.subtitle {{
    font-family: '{t['font_display']}', Georgia, serif;
    font-style: italic; font-size: 14px; color: {muted};
    text-align: center; line-height: 1.5; max-width: 440px;
    margin: 0 auto;
}}
.separator {{
    width: 100%; max-width: 620px; height: 1px;
    background: {text_l}; opacity: 0.12;
    margin: 28px auto;
}}
.author-name {{
    font-family: '{t['font_display']}', Georgia, serif;
    font-size: 16px; font-weight: 700; color: {text_l};
    text-align: center; margin-bottom: 6px;
}}
.date-line {{
    font-size: 11px; color: {muted}; text-align: center;
    letter-spacing: 0.03em;
}}
</style>
</head>
<body>
<div class="page">
    <div class="org-name">{org}</div>
    <div class="org-rule"></div>
    <div class="title">{t['title']}</div>
    <div class="title-rule"></div>
    {subtitle_block}
    {image_block}
    {abstract_block}
    {'<div class="separator"></div>' if (t.get('abstract') or img_url) else '<div style="margin:28px 0;"></div>'}
    <div class="author-name">{t.get('author','')}</div>
    <div class="date-line">{t.get('date','')}</div>
</div>
</body></html>"""


# ── Pattern 12: Terminal — cyber/hacker aesthetic ───────────────────────────────
def _pattern_terminal(t: dict) -> str:
    """
    Dark terminal/IDE aesthetic: grid overlay, monospace font, neon accent,
    corner brackets around the title block, status bar at bottom.
    Used for: tech reports, developer docs, security audits, system documentation.
    """
    bg      = t.get("cover_bg", "#0D1117")
    accent  = t["accent"]
    text_l  = t.get("text_light", "#E6EDF3")
    muted   = t.get("muted", "#48897C")
    dark    = t.get("dark", "#010409")
    org     = t.get("doc_type", "DOCUMENT").upper()
    date_s  = t.get("date", "")
    author  = t.get("author", "")

    subtitle_line = ""
    if t.get("subtitle"):
        subtitle_line = f'<div class="subtitle">&gt; {t["subtitle"]}</div>'

    abstract_block = ""
    if t.get("abstract"):
        abstract_block = f"""
        <div class="abstract-text">{t['abstract']}</div>"""

    # grid overlay: horizontal + vertical lines
    h_lines = "".join(
        f'<line x1="0" y1="{y}" x2="794" y2="{y}" stroke="{accent}" stroke-width="0.4"/>'
        for y in range(0, 1124, 48)
    )
    v_lines = "".join(
        f'<line x1="{x}" y1="0" x2="{x}" y2="1123" stroke="{accent}" stroke-width="0.4"/>'
        for x in range(0, 795, 48)
    )
    grid_svg = (
        f'<svg style="position:absolute;top:0;left:0;width:794px;height:1123px;'
        f'pointer-events:none;opacity:0.07" xmlns="http://www.w3.org/2000/svg">'
        + h_lines + v_lines + "</svg>"
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {bg}; }}
.page {{ background: {bg}; }}

/* Terminal label — top */
.term-label {{
    position: absolute; top: 44px; left: 56px; right: 56px;
    display: flex; align-items: center; gap: 10px;
}}
.dot {{
    width: 8px; height: 8px; border-radius: 50%;
    background: {accent}; flex-shrink: 0;
}}
.term-meta {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    font-size: 10px; color: {accent}; letter-spacing: 0.08em;
    text-transform: uppercase;
}}

/* Title bracket block */
.bracket-block {{
    position: absolute;
    top: 310px; left: 56px; right: 56px;
    border-left: 2px solid {accent}; border-top: 2px solid {accent};
    padding: 24px 28px 28px;
    box-shadow: inset 0 0 0 0;
}}
.bracket-block::after {{
    content: '';
    position: absolute;
    bottom: 0; right: 0;
    width: 32px; height: 2px;
    background: {accent};
}}
.bracket-block::before {{
    content: '';
    position: absolute;
    bottom: 0; right: 0;
    width: 2px; height: 32px;
    background: {accent};
}}

.title {{
    font-family: '{t['font_display']}', 'Courier New', monospace;
    font-weight: 700; font-size: 46px; line-height: 1.05;
    color: {text_l}; letter-spacing: 0.01em;
    text-transform: uppercase;
    word-wrap: break-word; margin-bottom: 16px;
}}
.subtitle {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    font-size: 13px; color: {accent};
    line-height: 1.5; letter-spacing: 0.02em;
    margin-top: 8px;
}}

/* Content block below brackets */
.content-lower {{
    position: absolute;
    top: 640px; left: 56px; right: 56px;
    display: flex; gap: 40px; align-items: flex-start;
}}
.abstract-text {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    font-size: 10.5px; line-height: 1.8; color: {muted};
    flex: 1;
}}
.author-block {{
    text-align: right; flex-shrink: 0; min-width: 160px;
}}
.author-label {{
    font-family: '{t['font_body']}', monospace;
    font-size: 8px; letter-spacing: 0.20em; color: {muted};
    text-transform: uppercase; margin-bottom: 6px;
}}
.author-name {{
    font-family: '{t['font_body']}', monospace;
    font-size: 14px; font-weight: 700; color: {text_l};
}}
.author-org {{
    font-family: '{t['font_body']}', monospace;
    font-size: 10px; color: {accent}; margin-top: 4px;
}}

/* Bottom status bar */
.statusbar {{
    position: absolute; bottom: 0; left: 0; right: 0;
    height: 36px; background: {accent}; opacity: 0.12;
}}
.statusbar-text {{
    position: absolute; bottom: 0; left: 0; right: 0;
    height: 36px; display: flex; align-items: center;
    justify-content: space-between; padding: 0 56px;
}}
.sb-item {{
    font-family: '{t['font_body']}', monospace;
    font-size: 9px; color: {muted}; letter-spacing: 0.12em;
    text-transform: uppercase;
}}
</style>
</head>
<body>
<div class="page">
    {grid_svg}

    <div class="term-label">
        <div class="dot"></div>
        <div class="term-meta">SYSTEM_REPORT // {date_s}</div>
    </div>

    <div class="bracket-block">
        <div class="title">{t['title']}</div>
        {subtitle_line}
    </div>

    <div class="content-lower">
        {abstract_block}
        <div class="author-block">
            <div class="author-label">AUTHOR_ID</div>
            <div class="author-name">{author}</div>
            <div class="author-org">{org}</div>
        </div>
    </div>

    <div class="statusbar"></div>
    <div class="statusbar-text">
        <div class="sb-item">Ln 1, Col 1</div>
        <div class="sb-item">UTF-8</div>
        <div class="sb-item">GENERATED_BY_COVERGENIUS</div>
    </div>
</div>
</body></html>"""


# ── Pattern 13: Poster — bold sidebar + oversized type ─────────────────────────
def _pattern_poster(t: dict) -> str:
    """
    Bold minimalist poster: thick vertical sidebar on the left, oversized all-caps
    title, typewriter-style metadata. Optional thumbnail on the right side.
    Used for: portfolios, creative reports, journalism, photography books.
    """
    bg      = t.get("cover_bg", "#FFFFFF")
    accent  = t["accent"]       # typically black or strong dark
    dark    = t.get("dark", "#0A0A0A")
    muted   = t.get("muted", "#888888")
    text_l  = t.get("text_light", "#FFFFFF")
    img_url = t.get("cover_image", "")

    sidebar_w = 52

    subtitle_block = ""
    if t.get("subtitle"):
        subtitle_block = f'<div class="subtitle">{t["subtitle"]}</div>'

    image_block = ""
    if img_url:
        image_block = f"""
        <img src="{img_url}" style="
            width:260px;height:340px;object-fit:cover;
            display:block;margin-top:32px;
            filter:grayscale(100%) contrast(1.1);"/>"""

    meta_lines = []
    if t.get("author"):
        meta_lines.append(f'<div class="meta-line">{t["author"]}</div>')
    if t.get("subtitle"):
        meta_lines.append(f'<div class="meta-line meta-role">{t["subtitle"]}</div>')
    if t.get("date"):
        meta_lines.append(f'<div class="meta-line meta-date">{t["date"]}</div>')
    meta_block = "\n".join(meta_lines)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<style>
{_base_css(t)}
html, body {{ background: {bg}; }}
.page {{ background: {bg}; }}

/* Left sidebar — the dominant color element */
.sidebar {{
    position: absolute;
    top: 0; left: 0;
    width: {sidebar_w}px; height: 1123px;
    background: {accent};
}}

/* Main content — offset from sidebar */
.content {{
    position: absolute;
    left: {sidebar_w + 52}px; right: 52px;
    top: 100px; bottom: 80px;
}}

/* Oversized display title */
.title {{
    font-family: '{t['font_display']}', 'Arial Black', Impact, sans-serif;
    font-weight: 900;
    font-size: 96px;
    line-height: 0.92;
    color: {dark};
    letter-spacing: -0.03em;
    text-transform: uppercase;
    max-width: 620px;
    word-wrap: break-word;
    margin-bottom: 22px;
}}

.subtitle {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    font-size: 12px;
    color: {muted};
    letter-spacing: 0.05em;
    margin-bottom: 0;
}}

/* Thin rule under title area */
.rule {{
    width: 64px; height: 2px;
    background: {dark};
    margin: 24px 0 28px;
}}

/* Author / meta in typewriter font */
.meta-group {{
    margin-top: 32px;
}}
.meta-line {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    font-size: 12px; color: {dark};
    line-height: 1.8; letter-spacing: 0.02em;
}}
.meta-role {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    color: {muted};
}}
.meta-date {{
    font-family: '{t['font_body']}', 'Courier New', monospace;
    font-size: 12px; color: {dark};
    margin-top: 8px;
}}

/* Right-side content area for thumbnail */
.right-col {{
    position: absolute;
    right: 52px;
    top: 380px; bottom: 80px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
}}

/* Small accent square icon */
.icon-block {{
    width: 64px; height: 64px;
    background: {accent};
    margin-top: 28px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}}
.icon-lines {{
    display: flex; flex-direction: column; gap: 6px;
}}
.icon-line {{
    height: 2px; background: {text_l};
}}
</style>
</head>
<body>
<div class="page">
    <div class="sidebar"></div>

    <div class="content">
        <div class="title">{t['title']}</div>
        {subtitle_block}
        <div class="rule"></div>
        <div class="meta-group">{meta_block}</div>
    </div>

    <div class="right-col">
        {image_block}
        <div class="icon-block">
            <div class="icon-lines">
                <div class="icon-line" style="width:32px;"></div>
                <div class="icon-line" style="width:24px;"></div>
                <div class="icon-line" style="width:28px;"></div>
            </div>
        </div>
    </div>
</div>
</body></html>"""


# ── Dispatch ───────────────────────────────────────────────────────────────────
PATTERNS = {
    "fullbleed":   _pattern_fullbleed,
    "split":       _pattern_split,
    "typographic": _pattern_typographic,
    "atmospheric": _pattern_atmospheric,
    "minimal":     _pattern_minimal,
    "stripe":      _pattern_stripe,
    "diagonal":    _pattern_diagonal,
    "frame":       _pattern_frame,
    "editorial":   _pattern_editorial,
    "magazine":    _pattern_magazine,
    "darkroom":    _pattern_darkroom,
    "terminal":    _pattern_terminal,
    "poster":      _pattern_poster,
}


def render(tokens: dict) -> str:
    """Dispatch to the cover pattern function and return the HTML string."""
    pattern = tokens.get("cover_pattern", "fullbleed")
    fn = PATTERNS.get(pattern, _pattern_fullbleed)
    return fn(tokens)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Render cover HTML from tokens.json")
    parser.add_argument("--tokens", default="tokens.json")
    parser.add_argument("--out",    default="cover.html")
    parser.add_argument("--subtitle", default="", help="Optional subtitle override")
    args = parser.parse_args()

    try:
        with open(args.tokens, encoding="utf-8") as f:
            tokens = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"status": "error", "error": f"tokens file not found: {args.tokens}"}),
              file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "error": f"invalid JSON: {e}"}), file=sys.stderr)
        sys.exit(1)

    if args.subtitle:
        tokens["subtitle"] = args.subtitle

    html = render(tokens)

    try:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(3)

    print(json.dumps({
        "status":  "ok",
        "out":     args.out,
        "pattern": tokens.get("cover_pattern"),
    }))


if __name__ == "__main__":
    main()
