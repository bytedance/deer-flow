# Memory System Improvements

This document tracks memory injection behavior and roadmap status.

## Status (As Of 2026-03-10)

Implemented in `main`:
- Accurate token counting via `tiktoken` in `format_memory_for_injection`.
- Facts are injected into prompt memory context.
- Facts are ranked by confidence (descending).
- Injection respects `max_injection_tokens` budget.

Planned / not yet merged:
- TF-IDF similarity-based fact retrieval.
- `current_context` input for context-aware scoring.
- Configurable similarity/confidence weights (`similarity_weight`, `confidence_weight`).
- Middleware/runtime wiring for context-aware retrieval before each model call.

## Current Behavior

Function today:

```python
def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
```

Current injection format:
- `User Context` section from `user.*.summary`
- `History` section from `history.*.summary`
- `Facts` section from `facts[]`, sorted by confidence, appended until token budget is reached

Token counting:
- Uses `tiktoken` (`cl100k_base`) when available
- Falls back to `len(text) // 4` if tokenizer import fails

## Known Gap

Previous versions of this document described TF-IDF/context-aware retrieval as if it were already shipped.
That was not accurate for `main` and caused confusion.

Issue reference: `#1059`

## Roadmap (Planned)

Planned scoring strategy:

```text
final_score = (similarity * 0.6) + (confidence * 0.4)
```

Planned integration shape:
1. Extract recent conversational context from filtered user/final-assistant turns.
2. Compute TF-IDF cosine similarity between each fact and current context.
3. Rank by weighted score and inject under token budget.
4. Fall back to confidence-only ranking if context is unavailable.

## Validation

Current regression coverage includes:
- facts inclusion in memory injection output
- confidence ordering
- token-budget-limited fact inclusion

Tests:
- `backend/tests/test_memory_prompt_injection.py`
