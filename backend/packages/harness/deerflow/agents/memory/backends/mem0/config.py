"""mem0 backend config -- parses and validates ``backend_config``.

Follows the noop-template pattern: a plain dataclass + ``from_backend_config``.
The host injects ``storage_path`` (and optionally ``should_keep_hidden_message``)
into every backend's config dict; those keys are accepted and ignored. Any
OTHER unknown key is rejected -- a typo in persistent-state config must fail
fast, not silently fall back to defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

#: Keys the host factory injects into backend_config; accepted and ignored.
_HOST_INJECTED_KEYS = frozenset({"storage_path", "should_keep_hidden_message"})

_STARTUP_POLICIES = frozenset({"fail_fast", "tolerate"})
_READ_POLICIES = frozenset({"fail_open", "fail_closed"})
_WRITE_POLICIES = frozenset({"log_and_drop", "raise"})


@dataclass(frozen=True)
class Mem0Config:
    """Validated knobs for the mem0 HTTP backend."""

    #: Name of the environment variable holding the mem0 API key. The key
    #: itself never appears in config.yaml.
    api_key_env: str = "MEM0_API_KEY"
    #: mem0 Platform API root; point at a self-hosted server for on-prem.
    base_url: str = "https://api.mem0.ai"
    #: Max memories injected by get_context / default search breadth (1-1000).
    top_k: int = 8
    #: Minimum relevance score for search() results (mem0 `threshold`, 0-1).
    score_threshold: float = 0.1
    #: Hard cap on the injection text returned by get_context.
    max_injection_chars: int = 12000
    #: Per-request HTTP timeout in seconds.
    timeout_seconds: float = 10.0
    #: "fail_fast" = auth-check in from_config; "tolerate" = defer to first use.
    startup_policy: str = "fail_fast"
    #: "fail_open" = recall errors inject nothing and continue;
    #: "fail_closed" = recall errors raise MemoryManagerError.
    read_policy: str = "fail_open"
    #: "log_and_drop" = write errors are logged and dropped (at-most-once);
    #: "raise" = write errors raise MemoryManagerError.
    write_policy: str = "log_and_drop"

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> Mem0Config:
        cfg = dict(backend_config or {})
        failure_policy = cfg.pop("failure_policy", {}) or {}
        unknown = (
            set(cfg)
            - {
                "api_key_env",
                "base_url",
                "top_k",
                "score_threshold",
                "max_injection_chars",
                "timeout_seconds",
                "startup_policy",
            }
            - _HOST_INJECTED_KEYS
        )
        if unknown:
            raise ValueError(f"mem0 backend_config has unknown keys: {sorted(unknown)}")
        if not isinstance(failure_policy, dict):
            raise ValueError("mem0 failure_policy must be a mapping {read, write}")
        unknown_fp = set(failure_policy) - {"read", "write"}
        if unknown_fp:
            raise ValueError(f"mem0 failure_policy has unknown keys: {sorted(unknown_fp)}")

        config = cls(
            api_key_env=str(cfg.get("api_key_env", "MEM0_API_KEY")),
            base_url=str(cfg.get("base_url", "https://api.mem0.ai")).rstrip("/"),
            top_k=int(cfg.get("top_k", 8)),
            score_threshold=float(cfg.get("score_threshold", 0.1)),
            max_injection_chars=int(cfg.get("max_injection_chars", 12000)),
            timeout_seconds=float(cfg.get("timeout_seconds", 10.0)),
            startup_policy=str(cfg.get("startup_policy", "fail_fast")),
            read_policy=str(failure_policy.get("read", "fail_open")),
            write_policy=str(failure_policy.get("write", "log_and_drop")),
        )
        if config.startup_policy not in _STARTUP_POLICIES:
            raise ValueError(f"mem0 startup_policy must be one of {sorted(_STARTUP_POLICIES)}")
        if config.read_policy not in _READ_POLICIES:
            raise ValueError(f"mem0 failure_policy.read must be one of {sorted(_READ_POLICIES)}")
        if config.write_policy not in _WRITE_POLICIES:
            raise ValueError(f"mem0 failure_policy.write must be one of {sorted(_WRITE_POLICIES)}")
        if not 1 <= config.top_k <= 1000:
            raise ValueError("mem0 top_k must be in [1, 1000]")
        if not 0.0 <= config.score_threshold <= 1.0:
            raise ValueError("mem0 score_threshold must be in [0, 1]")
        if config.max_injection_chars <= 0:
            raise ValueError("mem0 max_injection_chars must be positive")
        if config.timeout_seconds <= 0:
            raise ValueError("mem0 timeout_seconds must be positive")
        if not config.api_key_env.strip():
            raise ValueError("mem0 api_key_env must be a non-empty env var name")
        return config

    def resolve_api_key(self) -> str:
        """Read the API key from the configured environment variable."""
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise ValueError(f"mem0 API key missing: environment variable {self.api_key_env} is unset or empty")
        return key
