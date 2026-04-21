"""Shared text sanitization helpers.

Provides reusable sanitizers for two concerns:

1. ``strip_symbols_and_invisibles`` — removes emoji/pictograph blocks, icon-font
   private-use-area characters, BiDi/invisible control characters, variation
   selectors, and related Unicode ranges. Used both by the SearXNG web-search
   tool (to defang injection payloads hidden in third-party content) and by the
   Gemma 4 prompt pipeline (to strip decorative emojis that would otherwise
   cost tokens and bias deliverables toward emoji-heavy UI output).

2. ``strip_gemma_channel_blocks`` — removes Gemma 4 internal reasoning markers
   (``<|channel>thought\\n...<channel|>``) that must be dropped from historical
   model turns per Google's Gemma 4 prompt-formatting documentation.
"""

from __future__ import annotations

import re

# Unicode ranges covering emoji, pictographs, icon-font private-use characters,
# and invisible/BiDi control characters that can be abused for prompt injection
# or bloat deliverables.
_UNSAFE_CHAR_RE = re.compile(
    "["
    # Invisible & BiDi control
    "\u00ad"  # soft hyphen
    "\u061c"  # Arabic letter mark
    "\u180e"  # Mongolian vowel separator
    "\u200b-\u200f"  # ZWSP/ZWNJ/ZWJ/LRM/RLM
    "\u202a-\u202e"  # LRE/RLE/PDF/LRO/RLO (BiDi override)
    "\u2060-\u206f"  # WJ, invisible times/separator, etc.
    "\ufe00-\ufe0f"  # variation selectors
    "\ufeff"  # BOM / zero-width no-break space
    "\ufff9-\ufffb"  # interlinear annotation
    "\U000e0000-\U000e007f"  # tag characters (invisible)
    "\U000e0100-\U000e01ef"  # variation selectors supplement
    # Symbol & pictograph blocks (emoji families)
    "\u2300-\u23ff"  # misc technical
    "\u2460-\u24ff"  # enclosed alphanumerics
    "\u2500-\u257f"  # box drawing
    "\u2580-\u259f"  # block elements
    "\u25a0-\u25ff"  # geometric shapes
    "\u2600-\u26ff"  # misc symbols
    "\u2700-\u27bf"  # dingbats
    "\u2b00-\u2bff"  # misc symbols and arrows
    "\u2934-\u2935"  # curved arrows commonly used as icons
    "\U0001f000-\U0001ffff"  # SMP symbol/emoji planes
    # Private use areas — used by Nerdfonts / FontAwesome / material icons
    "\ue000-\uf8ff"  # BMP PUA
    "\U000f0000-\U000ffffd"  # SPUA-A
    "\U00100000-\U0010fffd"  # SPUA-B
    "]"
)

# Matches Gemma 4 reasoning blocks emitted between `<|channel>` and `<channel|>`.
# Accepts both the tokenizer-literal form and variants that sometimes leak with
# extra pipe characters (`<|channel|>foo<|channel|>` etc.).
_GEMMA_CHANNEL_RE = re.compile(
    r"<\|?channel\|?>[\s\S]*?<\|?channel\|?>",
    flags=re.IGNORECASE,
)


def strip_symbols_and_invisibles(text: str) -> str:
    """Remove emojis, pictographs, icon-font PUA characters, and invisible controls.

    Preserves ordinary ASCII, CJK text, punctuation, and whitespace structure.
    Whitespace is intentionally left untouched so Markdown/code blocks and
    indentation stay intact; callers that need whitespace normalization should
    handle it after this pass.
    """
    if not text:
        return ""
    return _UNSAFE_CHAR_RE.sub("", text)


def strip_gemma_channel_blocks(text: str) -> str:
    """Remove Gemma 4 ``<|channel>...<channel|>`` reasoning blocks.

    Non-destructive for any input that does not contain channel markers, which
    makes it safe to apply unconditionally when Gemma 4 is the active model
    (other Gemma-family outputs simply pass through).
    """
    if not text:
        return ""
    return _GEMMA_CHANNEL_RE.sub("", text)


__all__ = [
    "strip_symbols_and_invisibles",
    "strip_gemma_channel_blocks",
]
