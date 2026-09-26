"""Shared TypeSafe (Jev) client for every host-side consumer.

One transport layer, several adapters:

* ``guardrails/typesafe.py`` — the pre-execution tool risk gate.
* ``agents/memory/prescreen/`` — the memory capture pre-screen (planned).
* ``agents/memory/signals/`` — signal classification and its coordinator (planned).

**Shared** (this package): client lifecycle and ``transport_factory`` injection,
authentication, retry and backoff, the deadline budget, response parsing and the
error taxonomy, UTF-8 wire-size counting, and the request skeleton.

**Not shared — it stays in each adapter, on purpose:**

* **State content**: tool-call arguments for the gate, the conversation tail for
  the memory consumers. The client never inspects what it sends.
* **Questions, criteria, thresholds and decision direction**: ``risky_tool_call``
  denies at or above its threshold, ``memory_worth_keeping`` skips below its own —
  opposite directions over the same transport.
* **Failure policy**: the gate fails closed (error ⇒ deny); the memory paths fail
  softly (error ⇒ carry on with their normal behaviour).
* **Cache semantics**: the gate's provider owns its cache, the memory layer's
  coordinator owns the combined-request cache. Different keys, different owners,
  so no cached verdict is ever shared between consumers by accident.
* **Business audit**: what a decision records (the gate's run-journal reason, the
  memory pre-screen's record) and how it relates to the journal or metrics.

A change that would move one of those into this package is a change to the design,
not a refactor (see ``docs/superpowers/specs/2026-09-25-shared-jev-typesafe-client-design.en.md``
§2.2). Caching, pooling and per-consumer policy parameters must stay out.
"""

from deerflow.typesafe.client import (
    CATEGORY_LABEL,
    CATEGORY_MISSING,
    CATEGORY_PROBABILITY,
    CATEGORY_TYPE,
    QUESTION_CHOICE,
    QUESTION_NOUL,
    Answer,
    AnswerSet,
    ChoiceAnswer,
    NoulAnswer,
    Question,
    QuestionError,
    TransportFactory,
    TypeSafeClient,
    recordable_model,
    wire_size,
)
from deerflow.typesafe.connection import (
    CONNECTION_FIELDS,
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_DEADLINE_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MODEL,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_TIMEOUT,
    ENDPOINT_PATH,
    MODE_OFF,
    TypeSafeConnection,
    resolve_connection,
    resolve_connection_for_mode,
    typesafe_defaults,
)
from deerflow.typesafe.errors import (
    CAUSE_DEADLINE,
    CAUSE_HTTP_STATUS,
    CAUSE_INVALID_RESPONSE,
    CAUSE_TRANSPORT,
    CAUSES,
    TypeSafeError,
)
from deerflow.typesafe.validation import criteria_entry, defaulted_text, finite_float, whole_number

__all__ = [
    "CAUSE_DEADLINE",
    "CAUSE_HTTP_STATUS",
    "CAUSE_INVALID_RESPONSE",
    "CAUSE_TRANSPORT",
    "CAUSES",
    "CATEGORY_LABEL",
    "CATEGORY_MISSING",
    "CATEGORY_PROBABILITY",
    "CATEGORY_TYPE",
    "CONNECTION_FIELDS",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_BASE_URL",
    "DEFAULT_DEADLINE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MODEL",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_TIMEOUT",
    "ENDPOINT_PATH",
    "MODE_OFF",
    "QUESTION_CHOICE",
    "QUESTION_NOUL",
    "Answer",
    "AnswerSet",
    "ChoiceAnswer",
    "NoulAnswer",
    "Question",
    "QuestionError",
    "TransportFactory",
    "TypeSafeClient",
    "TypeSafeConnection",
    "recordable_model",
    "TypeSafeError",
    "criteria_entry",
    "defaulted_text",
    "finite_float",
    "resolve_connection",
    "resolve_connection_for_mode",
    "typesafe_defaults",
    "whole_number",
    "wire_size",
]
