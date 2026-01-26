# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation data models for structured source metadata.
"""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


class CitationMetadata(BaseModel):
    """Metadata extracted from a source."""

    # Core identifiers
    url: str
    title: str

    # Content information
    description: Optional[str] = None
    content_snippet: Optional[str] = None
    raw_content: Optional[str] = None

    # Source metadata
    domain: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[str] = None
    language: Optional[str] = None

    # Media
    images: List[str] = Field(default_factory=list)
    favicon: Optional[str] = None

    # Quality indicators
    relevance_score: float = 0.0
    credibility_score: float = 0.0

    # Timestamps
    accessed_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Additional metadata
    extra: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, **data):
        """Initialize and extract domain from URL if not provided."""
        super().__init__(**data)
        if not self.domain and self.url:
            try:
                parsed = urlparse(self.url)
                self.domain = parsed.netloc
            except Exception:
                # If URL parsing fails for any reason, leave `domain` as None.
                # This is a non-critical convenience field and failures here
                # should not prevent citation metadata creation.
                pass

    @property
    def id(self) -> str:
        """Generate a unique ID for this citation based on URL."""
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "description": self.description,
            "content_snippet": self.content_snippet,
            "domain": self.domain,
            "author": self.author,
            "published_date": self.published_date,
            "language": self.language,
            "images": self.images,
            "favicon": self.favicon,
            "relevance_score": self.relevance_score,
            "credibility_score": self.credibility_score,
            "accessed_at": self.accessed_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CitationMetadata":
        """Create from dictionary."""
        # Remove 'id' as it's computed from url
        data = {k: v for k, v in data.items() if k != "id"}
        return cls.model_validate(data)

    @classmethod
    def from_search_result(
        cls, result: Dict[str, Any], query: str = ""
    ) -> "CitationMetadata":
        """Create citation metadata from a search result."""
        return cls(
            url=result.get("url", ""),
            title=result.get("title", "Untitled"),
            description=result.get("content", result.get("description", "")),
            content_snippet=result.get("content", "")[:500]
            if result.get("content")
            else None,
            raw_content=result.get("raw_content"),
            relevance_score=result.get("score", 0.0),
            extra={"query": query, "result_type": result.get("type", "page")},
        )



class Citation(BaseModel):
    """
    A citation reference that can be used in reports.

    This represents a numbered citation that links to source metadata.
    """

    # Citation number (1-indexed for display)
    number: int

    # Reference to the source metadata
    metadata: CitationMetadata

    # Context where this citation is used
    context: Optional[str] = None

    # Specific quote or fact being cited
    cited_text: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def id(self) -> str:
        """Get the citation ID from metadata."""
        return self.metadata.id

    @property
    def url(self) -> str:
        """Get the URL from metadata."""
        return self.metadata.url

    @property
    def title(self) -> str:
        """Get the title from metadata."""
        return self.metadata.title

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "number": self.number,
            "metadata": self.metadata.to_dict(),
            "context": self.context,
            "cited_text": self.cited_text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Citation":
        """Create from dictionary."""
        return cls.model_validate({
            "number": data["number"],
            "metadata": CitationMetadata.from_dict(data["metadata"])
            if isinstance(data.get("metadata"), dict)
            else data["metadata"],
            "context": data.get("context"),
            "cited_text": data.get("cited_text"),
        })

    def to_markdown_reference(self) -> str:
        """Generate markdown reference format: [Title](URL)"""
        return f"[{self.title}]({self.url})"

    def to_numbered_reference(self) -> str:
        """Generate numbered reference format: [1] Title - URL"""
        return f"[{self.number}] {self.title} - {self.url}"

    def to_inline_marker(self) -> str:
        """Generate inline citation marker: [^1]"""
        return f"[^{self.number}]"

    def to_footnote(self) -> str:
        """Generate footnote definition: [^1]: Title - URL"""
        return f"[^{self.number}]: {self.title} - {self.url}"
