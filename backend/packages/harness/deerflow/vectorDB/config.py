from typing import Literal

from pydantic import BaseModel, Field


class ChromaConfig(BaseModel):
    path: str = "vector_db/chroma"
    collection_name: str = "deerflow_knowledge"


class VectorStoreConfig(BaseModel):
    backend: Literal["none", "chroma"] = "none"

    embedding_model: str | None = None

    chroma: ChromaConfig = Field(default_factory=ChromaConfig)
