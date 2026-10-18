"""Host-owned, bounded evidence from the actual assembly, before graph execution."""

import hashlib
import hmac
import json
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict

from deerflow_extension_api import AgentAssemblyDescriptor

EVIDENCE_KEY = "deerflow_assembly_evidence"
_capture = ContextVar("capture_run_assembly", default=False)
_key = secrets.token_bytes(32)


def capture_requested():
    return _capture.get()


@contextmanager
def capture_assembly():
    token = _capture.set(True)
    try:
        yield
    finally:
        _capture.reset(token)


def _digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    return hmac.new(_key, raw, hashlib.sha256).hexdigest()


def project_assembly_evidence(descriptor, *, thread_id, run_id):
    if not isinstance(descriptor, AgentAssemblyDescriptor):
        return None
    # Do not expose arbitrary provider kwargs, middleware parameters, prompts,
    # URLs, headers or credentials. Keyed versions cover them without raw data.
    parameters = {
        key: value
        for key, value in descriptor.model_parameters.items()
        if key in {"temperature", "top_p", "top_k", "max_tokens", "max_completion_tokens", "seed", "frequency_penalty", "presence_penalty"} and type(value) in (bool, int, float)
    }
    proof = {
        "schema_version": 1,
        "source": "host_assembly",
        "thread_id": thread_id,
        "run_id": run_id,
        "agent": descriptor.agent_name,
        "model": descriptor.effective_model,
        "parameters": parameters,
        "model_version": _digest([descriptor.model_parameters, descriptor.thinking_enabled, descriptor.reasoning_effort]),
        "instructions_version": _digest(descriptor.base_prompt_hash),
        "tools_version": _digest([asdict(t) for t in descriptor.tools] + [list(descriptor.deferred_tool_names)]),
        "skills_version": _digest([list(descriptor.enabled_skills), descriptor.effective_policies.get("skill_catalog_hash")]),
        "policy_version": _digest([asdict(m) for m in descriptor.middlewares] + [descriptor.effective_policies]),
    }
    proof["version"] = _digest({k: v for k, v in proof.items() if k not in ("thread_id", "run_id")})
    if len(json.dumps(proof).encode()) > 8000:
        raise ValueError("Assembly evidence limit")
    return proof
