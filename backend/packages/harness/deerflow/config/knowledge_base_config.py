from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr


class KnowledgeBaseConfig(BaseModel):
    """Hot-reloadable RAGFlow retrieval and knowledge-management settings."""

    model_config = ConfigDict(validate_default=True)

    enabled: bool = Field(default=False)
    base_url: AnyHttpUrl = Field(default="http://localhost:9380")
    api_key: SecretStr | None = Field(default=None)
    timeout: float = Field(default=30, gt=0, le=600)

    page_size: int = Field(default=8, ge=1, le=100)
    similarity_threshold: float = Field(default=0.2, ge=0, le=1)
    vector_similarity_weight: float = Field(default=0.3, ge=0, le=1)
    top_k: int = Field(default=256, ge=1, le=1024)
    max_chars_per_chunk: int = Field(default=800, ge=1, le=100_000)
    max_total_chars: int = Field(default=8000, ge=1, le=1_000_000)

    watch_interval_seconds: int = Field(default=3, ge=1, le=300)
    idle_interval_seconds: int = Field(default=15, ge=1, le=3600)
