"""TypeSafe (Jev) guardrail provider: pre-execution risk gate for tool calls.

One ``noul`` question (``risky_tool_call``) asks whether a tool call is likely to
cause an irreversible or out-of-scope side effect. Calls at or above
``threshold`` are denied before execution, so the agent sees the reason and can
choose another approach.

Three properties are load-bearing and easy to lose in a refactor:

* **``state`` is built with strict JSON** — no ``default=``, ``allow_nan=False``,
  string keys only. Arguments that cannot be serialised, and argument text above
  ``max_state_chars``, are denied *locally*: nothing is truncated and sent, and
  no verdict is ever based on a prefix.
* **Timeouts are budgets, not guarantees.** The async path cancels in-flight
  requests through ``asyncio.timeout``. The sync path cannot preempt a blocking
  call, so it checks the deadline after the response headers arrive, around the
  body read, and before the decision is accepted — and drops results that
  arrived late instead of returning them.
* **Clients live for exactly one evaluation.** The framework has no provider
  lifecycle hook, and httpx closes an injected transport when its client closes,
  so a shared transport instance would be dead on the second evaluation.
  ``transport_factory`` is therefore a factory, called once per network-needing
  evaluation and closed together with the client it was handed to.

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
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason, GuardrailRequest

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_API_KEY_ENV = "TYPESAFE_API_KEY"

_ENDPOINT_PATH = "/v1/systemone"
_QUESTION_ID = "risky_tool_call"
_OK_STATUS = 200
_UNAUTHORIZED_STATUS = 401
_RETRYABLE_STATUS_CODES = frozenset({429, 529})
_DIGEST_CHARS = 16

# The served ``model`` is the one response value that reaches the reason message
# verbatim, and from there the denied ToolMessage, the run journal, middleware
# logs and the evaluation report. Only a token of this shape is recorded as
# itself; anything else is recorded as a digest. See ``_recordable_model``.
_MODEL_TOKEN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}\Z")

_DEFAULT_INSTRUCTIONS = "Does executing this tool call risk an irreversible or out-of-scope side effect? Judge the call from its text alone."
_DEFAULT_CRITERIA_TRUE = (
    "Any of: deletes or overwrites data; changes permissions or access control; publishes, pushes, or sends anything outside the task; "
    "spends money or places an order; reads or writes credentials or secrets; executes content that the call text does not show "
    "(bash ./script.sh, curl ... | sh, base64 or compressed payloads, python -c on decoded input); the arguments are too thin to tell "
    "how far the effect reaches. These take precedence over the false criteria."
)
_DEFAULT_CRITERIA_FALSE = "Read-only or retrieval-only; or a change that the call text shows to be local and reversible."

TransportFactory = Callable[[], "httpx.BaseTransport | httpx.AsyncBaseTransport"]


class TypeSafeGuardrailError(RuntimeError):
    """A TypeSafe evaluation could not produce a usable verdict.

    ``cause`` is a short machine-readable category: ``deadline``, ``transport``,
    ``http_status`` or ``invalid_response``. The middleware maps this exception
    to ``guardrails.fail_closed``; it is never downgraded to an allow here.
    """

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


class _RetryableAttempt(TypeSafeGuardrailError):
    """Internal: this attempt failed in a way another attempt may fix."""


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
    than on the first tool call.
    """

    name = "typesafe"
    policy_id = "deerflow.guardrails.typesafe"
    policy_version = "1.1.0"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "jev-latest",
        threshold: float = 0.5,
        instructions: str | None = None,
        criteria: dict[object, object] | None = None,
        tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        timeout: float = 5.0,
        deadline_seconds: float = 10.0,
        max_attempts: int = 2,
        retry_backoff: float = 0.5,
        max_state_chars: int = 4000,
        cache_size: int = 256,
        cache_ttl_seconds: float = 300.0,
        transport_factory: TransportFactory | None = None,
    ) -> None:
        resolved_key = api_key if api_key is not None else os.environ.get(api_key_env)
        if not resolved_key:
            raise ValueError(f"TypeSafe requires an API key: pass 'api_key' in guardrails.provider.config or set the {api_key_env} environment variable")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string; TypeSafe returns the version it actually served")

        self._api_key = resolved_key
        self._url = f"{base_url.rstrip('/')}{_ENDPOINT_PATH}"
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._threshold = _finite_float("threshold", threshold, minimum=0.0, maximum=1.0)
        self._instructions = _defaulted_text("instructions", instructions, _DEFAULT_INSTRUCTIONS)
        self._criteria_true = _defaulted_text("criteria.true", _criteria_entry(criteria, True), _DEFAULT_CRITERIA_TRUE)
        self._criteria_false = _defaulted_text("criteria.false", _criteria_entry(criteria, False), _DEFAULT_CRITERIA_FALSE)
        self._tools = _tool_names("tools", tools)
        self._allowed_tools = _tool_names("allowed_tools", allowed_tools)
        self._timeout = _finite_float("timeout", timeout, minimum=0.0, exclusive=True)
        self._deadline_seconds = _finite_float("deadline_seconds", deadline_seconds, minimum=0.0, exclusive=True)
        self._max_attempts = _whole_number("max_attempts", max_attempts, minimum=1)
        self._retry_backoff = _finite_float("retry_backoff", retry_backoff, minimum=0.0)
        self._max_state_chars = _whole_number("max_state_chars", max_state_chars, minimum=1)
        self._cache_size = _whole_number("cache_size", cache_size, minimum=0)
        self._cache_ttl_seconds = _finite_float("cache_ttl_seconds", cache_ttl_seconds, minimum=0.0)
        self._transport_factory = transport_factory
        self._cache: OrderedDict[tuple[str, str], _CacheEntry] = OrderedDict()

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare behaviour-affecting parameters for assembly identity (never the key)."""
        from deerflow_extension_api import canonical_hash

        return {
            "model": self._model,
            "base_url": self._base_url,
            "threshold": self._threshold,
            "instructions_hash": canonical_hash(self._instructions),
            "criteria": {"true": self._criteria_true, "false": self._criteria_false},
            "tools": None if self._tools is None else sorted(self._tools),
            "allowed_tools": None if self._allowed_tools is None else sorted(self._allowed_tools),
            "timeout": self._timeout,
            "deadline_seconds": self._deadline_seconds,
            "max_attempts": self._max_attempts,
            "retry_backoff": self._retry_backoff,
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
        deadline_at = time.monotonic() + self._deadline_seconds
        answer = self._post_sync(self._build_payload(prepared), deadline_at)
        self._check_budget(deadline_at)
        return self._decide_from_answer(prepared, answer)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        prepared = self._prepare(request)
        if isinstance(prepared, GuardrailDecision):
            return prepared
        cached = self._cache_get(prepared)
        if cached is not None:
            return self._cached_decision(cached)
        deadline_at = time.monotonic() + self._deadline_seconds
        answer = await self._post_async(self._build_payload(prepared), deadline_at)
        self._check_budget(deadline_at)
        return self._decide_from_answer(prepared, answer)

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

    def _build_payload(self, probe: _Probe) -> dict[str, object]:
        return {
            "state": {"tool_call": {"name": probe.tool_name, "arguments": probe.arguments_text}},
            "model": self._model,
            "questions": {
                _QUESTION_ID: {
                    "type": "noul",
                    "instructions": self._instructions,
                    "criteria": {"true": self._criteria_true, "false": self._criteria_false},
                }
            },
        }

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
        # ``model`` is already bounded by _recordable_model: it is response
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

    # --- transport --------------------------------------------------------

    def _post_sync(self, payload: dict[str, object], deadline_at: float) -> _Answer:
        transport = None if self._transport_factory is None else self._transport_factory()
        with httpx.Client(timeout=self._timeout, transport=transport) as client:
            for attempt in range(1, self._max_attempts + 1):
                self._check_budget(deadline_at)
                try:
                    return self._attempt_sync(client, payload, deadline_at)
                except _RetryableAttempt as exc:
                    if attempt >= self._max_attempts:
                        raise TypeSafeGuardrailError(str(exc), cause=exc.cause) from exc
                    self._sleep_before_retry(attempt, deadline_at)

    async def _post_async(self, payload: dict[str, object], deadline_at: float) -> _Answer:
        # The cancellation scope covers the in-flight request and its body read:
        # it bounds the request duration, not the wall-clock cost of cleanup.
        try:
            async with asyncio.timeout(self._deadline_seconds):
                transport = None if self._transport_factory is None else self._transport_factory()
                async with httpx.AsyncClient(timeout=self._timeout, transport=transport) as client:
                    for attempt in range(1, self._max_attempts + 1):
                        self._check_budget(deadline_at)
                        try:
                            return await self._attempt_async(client, payload, deadline_at)
                        except _RetryableAttempt as exc:
                            if attempt >= self._max_attempts:
                                raise TypeSafeGuardrailError(str(exc), cause=exc.cause) from exc
                            await self._async_sleep_before_retry(attempt, deadline_at)
        except TimeoutError as exc:
            # asyncio.timeout converts only the cancellation it triggered; an
            # outer CancelledError stays a CancelledError and keeps propagating.
            raise self._deadline_error() from exc

    def _attempt_sync(self, client: httpx.Client, payload: dict[str, object], deadline_at: float) -> _Answer:
        try:
            with client.stream("POST", self._url, json=payload, headers=self._headers()) as response:
                self._check_budget(deadline_at)
                if response.status_code != _OK_STATUS:
                    raise self._status_error(response.status_code)
                self._check_budget(deadline_at)
                body = response.read()
                self._check_budget(deadline_at)
                return self._parse_answer(body)
        except httpx.TransportError as exc:
            raise _RetryableAttempt(f"TypeSafe request failed: {type(exc).__name__}", cause="transport") from exc
        except httpx.HTTPError as exc:
            raise TypeSafeGuardrailError(f"TypeSafe request failed: {type(exc).__name__}", cause="transport") from exc

    async def _attempt_async(self, client: httpx.AsyncClient, payload: dict[str, object], deadline_at: float) -> _Answer:
        try:
            async with client.stream("POST", self._url, json=payload, headers=self._headers()) as response:
                self._check_budget(deadline_at)
                if response.status_code != _OK_STATUS:
                    raise self._status_error(response.status_code)
                self._check_budget(deadline_at)
                body = await response.aread()
                self._check_budget(deadline_at)
                return self._parse_answer(body)
        except httpx.TransportError as exc:
            raise _RetryableAttempt(f"TypeSafe request failed: {type(exc).__name__}", cause="transport") from exc
        except httpx.HTTPError as exc:
            raise TypeSafeGuardrailError(f"TypeSafe request failed: {type(exc).__name__}", cause="transport") from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}

    def _status_error(self, status_code: int) -> TypeSafeGuardrailError:
        # Only the numeric status is reported. The response body *and* the HTTP
        # status line are both server-controlled, TypeSafe may echo the state
        # (raw tool arguments) in either, and this message reaches middleware
        # logs and the evaluation report.
        hint = " (check the API key configured via api_key / the API key environment variable)" if status_code == _UNAUTHORIZED_STATUS else ""
        message = f"TypeSafe returned HTTP {status_code}{hint}"
        if status_code in _RETRYABLE_STATUS_CODES:
            return _RetryableAttempt(message, cause="http_status")
        return TypeSafeGuardrailError(message, cause="http_status")

    def _parse_answer(self, body: bytes) -> _Answer:
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise TypeSafeGuardrailError("TypeSafe response was not valid JSON", cause="invalid_response") from exc
        if not isinstance(payload, dict):
            raise TypeSafeGuardrailError("TypeSafe response must be a JSON object", cause="invalid_response")
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            raise TypeSafeGuardrailError("TypeSafe response is missing a non-empty 'model'", cause="invalid_response")
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise TypeSafeGuardrailError("TypeSafe response is missing an 'answers' object", cause="invalid_response")
        answer = answers.get(_QUESTION_ID)
        if not isinstance(answer, dict):
            raise TypeSafeGuardrailError(f"TypeSafe response has no answer for question {_QUESTION_ID!r}", cause="invalid_response")
        if answer.get("type") != "noul":
            raise TypeSafeGuardrailError(f"TypeSafe answer for {_QUESTION_ID!r} is not a noul answer (type={type(answer.get('type')).__name__})", cause="invalid_response")
        raw_probability = answer.get("noul")
        # bool is an int subclass, and json.loads parses NaN/Infinity literals, so
        # both are rejected here rather than reaching the threshold comparison.
        # Only the offending type is reported: a malformed response may echo tool
        # arguments here, and this message reaches middleware logs and the
        # evaluation report, which is exactly what the HTTP error path avoids.
        if isinstance(raw_probability, bool) or not isinstance(raw_probability, (int, float)):
            raise TypeSafeGuardrailError(f"TypeSafe returned a non-numeric noul probability (type={type(raw_probability).__name__})", cause="invalid_response")
        probability = float(raw_probability)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise TypeSafeGuardrailError("TypeSafe returned a noul probability outside [0, 1]", cause="invalid_response")
        return _Answer(probability=probability, model=_recordable_model(model))

    # --- deadline budget --------------------------------------------------

    def _check_budget(self, deadline_at: float) -> None:
        """Reject a result when the evaluation budget is spent, even on success."""
        if time.monotonic() >= deadline_at:
            raise self._deadline_error()

    def _deadline_error(self) -> TypeSafeGuardrailError:
        return TypeSafeGuardrailError(f"TypeSafe evaluation exceeded deadline_seconds={self._deadline_seconds:g}", cause="deadline")

    def _remaining(self, deadline_at: float) -> float:
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            raise self._deadline_error()
        return remaining

    def _sleep_before_retry(self, attempt: int, deadline_at: float) -> None:
        time.sleep(min(self._retry_backoff * 2 ** (attempt - 1), self._remaining(deadline_at)))

    async def _async_sleep_before_retry(self, attempt: int, deadline_at: float) -> None:
        await asyncio.sleep(min(self._retry_backoff * 2 ** (attempt - 1), self._remaining(deadline_at)))

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


def _recordable_model(model: str) -> str:
    """Return the served model token, or a digest when it is not safe to record.

    ``model`` is response content: it lands in the denial ``ToolMessage``, the run
    journal, middleware logs and the evaluation report. A malformed or hostile
    endpoint can put an echoed tool argument, injected instructions or a
    multi-megabyte string there, so only a token matching ``_MODEL_TOKEN`` is
    recorded verbatim. Anything else keeps a stable, bounded provenance record
    instead of being echoed, without discarding a verdict that is otherwise
    usable: rejecting the response would turn a cosmetic server quirk into a
    fail-closed denial of every call the endpoint answers.
    """
    if _MODEL_TOKEN.match(model):
        return model
    # surrogatepass: json.loads produces lone surrogates for escaped input, and a
    # plain UTF-8 encode would raise on them where this must not fail.
    digest = hashlib.sha256(model.encode("utf-8", "surrogatepass")).hexdigest()[:_DIGEST_CHARS]
    return f"unrecorded:sha256:{digest}"


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


def _finite_float(name: str, value: object, *, minimum: float | None = None, maximum: float | None = None, exclusive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if minimum is not None and (number <= minimum if exclusive else number < minimum):
        raise ValueError(f"{name} must be {'>' if exclusive else '>='} {minimum:g}, got {number!r}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be <= {maximum:g}, got {number!r}")
    return number


def _whole_number(name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value!r}")
    return value


def _defaulted_text(name: str, value: object, fallback: str) -> str:
    if value is None:
        return fallback
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _criteria_entry(criteria: dict[object, object] | None, flag: bool) -> object:
    """Look up a ``criteria`` entry under either the YAML or the JSON spelling.

    A YAML ``criteria: {true: ..., false: ...}`` block parses its keys as booleans,
    while a JSON-typed config keeps them as the strings ``"true"``/``"false"``.
    """
    if criteria is None:
        return None
    if not isinstance(criteria, dict):
        raise ValueError("criteria must be a mapping with optional 'true'/'false' entries")
    for key in (flag, "true" if flag else "false"):
        if key in criteria:
            return criteria[key]
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
