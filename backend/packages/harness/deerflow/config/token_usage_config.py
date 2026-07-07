from pydantic import BaseModel, Field


class TokenUsageConfig(BaseModel):
    """Configuration for token usage tracking."""

    enabled: bool = Field(default=True, description="Enable token usage tracking middleware")

    counting: str = Field(
        default="approximate",
        description=(
            "Token-counting strategy for the context-usage breakdown. "
            '"approximate" (default) uses the network-free chars//4 heuristic — fast and '
            "dependency-free. "
            '"exact" uses the model tokenizer (tiktoken, cl100k_base); the encoding is loaded '
            "lazily and cached, but the first call may download BPE data from a public endpoint. "
            "Falls back to a CJK-aware char estimate if tiktoken is unavailable. "
            "Only affects the context-usage indicator rows, not provider billing."
        ),
    )

    def is_exact_counting(self) -> bool:
        """True when the breakdown should use the model tokenizer instead of the heuristic."""
        return (self.counting or "").strip().lower() == "exact"
