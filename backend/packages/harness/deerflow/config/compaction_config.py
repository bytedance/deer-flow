"""Configuration for Headroom-based context compaction.

Context compaction compresses the message history sent to the LLM — primarily
large tool outputs, logs, and search results — *just before* each model call,
using the optional `Headroom <https://github.com/chopratejas/headroom>`_
library (``pip install headroom-ai``).

Unlike :class:`~deerflow.config.summarization_config.SummarizationConfig`, which
*rewrites persisted state* by replacing old turns with an LLM-generated summary,
compaction is **non-destructive**: it only shrinks the copy of the messages
handed to the model for a single call. The full, original history stays in the
checkpointer untouched, so compaction is fully reversible and never loses tool
provenance. The two features are complementary and may both be enabled.

Headroom is an optional dependency. When it is not installed the middleware is a
transparent pass-through (logged once at startup), so enabling this config on a
host without ``headroom-ai`` is safe and simply does nothing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompactionConfig(BaseModel):
    """Config section for Headroom context compaction.

    Compaction runs inside the model-call boundary (``wrap_model_call``) and only
    rewrites the request copy of the messages — it never mutates checkpointed
    state. Content is compressed in place; the message count and tool-call
    structure are always preserved (if Headroom ever returns a different shape,
    the middleware falls back to passing the originals through unchanged).
    """

    enabled: bool = Field(
        default=False,
        description="Enable Headroom context compaction. Requires the optional 'headroom-ai' package; when it is missing the middleware is a no-op.",
    )
    model: str | None = Field(
        default=None,
        description="Model name Headroom uses for token counting / context sizing. None = resolve from the active model at call time, falling back to a sensible default.",
    )
    model_limit: int = Field(
        default=200_000,
        gt=0,
        description="Context window (tokens) Headroom assumes for the target model.",
    )
    min_total_tokens: int = Field(
        default=4_000,
        ge=0,
        description="Only run compaction once the estimated message-history token count exceeds this. Keeps short conversations untouched (and cache-friendly).",
    )
    min_tokens_to_compress: int = Field(
        default=250,
        ge=0,
        description="Per-message floor: messages estimated below this many tokens are never compressed.",
    )
    protect_recent: int = Field(
        default=4,
        ge=0,
        description="Number of most-recent messages left uncompressed (the active conversation). 0 compresses everything.",
    )
    compress_user_messages: bool = Field(
        default=False,
        description="Also compress user/human messages. Default False — for agent workloads user turns are usually small and worth preserving verbatim.",
    )
    compress_system_messages: bool = Field(
        default=False,
        description="Compress system messages embedded in the history. Default False to keep instructions/tool definitions byte-exact.",
    )
    target_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Keep-ratio hint for Headroom's text compressor (e.g. 0.5 keeps ~50%). None lets Headroom decide (most aggressive).",
    )
    savings_profile: str | None = Field(
        default=None,
        description="Named Headroom savings profile to apply (e.g. 'agent-90'). None uses the default pipeline.",
    )
    fail_open: bool = Field(
        default=True,
        description="If True, any error during compaction is swallowed and the original messages are sent unchanged. Set False to surface compaction errors.",
    )
