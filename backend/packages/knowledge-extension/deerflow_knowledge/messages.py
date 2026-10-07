"""One copy strategy for configuration-class refusals (spec 2026-09-30 D2, ② 已裁＝乙).

Every such message carries both languages, joined by `` / ``: the frontend renders ``detail``
verbatim, so a bilingual line serves both locales without an i18n layer. Kept import-free on
purpose — the provider allowlist is deliberately import-light and uses it too.
"""

from __future__ import annotations


def bilingual(cn: str, en: str) -> str:
    """Chinese first, English after `` / `` — the one shape every refusal follows."""
    return f"{cn} / {en}"
