"""OpenAI-compatible answer provider configured only through named environment variables.

Credentials and the endpoint are resolved from the environment variable names
recorded in the versioned config; they are never read from files, logged, or
persisted. Error messages name the missing variables, never their values.
Responses are reduced to the prediction text and non-secret metadata — response
headers and complete payloads are never returned to callers.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass

import httpx

from .config import QAConfig

RETRY_BACKOFF_SECONDS = 2.0


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSettings:
    base_url: str
    api_key: str


@dataclass(frozen=True)
class AnswerCall:
    prediction: str
    attempts: int
    request_fingerprint: str
    response_model: str | None
    usage: dict[str, int]


def resolve_provider_settings(qa: QAConfig) -> ProviderSettings:
    base_url = os.environ.get(qa.base_url_env, "").strip()
    api_key = os.environ.get(qa.api_key_env, "").strip()
    missing = [name for name, value in ((qa.base_url_env, base_url), (qa.api_key_env, api_key)) if not value]
    if missing:
        raise ProviderConfigurationError(f"missing provider environment variables: {', '.join(missing)}")
    return ProviderSettings(base_url=base_url, api_key=api_key)


def build_client(settings: ProviderSettings, qa: QAConfig) -> httpx.Client:
    return httpx.Client(base_url=settings.base_url, headers={"Authorization": f"Bearer {settings.api_key}"}, timeout=qa.timeout_seconds)


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def request_payload(qa: QAConfig, messages: tuple[dict[str, str], ...]) -> dict[str, object]:
    return {"model": qa.model, "temperature": qa.temperature, "max_tokens": qa.max_tokens, "stream": qa.stream, "messages": list(messages)}


def request_fingerprint(qa: QAConfig, messages: tuple[dict[str, str], ...]) -> str:
    return hashlib.sha256(json.dumps(request_payload(qa, messages), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def request_answer(client: httpx.Client, qa: QAConfig, messages: tuple[dict[str, str], ...], *, backoff_seconds: float = RETRY_BACKOFF_SECONDS) -> AnswerCall:
    payload = request_payload(qa, messages)
    fingerprint = request_fingerprint(qa, messages)
    last_error = "no attempt was made"
    for attempt in range(1, qa.max_attempts + 1):
        if attempt > 1 and backoff_seconds > 0:
            time.sleep(backoff_seconds)
        try:
            response = client.post("/chat/completions", json=payload)
        except httpx.HTTPError as error:
            last_error = f"network error: {type(error).__name__}"
            continue
        if _is_retryable_status(response.status_code):
            last_error = f"retryable status {response.status_code}"
            continue
        if response.status_code != 200:
            raise ProviderCallError(f"provider returned non-retryable status {response.status_code}")
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            prediction = message["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderCallError("provider response is missing choices[0].message.content") from error
        if not isinstance(prediction, str):
            raise ProviderCallError("provider prediction is not a string")
        raw_usage = body.get("usage")
        usage = {key: value for key, value in raw_usage.items() if isinstance(value, int)} if isinstance(raw_usage, dict) else {}
        response_model = body.get("model") if isinstance(body.get("model"), str) else None
        return AnswerCall(prediction=prediction, attempts=attempt, request_fingerprint=fingerprint, response_model=response_model, usage=usage)
    raise ProviderCallError(f"provider call failed after {qa.max_attempts} attempts: {last_error}")
