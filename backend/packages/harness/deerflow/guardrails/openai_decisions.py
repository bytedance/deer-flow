"""OpenAI Decisions guardrail provider: the same pre-execution risk gate, another endpoint.

Issue #7005 asked for a second decision backend behind the interfaces the Jev integration
already uses. Everything that makes this a *gate* is inherited from
:class:`~deerflow.guardrails.typesafe.TypeSafeGuardrailProvider` and deliberately not restated:
the strict-JSON local preflight, the character-count boundary, the threshold direction, the
cache, and fail-closed. Two copies of a security boundary drift apart, and the copy the primary
suite does not exercise is the one that goes quiet.

What differs is the wire, and only the wire:

* ``input`` is text, so the judged bytes are the canonical JSON the state digest already
  identifies — the same bytes, not a second serialisation of them.
* a ``noul`` question becomes a ``predicate`` question, whose rubric rides in ``instructions``
  (see ``deerflow.openai_decisions.client``).
* a refusal is an answer, not an HTTP failure; the inherited ``_recorded_answer`` already treats
  "no validated answer for my one question" as ``TypeSafeGuardrailError`` with cause
  ``invalid_response``, so the gate denies on exactly the path it denies on today.

Configuration is the existing slot — no new schema::

    guardrails:
      provider:
        use: deerflow.guardrails.openai_decisions:OpenAIDecisionsGuardrailProvider
        config:
          api_key_env: OPENAI_API_KEY
          model: <the decision model this deployment names>
"""

from __future__ import annotations

from deerflow.guardrails.typesafe import TypeSafeGuardrailError, TypeSafeGuardrailProvider, _Probe
from deerflow.openai_decisions.client import OpenAIDecisionsClient, resolve_decisions_connection
from deerflow.typesafe.client import TransportFactory, TypeSafeClient
from deerflow.typesafe.connection import TypeSafeConnection


class OpenAIDecisionsGuardrailError(TypeSafeGuardrailError):
    """A Decisions evaluation could not produce a usable verdict.

    Same family, same handling by ``guardrails.fail_closed``, different name so a log line and a
    denial reason never attribute a decision to the wrong service.
    """


class OpenAIDecisionsGuardrailProvider(TypeSafeGuardrailProvider):
    """Deny tool calls whose Decisions ``predicate`` probability reaches ``threshold``.

    Reads the same ``guardrails.provider.config`` block and the same optional fields as the Jev
    provider; only ``base_url``/``model``/``api_key_env`` default differently, because they name a
    different service.
    """

    name = "openai_decisions"
    policy_id = "deerflow.guardrails.openai_decisions"
    policy_version = "1.0.0"
    code_prefix = "openai_decisions"
    provider_name = "OpenAI Decisions"
    error_class = OpenAIDecisionsGuardrailError

    def _resolve_connection(self, settings: dict[str, object]) -> TypeSafeConnection:
        return resolve_decisions_connection(settings=settings, configuration_source=self.configuration_source)

    def _build_client(self, connection: TypeSafeConnection, *, transport_factory: TransportFactory | None) -> TypeSafeClient:
        return OpenAIDecisionsClient(connection, transport_factory=transport_factory)

    def _state(self, probe: _Probe) -> str:
        return probe.state_text


__all__ = ["OpenAIDecisionsGuardrailError", "OpenAIDecisionsGuardrailProvider"]
