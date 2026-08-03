"""Formatting helpers for upload summaries shown to the model."""

from collections import Counter
from collections.abc import Iterable

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags


def format_extension_counts(extensions: Iterable[str]) -> str:
    """Return a stable, neutralized summary of extension counts."""
    counts = Counter(extensions)
    parts = [f"{count} {extension}" for extension, count in sorted(counts.items())]
    return neutralize_untrusted_tags(", ".join(parts))
