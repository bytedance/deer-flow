"""TypeSafe (Jev) guardrail provider: pre-execution risk gate for tool calls.

One ``noul`` question (``risky_tool_call``) asks whether a tool call is likely to
cause an irreversible or out-of-scope side effect. Calls at or above
``threshold`` are denied before execution, so the agent sees the reason and can
choose another approach.

Transport, authentication, retry, the deadline budget, response parsing and the
error taxonomy live in ``deerflow.typesafe`` and are shared with the memory
consumers. What stays here is everything that makes this gate a gate: the state
(tool name plus canonical argument JSON), the question and its criteria, the
threshold and its direction, the local preflight that refuses to send anything
unusable, the cache, and the failure policy — an error denies.

Three properties are load-bearing and easy to lose in a refactor:

* **``state`` is built with strict JSON** — no ``default=``, ``allow_nan=False``,
  string keys only. Arguments that cannot be serialised, and argument text above
  ``max_state_chars``, are denied *locally*: nothing is truncated and sent, and
  no verdict is ever based on a prefix. ``max_state_chars`` stays a **character**
  count of the canonical argument JSON; the shared client's ``wire_size`` reports
  bytes but replaces no limit here.
* **Timeouts are budgets, not guarantees.** The shared client's async path
  cancels in-flight requests through ``asyncio.timeout``; its sync path cannot
  preempt a blocking call, so it checks the deadline after the response headers,
  around the body read and after parsing, and drops a result that arrived late.
* **Clients live for exactly one evaluation** — ``transport_factory`` is a
  factory, not an instance, and the client closes it with itself.

A configured ``allowed_tools`` list is a hard permission list, not an exemption
from evaluation: a tool outside it is refused locally and never probed, while a
listed tool still has to clear the risk gate. ``None`` means "no list configured"
and ``[]`` means "no tool may run" — a truthiness test would collapse the second
into the first and fail open.

This provider does not extend the audit path: denials reach the run journal
through ``GuardrailMiddleware`` as usual, allow decisions remain unpersisted, and
the recorded reason message carries the fields needed to replay the threshold
comparison (probability, threshold, model version, state digest). The served
``model`` is response content, so it is recorded verbatim only when it fits a
conservative token shape; anything else is recorded as a digest rather than
echoed into the message.

Connection settings resolve with the documented precedence — this provider's own
config, then the top-level ``typesafe:`` block, then the built-in defaults — so
an existing ``guardrails.provider.config`` keeps working unchanged while a
deployment with several TypeSafe consumers can share one block.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest
from deerflow.typesafe.client import QUESTION_NOUL, AnswerSet, Question, TransportFactory, TypeSafeClient, recordable_model
from deerflow.typesafe.connection import DEFAULT_API_KEY_ENV, DEFAULT_BASE_URL, TypeSafeConnection, resolve_connection, typesafe_defaults
from deerflow.typesafe.errors import CAUSE_INVALID_RESPONSE, TypeSafeError
from deerflow.typesafe.validation import criteria_entry, defaulted_text, finite_float, whole_number

_QUESTION_ID = "risky_tool_call"
_DIGEST_CHARS = 16

_DEFAULT_INSTRUCTIONS = "Does executing this tool call risk an irreversible or out-of-scope side effect? Judge the call from its text alone."
_DEFAULT_CRITERIA_TRUE = (
    "Any of: deletes or overwrites data; changes permissions or access control; publishes, pushes, or sends anything outside the task; "
    "spends money or places an order; reads or writes credentials or secrets; executes content that the call text does not show "
    "(bash ./script.sh, curl ... | sh, base64 or compressed payloads, python -c on decoded input); the arguments are too thin to tell "
    "how far the effect reaches. These take precedence over the false criteria."
)
_DEFAULT_CRITERIA_FALSE = "Read-only or retrieval-only; or a change that the call text shows to be local and reversible."

_CONFIGURATION_SOURCE = "guardrails.provider.config"


class TypeSafeGuardrailError(TypeSafeError):
    """A TypeSafe evaluation could not produce a usable verdict.

    The shared request-level categories (``deadline``, ``transport``,
    ``http_status``, ``invalid_response``) pass through unchanged, and a
    question-level failure for this provider's own question is reported with
    ``invalid_response`` too: the envelope was usable, this answer was not, and
    the gate has no verdict. The middleware maps this exception to
    ``guardrails.fail_closed``; it is never downgraded to an allow here.
    """


@dataclass(frozen=True)
class _Answer:
    probability: float
    model: str


@dataclass(frozen=True)
class _Probe:
    """A locally validated call that is worth sending to TypeSafe."""

    tool_name: str
    arguments_text: str
    state_digest: str


@dataclass(frozen=True)
class _CacheEntry:
    allow: bool
    probability: float
    model: str
    state_digest: str
    expires_at: float


class TypeSafeGuardrailProvider:
    """Deny tool calls whose Jev risk probability reaches ``threshold``.

    A configured ``allowed_tools`` list decides which tools may run at all: tools
    outside it are refused locally, without a state, a request or a cache entry.

    Configuration lives in ``guardrails.provider.config``; constructor arguments
    are validated eagerly so a bad deployment fails at agent build time rather
    than on the first tool call. The connection fields this provider does not set
    come from the top-level ``typesafe:`` block, and from the built-in defaults
    when that block is absent.
    """

    name = "typesafe"
    policy_id = "deerflow.guardrails.typesafe"
    policy_version = "1.1.0"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        threshold: float = 0.5,
        instructions: str | None = None,
        criteria: dict[object, object] | None = None,
        tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        timeout: float | None = None,
        deadline_seconds: float | None = None,
        max_attempts: int | None = None,
        retry_backoff: float | None = None,
        max_state_chars: int = 4000,
        cache_size: int = 256,
        cache_ttl_seconds: float = 300.0,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        connection: TypeSafeConnection = resolve_connection(
            settings={
                "api_key": api_key,
                "api_key_env": api_key_env,
                "base_url": base_url,
                "model": model,
                "timeout": timeout,
                "deadline_seconds": deadline_seconds,
                "max_attempts": max_attempts,
                "retry_backoff": retry_backoff,
            },
            defaults=typesafe_defaults(),
            configuration_source=_CONFIGURATION_SOURCE,
        )
        self._connection = connection
        self._client = TypeSafeClient(connection, transport_factory=transport_factory)
        self._threshold = finite_float("threshold", threshold, minimum=0.0, maximum=1.0)
        self._instructions = defaulted_text("instructions", instructions, _DEFAULT_INSTRUCTIONS)
        self._criteria_true = defaulted_text("criteria.true", criteria_entry(criteria, True), _DEFAULT_CRITERIA_TRUE)
        self._criteria_false = defaulted_text("criteria.false", criteria_entry(criteria, False), _DEFAULT_CRITERIA_FALSE)
        self._tools = _tool_names("tools", tools)
        self._allowed_tools = _tool_names("allowed_tools", allowed_tools)
        self._max_state_chars = whole_number("max_state_chars", max_state_chars, minimum=1)
        self._cache_size = whole_number("cache_size", cache_size, minimum=0)
        self._cache_ttl_seconds = finite_float("cache_ttl_seconds", cache_ttl_seconds, minimum=0.0)
        self._question = Question(
            type=QUESTION_NOUL,
            instructions=self._instructions,
            criteria={"true": self._criteria_true, "false": self._criteria_false},
        )
        self._questions: dict[str, Question] = {_QUESTION_ID: self._question}
        self._cache: OrderedDict[tuple[str, str], _CacheEntry] = OrderedDict()

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare behaviour-affecting parameters for assembly identity (never the key).

        This is the public, per-consumer policy identity. It carries the
        connection's public parameters plus everything that changes a verdict —
        and never the credential: the fingerprint that decides whether two
        consumers may share a request belongs to ``TypeSafeClient.sharing_key``,
        which consumers compare internally.
        """
        from deerflow_extension_api import canonical_hash

        return {
            **self._connection.public_parameters(),
            "threshold": self._threshold,
            "instructions_hash": canonical_hash(self._instructions),
            "criteria": {"true": self._criteria_true, "false": self._criteria_false},
            "tools": None if self._tools is None else sorted(self._tools),
            "allowed_tools": None if self._allowed_tools is None else sorted(self._allowed_tools),
            "max_state_chars": self._max_state_chars,
            "cache_size": self._cache_size,
            "cache_ttl_seconds": self._cache_ttl_seconds,
        }

    # --- decision paths ---------------------------------------------------

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        prepared = self._prepare(request)
        if isinstance(prepared, GuardrailDecision):
            return prepared
        cached = self._cache_get(prepared)
        if cached is not None:
            return self._cached_decision(cached)
        return self._decide_from_answer(prepared, self._ask_sync(prepared))

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        prepared = self._prepare(request)
        if isinstance(prepared, GuardrailDecision):
            return prepared
        cached = self._cache_get(prepared)
        if cached is not None:
            return self._cached_decision(cached)
        return self._decide_from_answer(prepared, await self._ask_async(prepared))

    def _ask_sync(self, probe: _Probe) -> _Answer:
        try:
            answer_set = self._client.ask(self._state(probe), self._questions)
        except TypeSafeError as exc:
            raise TypeSafeGuardrailError(str(exc), cause=exc.cause) from exc
        return self._recorded_answer(answer_set)

    async def _ask_async(self, probe: _Probe) -> _Answer:
        try:
            answer_set = await self._client.aask(self._state(probe), self._questions)
        except TypeSafeError as exc:
            raise TypeSafeGuardrailError(str(exc), cause=exc.cause) from exc
        return self._recorded_answer(answer_set)

    def _recorded_answer(self, answer_set: AnswerSet) -> _Answer:
        """This provider's one answer, with the served model reduced to a recordable token.

        The shared parser returns a question-level failure as data so that a
        memory consumer can fall back per question. This provider asked exactly
        one question, so that failure means the evaluation has no verdict — the
        same outcome it had when the parser raised for it, with the same cause.
        """
        answer = answer_set.noul(_QUESTION_ID)
        if answer is None:
            error = answer_set.errors_by_question.get(_QUESTION_ID)
            message = error.message if error is not None else f"TypeSafe response has no answer for question {_QUESTION_ID!r}"
            raise TypeSafeGuardrailError(message, cause=CAUSE_INVALID_RESPONSE)
        return _Answer(probability=answer.probability, model=recordable_model(answer_set.model))

    def _state(self, probe: _Probe) -> dict[str, object]:
        return {"tool_call": {"name": probe.tool_name, "arguments": probe.arguments_text}}

    # --- preflight (local, no network) ------------------------------------

    def _prepare(self, request: GuardrailRequest) -> _Probe | GuardrailDecision:
        """Build the state to send, or return a decision that needs no network.

        Order is load-bearing: ``allowed_tools`` is a permission list, so it is
        checked before the probe scope -- a tool it refuses stays refused even
        when ``tools`` would have skipped probing it, and must not inherit an
        allow from being out of probe scope.
        """
        tool_name = str(request.tool_name)
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            return GuardrailDecision(
                allow=False,
                reasons=[GuardrailReason(code="typesafe.tool_not_allowed", message=f"typesafe.tool_not_allowed: tool={tool_name!r} not in configured allowed_tools policy={self._policy_ref()}")],
                policy_id=self.policy_id,
                metadata={"tool_not_allowed": True},
            )
        if self._tools is not None and tool_name not in self._tools:
            return GuardrailDecision(
                allow=True,
                reasons=[GuardrailReason(code="typesafe.tool_not_probed", message=f"typesafe.tool_not_probed: tool={tool_name!r} not in configured tools policy={self._policy_ref()}")],
                policy_id=self.policy_id,
                metadata={"tool_not_probed": True},
            )
        tool_input = request.tool_input
        failure = "TypeError" if not isinstance(tool_input, dict) else _strict_json_failure(tool_input)
        if failure is not None:
            return self._state_unusable("unserializable", reason=failure, digest="unavailable")
        try:
            arguments_text = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            state_text = json.dumps({"tool_call": {"name": tool_name, "arguments": arguments_text}}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            # The UTF-8 encode belongs inside this guard: a lone surrogate is a str
            # that json.dumps emits verbatim, so it passes both dumps calls and only
            # fails when the digest is encoded. Letting UnicodeEncodeError escape
            # would turn a local validation failure into a provider *error*, which
            # fail_closed=false converts into running the tool unevaluated.
            state_digest = hashlib.sha256(state_text.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
        except (TypeError, ValueError) as exc:  # UnicodeEncodeError arrives here through ValueError
            return self._state_unusable("unserializable", reason=type(exc).__name__, digest="unavailable")
        # Character count of the canonical argument JSON, not its wire size: one
        # CJK character is three UTF-8 bytes, so a byte limit here would move the
        # boundary this fallback has always drawn (the shared client counts bytes
        # when a consumer asks it to; it changes no limit).
        if len(arguments_text) > self._max_state_chars:
            return self._state_unusable("too_large", limit=self._max_state_chars, length=len(arguments_text), digest=state_digest)
        return _Probe(tool_name=tool_name, arguments_text=arguments_text, state_digest=state_digest)

    def _state_unusable(self, cause: str, **fields: object) -> GuardrailDecision:
        """Deny a call TypeSafe must not see: nothing truncated, nothing lossy is sent."""
        detail = " ".join(f"{key}={value}" for key, value in fields.items())
        return GuardrailDecision(
            allow=False,
            reasons=[GuardrailReason(code="typesafe.state_unusable", message=f"typesafe.state_unusable: cause={cause} {detail} policy={self._policy_ref()}")],
            policy_id=self.policy_id,
            metadata={"state_unusable_cause": cause, **fields},
        )

    def _decide_from_answer(self, probe: _Probe, answer: _Answer) -> GuardrailDecision:
        allow = answer.probability < self._threshold
        self._cache_put(probe, allow=allow, answer=answer)
        return self._model_decision(allow=allow, probability=answer.probability, model=answer.model, state_digest=probe.state_digest, cached=False)

    def _cached_decision(self, entry: _CacheEntry) -> GuardrailDecision:
        return self._model_decision(allow=entry.allow, probability=entry.probability, model=entry.model, state_digest=entry.state_digest, cached=True)

    def _model_decision(self, *, allow: bool, probability: float, model: str, state_digest: str, cached: bool) -> GuardrailDecision:
        code = "typesafe.allowed" if allow else "typesafe.tool_call_risky"
        # repr(): the recorded probability and threshold must replay to the same
        # verdict, so neither is rounded for display. repr() round-trips exactly.
        # ``model`` is already bounded by recordable_model: it is response
        # content, so a value outside the recordable shape arrives as a digest and
        # never as the echoed text this message would otherwise carry into the
        # ToolMessage, the run journal, the logs and the report.
        message = f"{code}: p={probability!r} {'<' if allow else '>='} t={self._threshold!r} model={model} cached={str(cached).lower()} digest={state_digest} policy={self._policy_ref()}"
        return GuardrailDecision(
            allow=allow,
            reasons=[GuardrailReason(code=code, message=message)],
            policy_id=self.policy_id,
            metadata={"probability": probability, "threshold": self._threshold, "model": model, "cached": cached, "state_digest": state_digest},
        )

    def _policy_ref(self) -> str:
        return f"{self.policy_id}@{self.policy_version}"

    # --- cache ------------------------------------------------------------

    def _cache_get(self, probe: _Probe) -> _CacheEntry | None:
        if self._cache_size <= 0 or self._cache_ttl_seconds <= 0:
            return None
        key = (probe.tool_name, probe.arguments_text)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            # pop(): sync evaluation can run on executor threads when a turn
            # produces parallel tool calls, so another thread may already have
            # removed this same expired entry. A bare ``del`` would raise
            # KeyError, which the middleware reports as a provider error and,
            # under fail_closed, turns into a spurious denial.
            self._cache.pop(key, None)
            return None
        return entry

    def _cache_put(self, probe: _Probe, *, allow: bool, answer: _Answer) -> None:
        if self._cache_size <= 0 or self._cache_ttl_seconds <= 0:
            return
        self._cache[(probe.tool_name, probe.arguments_text)] = _CacheEntry(
            allow=allow,
            probability=answer.probability,
            model=answer.model,
            state_digest=probe.state_digest,
            expires_at=time.monotonic() + self._cache_ttl_seconds,
        )
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _strict_json_failure(value: object) -> str | None:
    """Return the exception name ``json.dumps`` would raise on ``value``, else None.

    ``json.dumps`` silently stringifies non-string keys — ``{1: "a"}`` becomes
    ``{"1": "a"}``, colliding with a genuinely different call — while its default
    settings emit the non-JSON ``NaN`` literal. The key check therefore has to
    happen here; the remaining checks mirror the strict dump's rejections so the
    deny message can name the failure class.
    """
    stack: list[tuple[bool, object]] = [(False, value)]
    active: set[int] = set()
    while stack:
        leaving, item = stack.pop()
        if leaving:
            active.discard(id(item))
            continue
        if item is None or isinstance(item, (str, bool, int)):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                return "ValueError"
            continue
        if isinstance(item, (dict, list)):
            if id(item) in active:
                return "ValueError"
            active.add(id(item))
            stack.append((True, item))
            if isinstance(item, dict):
                for key, nested in item.items():
                    if not isinstance(key, str):
                        return "TypeError"
                    stack.append((False, nested))
            else:
                stack.extend((False, nested) for nested in item)
            continue
        return "TypeError"
    return None


def _tool_names(name: str, value: object) -> frozenset[str] | None:
    """``None`` means "not configured"; an empty list is a configured empty set.

    A truthiness test would collapse ``[]`` into ``None`` and silently fail open:
    no ``allowed_tools`` configured lets every tool through the gate, while an
    empty list must refuse every call.
    """
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(tool, str) or not tool for tool in value):
        raise ValueError(f"{name} must be a list of non-empty tool names, or omitted")
    return frozenset(value)


__all__ = ["DEFAULT_API_KEY_ENV", "DEFAULT_BASE_URL", "TypeSafeGuardrailError", "TypeSafeGuardrailProvider"]
