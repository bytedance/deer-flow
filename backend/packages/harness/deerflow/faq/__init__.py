"""FAQ module — decoupled FAQ retrieval service with structured I/O."""

from deerflow.faq.service import FaqService
from deerflow.faq.types import FaqItem, FaqQuery, FaqResult

__all__ = ["FaqQuery", "FaqResult", "FaqItem", "FaqService"]
