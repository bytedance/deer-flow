"""OpenAI Decisions transport for the host-side decision consumers.

Sibling of ``deerflow.typesafe`` for issue #7005: the same three consumer slots, the same
policy ownership, a different endpoint dialect.

* ``guardrails/openai_decisions.py`` — the pre-execution tool risk gate.
* ``agents/memory/prescreen/openai_decisions.py`` — the memory capture pre-screen.
* ``agents/memory/signals/openai_decisions.py`` — signal classification.

Shared here: the endpoint, the request envelope, question encoding, answer validation, and the
provider's own defaults. Transport lifecycle, authentication, retry, the deadline budget and
the bounded body read are inherited from ``deerflow.typesafe.client.TypeSafeClient`` rather than
restated, so one owner holds those rules for both backends.

The split of what stays in each adapter is `deerflow.typesafe`'s, unchanged: state content,
questions, criteria, thresholds, failure policy, cache semantics and business audit.
"""

from deerflow.openai_decisions.client import (
    ANSWER_TYPE_REFUSAL,
    CATEGORY_REFUSAL,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    ENDPOINT_PATH,
    QUESTION_CHOICE,
    QUESTION_PREDICATE,
    OpenAIDecisionsClient,
    encode_question,
    predicate_instructions,
    provider_defaults,
)

__all__ = [
    "ANSWER_TYPE_REFUSAL",
    "CATEGORY_REFUSAL",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_BASE_URL",
    "ENDPOINT_PATH",
    "OpenAIDecisionsClient",
    "QUESTION_CHOICE",
    "QUESTION_PREDICATE",
    "encode_question",
    "predicate_instructions",
    "provider_defaults",
]
