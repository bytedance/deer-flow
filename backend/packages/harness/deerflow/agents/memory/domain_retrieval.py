"""Domain memory retrieval for prompt injection.

Loads domain-scoped facts via semantic search and formats them for system prompts.
Applies decay policies and token budgeting.
"""

import logging
import time

from deerflow.agents.memory.domain_storage import DecayPolicy, DomainFact, apply_decay
from deerflow.agents.memory.prompt import _count_tokens
from deerflow.config.domain_memory_config import get_domain_memory_config
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)

_DEFAULT_DOMAIN_MEMORY_TOKENS = 1000


def _format_domain_facts(facts: list[DomainFact], max_tokens: int) -> str:
    """Format domain facts for prompt injection.

    Args:
        facts: List of DomainFact objects (assumed sorted by adjusted_score).
        max_tokens: Maximum tokens to use.

    Returns:
        Formatted domain context string, or empty string if no facts.
    """
    if not facts:
        return ""

    fact_lines: list[str] = []
    for fact in facts:
        if not fact.content or not fact.content.strip():
            continue
        domain = fact.domain or "general"
        entity = fact.entity_id or "unknown"
        score = fact.adjusted_score
        fact_lines.append(f"- [{domain}/{entity} | {score:.2f}] {fact.content.strip()}")

    if not fact_lines:
        return ""

    result = "\n".join(fact_lines)

    token_count = _count_tokens(result)
    if token_count > max_tokens:
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)
        result = result[:target_chars] + "\n..."

    return result


def get_domain_context(
    query: str,
    domain: str | None = None,
    entity_id: str | None = None,
    max_tokens: int | None = None,
    tenant_id: str | None = None,
) -> str:
    """Retrieve and format domain memory for prompt injection.

    Performs semantic search for domain facts, applies decay policy,
    filters by min_score, and formats for system prompt injection.

    Args:
        query: Search query text.
        domain: Optional domain filter (e.g., "equipment", "process").
        entity_id: Optional entity filter.
        max_tokens: Maximum tokens to use. Defaults to config value.
        tenant_id: Optional tenant ID. Defaults to current tenant.

    Returns:
        Formatted domain context string with "Domain context:" header,
        or empty string if no relevant facts found.
    """
    config = get_domain_memory_config()
    if not config.enabled or not config.injection_enabled:
        return ""

    if max_tokens is None:
        max_tokens = config.max_injection_tokens

    if tenant_id is None:
        tenant_id = get_current_tenant_id()

    from deerflow.agents.memory.domain_storage import get_domain_storage

    storage = get_domain_storage()
    if storage is None:
        return ""

    start = time.monotonic()
    facts = storage.search_facts(
        tenant_id=tenant_id,
        query=query,
        domain=domain,
        entity_id=entity_id,
        top_k=20,
        min_score=config.min_retrieval_score,
    )
    latency_ms = (time.monotonic() - start) * 1000

    if not facts:
        logger.debug(
            "Domain memory retrieved: tenant=%s query=%s facts=0 latency=%.1fms",
            tenant_id,
            query[:50],
            latency_ms,
        )
        return ""

    decay_config = config.get_domain_decay(domain or "default")
    policy = DecayPolicy(decay_config.policy)
    facts = apply_decay(facts, policy, decay_config.half_life_days)

    top_score = facts[0].adjusted_score if facts else 0.0
    logger.info(
        "Domain memory retrieved: tenant=%s query=%s facts=%d top_score=%.3f latency=%.1fms",
        tenant_id,
        query[:50],
        len(facts),
        top_score,
        latency_ms,
    )

    formatted = _format_domain_facts(facts, max_tokens)
    if not formatted.strip():
        return ""

    return f"Domain context:\n{formatted}"
