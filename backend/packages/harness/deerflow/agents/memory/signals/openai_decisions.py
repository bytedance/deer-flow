"""OpenAI Decisions signal classifier: the same two additive hints over ``/v1/decisions``.

Like its pre-screen sibling, this subclass changes the endpoint and nothing else. The two
directions, their rubrics, ``hint_threshold``, the label mapping, the per-question cache buckets
and the rule that a model hint can never write a confirmation all stay in the base class — the
reinforcement evidence gate keeps reading the deterministic set only.

Configuration::

    memory:
      backend_config:
        signal_classification:
          mode: shadow
          use: deerflow.agents.memory.signals.openai_decisions:OpenAIDecisionsSignalClassifier
          config:
            api_key_env: OPENAI_API_KEY
            model: <the decision model this deployment names>
"""

from __future__ import annotations

from deerflow.agents.memory.signals.contract import CONFIGURATION_SOURCE
from deerflow.agents.memory.signals.typesafe import TypeSafeSignalClassifier
from deerflow.openai_decisions.client import OpenAIDecisionsClient, resolve_decisions_connection
from deerflow.typesafe.client import TransportFactory, TypeSafeClient
from deerflow.typesafe.connection import TypeSafeConnection


class OpenAIDecisionsSignalClassifier(TypeSafeSignalClassifier):
    """Map Decisions ``predicate`` probabilities for affirmation / negation onto hint labels."""

    name = "openai_decisions"
    policy_id = "deerflow.memory.signals.openai_decisions"
    policy_version = "1.0.0"

    def _resolve_connection(self, settings: dict[str, object]) -> TypeSafeConnection:
        return resolve_decisions_connection(settings=settings, configuration_source=CONFIGURATION_SOURCE)

    def _build_client(self, connection: TypeSafeConnection, *, transport_factory: TransportFactory | None) -> TypeSafeClient:
        return OpenAIDecisionsClient(connection, transport_factory=transport_factory)

    def _judge_state(self, batch_text: str) -> str:
        """The batch text itself: this endpoint's ``input`` is text, not a state object."""
        return batch_text


__all__ = ["OpenAIDecisionsSignalClassifier"]
