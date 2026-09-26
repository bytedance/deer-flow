"""The one error taxonomy every TypeSafe (Jev) consumer maps its failures from.

Two layers, deliberately separate (design §2.3):

* **Request level** — a transport error, a spent deadline, a non-200 status, or a
  response without a usable common envelope. These raise :class:`TypeSafeError`
  with one of the four causes below.
* **Question level** — an answer that is missing, has the wrong ``type``, carries
  a non-finite or out-of-range probability, or names an unknown ``choice`` label.
  These never raise: they come back as data in
  ``deerflow.typesafe.client.AnswerSet.errors_by_question`` so one bad question
  cannot discard the other valid answers in the same response.

``cause`` is the machine-readable category. What a cause *means* for execution is
the consumer's decision and stays there: the tool gate denies, the memory paths
fall back to their normal behaviour.
"""

from __future__ import annotations

#: The request never reached a usable response: DNS, connect, read, protocol.
CAUSE_TRANSPORT = "transport"
#: The endpoint answered, but not with ``200``.
CAUSE_HTTP_STATUS = "http_status"
#: The endpoint answered ``200`` with a body that is not a usable envelope.
CAUSE_INVALID_RESPONSE = "invalid_response"
#: The evaluation budget was spent before a usable result could be accepted.
CAUSE_DEADLINE = "deadline"

CAUSES = frozenset({CAUSE_TRANSPORT, CAUSE_HTTP_STATUS, CAUSE_INVALID_RESPONSE, CAUSE_DEADLINE})


class TypeSafeError(RuntimeError):
    """A TypeSafe request could not produce a usable answer set.

    Raised for request-level failures only. Consumers translate it into their own
    failure policy — the tool gate turns it into a fail-closed denial, the memory
    paths extract as usual — and never treat it as a verdict.

    The message never contains the credential, the request state, or any part of
    the response body: a malformed or hostile endpoint can echo the state back,
    and these messages reach middleware logs, the run journal and the evaluation
    report.
    """

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


__all__ = [
    "CAUSE_DEADLINE",
    "CAUSE_HTTP_STATUS",
    "CAUSE_INVALID_RESPONSE",
    "CAUSE_TRANSPORT",
    "CAUSES",
    "TypeSafeError",
]
