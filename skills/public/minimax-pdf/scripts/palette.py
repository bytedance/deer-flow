#!/usr/bin/env python3
"""
palette.py — Infer design tokens from document metadata.

Usage:
    python3 palette.py --title "AI Trends 2025" --type report --out tokens.json
    python3 palette.py --title "John Doe Resume" --type resume --out tokens.json
    python3 palette.py --meta meta.json --out tokens.json

Outputs tokens.json consumed by all downstream scripts.
Cover fonts are loaded via Google Fonts @import in the cover HTML (no local caching).
Body fonts always use ReportLab system fonts (Times-Bold / Helvetica).
Exit codes: 0 success, 1 bad args, 3 write error
"""

import argparse
import json
import sys

# ── Palette library ────────────────────────────────────────────────────────────
# Each entry: cover colors + cover_pattern + mood
PALETTES = {
    "report": {
        # Charcoal blue-grey cover; muted steel blue accent — authoritative, not flashy
        "cover_bg":   "#1B2A38",
        "accent":     "#3B6D8A",
        "accent_lt":  "#E6EFF5",
        "text_light": "#EDE9E2",
        "page_bg":    "#FAFAF8",
        "dark":       "#1A1E24",
        "body_text":  "#2C2C30",
        "muted":      "#7A7A84",
        "cover_pattern": "fullbleed",
        "mood": "authoritative",
    },
    "proposal": {
        # Dark charcoal cover; slate grey-blue accent — confident, understated
        "cover_bg":   "#22272E",
        "accent":     "#4E6070",
        "accent_lt":  "#EAECEE",
        "text_light": "#EDE9E2",
        "page_bg":    "#FAFAF7",
        "dark":       "#18191E",
        "body_text":  "#28282E",
        "muted":      "#7A7870",
        "cover_pattern": "split",
        "mood": "confident",
    },
    "resume": {
        # White; deep navy accent — clean and unambiguous
        "cover_bg":   "#FFFFFF",
        "accent":     "#1C3557",
        "accent_lt":  "#E8EEF5",
        "text_light": "#FFFFFF",
        "page_bg":    "#FFFFFF",
        "dark":       "#111111",
        "body_text":  "#222222",
        "muted":      "#888888",
        "cover_pattern": "typographic",
        "mood": "clean",
    },
    "portfolio": {
        # Near-black charcoal; cool slate grey accent — subdued professional
        "cover_bg":   "#191C20",
        "accent":     "#6A7A88",
        "accent_lt":  "#EAECEE",
        "text_light": "#EDE9E4",
        "page_bg":    "#F8F8F8",
        "dark":       "#18191E",
        "body_text":  "#28282E",
        "muted":      "#8A8A96",
        "cover_pattern": "atmospheric",
        "mood": "expressive",
    },
    "academic": {
        # Warm white; classic navy accent — scholarly standard
        "cover_bg":   "#F5F4F0",
        "accent":     "#2A436A",
        "accent_lt":  "#E6EBF4",
        "text_light": "#FFFFFF",
        "page_bg":    "#F5F4F0",
        "dark":       "#1A1A28",
        "body_text":  "#1E1E2A",
        "muted":      "#686877",
        "cover_pattern": "typographic",
        "mood": "scholarly",
    },
    "general": {
        # Dark slate; muted steel accent — neutral, no-nonsense
        "cover_bg":   "#1F2329",
        "accent":     "#4A6070",
        "accent_lt":  "#E6EAEC",
        "text_light": "#EEEBE5",
        "page_bg":    "#F8F6F2",
        "dark":       "#1A1A1A",
        "body_text":  "#2C2C2C",
        "muted":      "#888888",
        "cover_pattern": "fullbleed",
        "mood": "neutral",
    },
    # ── Extended types — each uses a distinct new cover pattern ─────────────────
    "minimal": {
        # Warm off-white; dark neutral grey — truly restrained, no color signal
        "cover_bg":   "#F7F6F4",
        "accent":     "#4A4A4A",
        "accent_lt":  "#EBEBEA",
        "text_light": "#F7F6F4",
        "page_bg":    "#F7F6F4",
        "dark":       "#111111",
        "body_text":  "#222222",
        "muted":      "#999999",
        "cover_pattern": "minimal",
        "mood": "restrained",
    },
    "stripe": {
        # Near-black; charcoal slate accent — structured, no-nonsense
        "cover_bg":   "#1E222A",
        "accent":     "#4A5568",
        "accent_lt":  "#EAECEE",
        "text_light": "#FFFFFF",
        "page_bg":    "#F8F8F7",
        "dark":       "#0E1117",
        "body_text":  "#262630",
        "muted":      "#888898",
        "cover_pattern": "stripe",
        "mood": "bold",
    },
    "diagonal": {
        # Deep navy; muted slate-blue accent — dignified, controlled
        "cover_bg":   "#1A2535",
        "accent":     "#3D5A72",
        "accent_lt":  "#E4EBF0",
        "text_light": "#EEF0F5",
        "page_bg":    "#F8FAFC",
        "dark":       "#0F1A2A",
        "body_text":  "#1E2C3A",
        "muted":      "#7A8A96",
        "cover_pattern": "diagonal",
        "mood": "dynamic",
    },
    "frame": {
        # Warm parchment; dark muted brown — classical, formal
        "cover_bg":   "#F5F2EC",
        "accent":     "#5C4A38",
        "accent_lt":  "#EAE5DE",
        "text_light": "#F5F2EC",
        "page_bg":    "#F5F2EC",
        "dark":       "#2A1E14",
        "body_text":  "#2C2018",
        "muted":      "#9A8A78",
        "cover_pattern": "frame",
        "mood": "classical",
    },
    "editorial": {
        # White; deep burgundy accent — editorial weight without the shout
        "cover_bg":   "#FFFFFF",
        "accent":     "#7A2B36",
        "accent_lt":  "#EEE4E5",
        "text_light": "#FFFFFF",
        "page_bg":    "#FFFFFF",
        "dark":       "#0A0A0A",
        "body_text":  "#1A1A1A",
        "muted":      "#777777",
        "cover_pattern": "editorial",
        "mood": "editorial",
    },
    # ── New patterns (v2) ────────────────────────────────────────────────────────
    "magazine": {
        # Warm linen; deep navy accent — formal publication standard
        "cover_bg":   "#F0EEE9",
        "accent":     "#1C3557",
        "accent_lt":  "#E4EBF3",
        "text_light": "#FFFFFF",
        "page_bg":    "#F0EEE9",
        "dark":       "#0D1A2B",
        "body_text":  "#2A2A2A",
        "muted":      "#888888",
        "cover_pattern": "magazine",
        "mood": "magazine",
    },
    "darkroom": {
        # Deep navy; muted steel-blue accent — premium, controlled
        "cover_bg":   "#151C27",
        "accent":     "#3D5A7A",
        "accent_lt":  "#E2EBF2",
        "text_light": "#EDE9E2",
        "page_bg":    "#F7F7F5",
        "dark":       "#0A1018",
        "body_text":  "#2C2C2C",
        "muted":      "#8A9AB0",
        "cover_pattern": "darkroom",
        "mood": "darkroom",
    },
    "terminal": {
        # Near-black; forest green accent — technical, serious (not neon)
        "cover_bg":   "#0D1117",
        "accent":     "#3D7A5C",
        "accent_lt":  "#E2EEE8",
        "text_light": "#E6EDF3",
        "page_bg":    "#F8F8F6",
        "dark":       "#010409",
        "body_text":  "#2C2C2C",
        "muted":      "#5A7A6A",
        "cover_pattern": "terminal",
        "mood": "terminal",
    },
    "poster": {
        # White; near-black accent sidebar — stark, unambiguous
        "cover_bg":   "#FFFFFF",
        "accent":     "#0A0A0A",
        "accent_lt":  "#EBEBEA",
        "text_light": "#FFFFFF",
        "page_bg":    "#FFFFFF",
        "dark":       "#0A0A0A",
        "body_text":  "#1A1A1A",
        "muted":      "#888888",
        "cover_pattern": "poster",
        "mood": "poster",
    },
}

# ── Font pairs — CSS names for cover HTML, ReportLab names for body ─────────────
# cover uses Google Fonts via @import (no local disk caching needed)
# body always uses system fonts via ReportLab
FONT_PAIRS = {
    "authoritative": {
        "display_css":  "Playfair Display",
        "body_css":     "IBM Plex Sans",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=IBM+Plex+Sans:ital,wght@0,400;0,600;1,400&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "confident": {
        "display_css":  "Syne",
        "body_css":     "Nunito Sans",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Syne:wght@600;800&family=Nunito+Sans:wght@400;600;700&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "clean": {
        "display_css":  "DM Serif Display",
        "body_css":     "DM Sans",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "expressive": {
        "display_css":  "Fraunces",
        "body_css":     "Inter",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,700;0,900;1,900&family=Inter:wght@300;400;500&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "scholarly": {
        "display_css":  "EB Garamond",
        "body_css":     "Source Sans 3",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,700;1,400&family=Source+Sans+3:wght@400;600&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "neutral": {
        "display_css":  "Outfit",
        "body_css":     "Outfit",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;700;900&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "restrained": {
        "display_css":  "Cormorant Garamond",
        "body_css":     "Jost",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,600;1,300&family=Jost:wght@300;400;500&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "bold": {
        "display_css":  "Barlow Condensed",
        "body_css":     "Barlow",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;900&family=Barlow:wght@400;500;600&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "dynamic": {
        "display_css":  "Montserrat",
        "body_css":     "Montserrat",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,300;0,700;0,900;1,400&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "classical": {
        "display_css":  "Cormorant",
        "body_css":     "Crimson Pro",
        "gfonts_import": "https://fonts.googleapis.com/css2?family=Cormorant:ital,wght@0,400;0,700;1,400&family=Crimson+Pro:wght@400;600&display=swap",
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "editorial": {
        "display_css":  "Bebas Neue",
        "body_css":     "Libre Franklin",
        "gfonts_import": (
            "https://fonts.googleapis.com/css2?family=Bebas+Neue"
            "&family=Libre+Franklin:ital,wght@0,400;0,700;1,400&display=swap"
        ),
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    # ── New moods (v2) ───────────────────────────────────────────────────────────
    "magazine": {
        "display_css":  "Playfair Display",
        "body_css":     "EB Garamond",
        "gfonts_import": (
            "https://fonts.googleapis.com/css2?family=Playfair+Display"
            ":ital,wght@0,700;0,900;1,700"
            "&family=EB+Garamond:ital,wght@0,400;0,600;1,400&display=swap"
        ),
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "darkroom": {
        "display_css":  "Playfair Display",
        "body_css":     "EB Garamond",
        "gfonts_import": (
            "https://fonts.googleapis.com/css2?family=Playfair+Display"
            ":ital,wght@0,700;0,900;1,700"
            "&family=EB+Garamond:ital,wght@0,400;0,600;1,400&display=swap"
        ),
        "display_rl":   "Times-Bold",
        "body_rl":      "Helvetica",
        "body_b_rl":    "Helvetica-Bold",
    },
    "terminal": {
        "display_css":  "Space Mono",
        "body_css":     "Space Mono",
        "gfonts_import": (
            "https://fonts.googleapis.com/css2?family=Space+Mono"
            ":ital,wght@0,400;0,700;1,400&display=swap"
        ),
        "display_rl":   "Courier-Bold",
        "body_rl":      "Courier",
        "body_b_rl":    "Courier-Bold",
    },
    "poster": {
        "display_css":  "Barlow Condensed",
        "body_css":     "Courier Prime",
        "gfonts_import": (
            "https://fonts.googleapis.com/css2?family=Barlow+Condensed"
            ":wght@700;900"
            "&family=Courier+Prime:ital,wght@0,400;0,700;1,400&display=swap"
        ),
        "display_rl":   "Times-Bold",
        "body_rl":      "Courier",
        "body_b_rl":    "Courier-Bold",
    },
}

SYSTEM_FALLBACK = {
    "display_css":  "Georgia",
    "body_css":     "Arial",
    "gfonts_import": "",
    "display_rl":   "Times-Bold",
    "body_rl":      "Helvetica",
    "body_b_rl":    "Helvetica-Bold",
}


# ── Colour helpers ──────────────────────────────────────────────────────────────
def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lighten(hex_color: str, factor: float = 0.09) -> str:
    """Blend hex_color toward white (factor = accent weight, 0=white, 1=full color)."""
    r, g, b = _hex_to_rgb(hex_color)
    return "#{:02X}{:02X}{:02X}".format(
        round(r * factor + 255 * (1 - factor)),
        round(g * factor + 255 * (1 - factor)),
        round(b * factor + 255 * (1 - factor)),
    )


# ── Token assembly ─────────────────────────────────────────────────────────────
def build_tokens(
    title: str,
    doc_type: str,
    author: str = "",
    date: str = "",
    accent_override: str = "",
    cover_bg_override: str = "",
) -> dict:
    palette   = PALETTES.get(doc_type, PALETTES["general"]).copy()
    mood      = palette["mood"]
    font_pair = FONT_PAIRS.get(mood, SYSTEM_FALLBACK)

    # Apply caller-supplied overrides before token assembly
    if accent_override:
        palette["accent"]    = accent_override
        palette["accent_lt"] = _lighten(accent_override, 0.09)
    if cover_bg_override:
        palette["cover_bg"] = cover_bg_override

    tokens = {
        # Identity
        "title":    title,
        "author":   author,
        "date":     date,
        "doc_type": doc_type,

        # Palette
        "cover_bg":      palette["cover_bg"],
        "accent":        palette["accent"],
        "accent_lt":     palette["accent_lt"],
        "text_light":    palette["text_light"],
        "page_bg":       palette["page_bg"],
        "dark":          palette["dark"],
        "body_text":     palette["body_text"],
        "muted":         palette["muted"],
        "cover_pattern": palette["cover_pattern"],
        "mood":          mood,

        # Typography — CSS names for cover HTML (loaded via Google Fonts @import)
        "font_display":     font_pair["display_css"],
        "font_body":        font_pair["body_css"],
        "gfonts_import":    font_pair["gfonts_import"],

        # Typography — ReportLab system font names for body pages
        "font_display_rl":  font_pair["display_rl"],
        "font_body_rl":     font_pair["body_rl"],
        "font_body_b_rl":   font_pair["body_b_rl"],

        # Legacy keys (kept so render_body.py's register_fonts is a no-op)
        "font_heading":  font_pair["display_rl"],
        "font_body_b":   font_pair["body_b_rl"],
        "font_paths":    {},

        # Type scale (pt)
        "size_display": 54,
        "size_h1":      22,
        "size_h2":      15,
        "size_h3":      11.5,
        "size_body":    10.5,
        "size_caption": 8.5,
        "size_meta":    8,

        # Layout (pt, 1cm ≈ 28.35pt)
        "margin_left":   79,   # 2.8cm
        "margin_right":  79,
        "margin_top":    79,
        "margin_bottom": 71,   # 2.5cm
        "section_gap":   26,
        "para_gap":      8,
        "line_gap":      17,
    }
    return tokens


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generate design tokens from document metadata")
    parser.add_argument("--title",  default="Untitled Document")
    parser.add_argument("--type",   default="general",
                        choices=list(PALETTES.keys()),
                        help="Document type: " + ", ".join(PALETTES.keys()))
    parser.add_argument("--author", default="")
    parser.add_argument("--date",   default="")
    parser.add_argument("--meta",     help="JSON file with title/type/author/date keys")
    parser.add_argument("--accent",   default="",
                        help="Override accent colour (hex, e.g. #2D6A8F). "
                             "accent_lt is auto-derived by lightening toward white.")
    parser.add_argument("--cover-bg", default="",
                        help="Override cover background colour (hex).")
    parser.add_argument("--out",    default="tokens.json")
    args = parser.parse_args()

    if args.meta:
        try:
            with open(args.meta) as f:
                meta = json.load(f)
            args.title  = meta.get("title",  args.title)
            args.type   = meta.get("type",   args.type)
            args.author = meta.get("author", args.author)
            args.date   = meta.get("date",   args.date)
        except Exception as e:
            print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
            sys.exit(1)

    tokens = build_tokens(
        args.title, args.type, args.author, args.date,
        accent_override=args.accent,
        cover_bg_override=getattr(args, "cover_bg", ""),
    )

    try:
        with open(args.out, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        sys.exit(3)

    print(json.dumps({
        "status":  "ok",
        "out":     args.out,
        "mood":    tokens["mood"],
        "pattern": tokens["cover_pattern"],
        "fonts":   f'{tokens["font_display"]} / {tokens["font_body"]}',
    }))


if __name__ == "__main__":
    main()
