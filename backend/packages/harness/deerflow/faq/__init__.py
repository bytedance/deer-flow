"""FAQ module — decoupled FAQ retrieval service with structured I/O."""

from deerflow.faq.service import FaqService
from deerflow.faq.types import FaqItem, FaqMatchLevel, FaqQuery, FaqResult, FaqRouteDecision

__all__ = ["FaqQuery", "FaqResult", "FaqItem", "FaqMatchLevel", "FaqRouteDecision", "FaqService"]
