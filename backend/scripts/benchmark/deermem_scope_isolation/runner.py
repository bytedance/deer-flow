from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig, DeerMemModelConfig
from deerflow.agents.memory.backends.deermem.deermem.core.llm import build_llm
from deerflow.agents.memory.backends.deermem.deermem.core.paths import DEFAULT_AGENT_BUCKET
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue
from deerflow.agents.memory.backends.deermem.deermem.core.storage import create_empty_memory, create_storage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

from .contract import Protocol, SemanticCase

ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = ROOT.parents[2]
PROMPT_PATH = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "agents" / "memory" / "backends" / "deermem" / "deermem" / "core" / "prompts" / "memory_update.chat.yaml"
ROW_SCHEMA_VERSION = 2
MARKER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LiveSettings:
    provider: str
    model: str
    temperature: float
    api_key_env: str
    base_url_env: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "api_key_env": self.api_key_env,
            "base_url_env": self.base_url_env,
        }


@dataclass(frozen=True)
class RunReport:
    reused: int
    executed: int


class _StaticModel:
    def __init__(self, output: dict[str, Any]):
        self.output = output
        self.prompt_sha256: str | None = None

    def invoke(self, prompt: Any, config: dict[str, Any] | None = None) -> Any:
        self.prompt_sha256 = _sha256_json(_prompt_projection(prompt))
        return SimpleNamespace(content=json.dumps(self.output), usage_metadata={})


class _CapturingModel:
    def __init__(self, model: Any):
        self.model = model
        self.prompt_sha256: str | None = None
        self.usage_metadata: dict[str, Any] = {}
        self.response_model: str | None = None

    def invoke(self, prompt: Any, config: dict[str, Any] | None = None) -> Any:
        self.prompt_sha256 = _sha256_json(_prompt_projection(prompt))
        response = self.model.invoke(prompt, config=config)
        usage = getattr(response, "usage_metadata", None)
        self.usage_metadata = usage if isinstance(usage, dict) else {}
        metadata = getattr(response, "response_metadata", None)
        if isinstance(metadata, dict) and isinstance(metadata.get("model_name"), str):
            self.response_model = metadata["model_name"]
        return response


def _prompt_projection(prompt: Any) -> list[dict[str, str]]:
    return [{"type": str(getattr(message, "type", "unknown")), "content": str(getattr(message, "content", message))} for message in prompt]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _git_revision() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def protocol_artifacts(manifest_path: Path) -> dict[str, str | None]:
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "extraction_prompt_sha256": sha256_file(PROMPT_PATH),
        "source_revision": _git_revision(),
    }


def _marker(mode: str, protocol: Protocol, manifest_path: Path, settings: LiveSettings | None) -> dict[str, Any]:
    return {
        "schema_version": MARKER_SCHEMA_VERSION,
        "protocol_id": protocol.protocol_id,
        "mode": mode,
        "artifacts": protocol_artifacts(manifest_path),
        "model": settings.public_dict() if settings else {"provider": "deterministic-static", "model": "offline-fixture", "temperature": 0.0},
    }


def ensure_run_identity(output_dir: Path, *, mode: str, protocol: Protocol, manifest_path: Path, settings: LiveSettings | None) -> dict[str, Any]:
    expected = _marker(mode, protocol, manifest_path, settings)
    marker_path = output_dir / "run.json"
    if marker_path.exists():
        actual = json.loads(marker_path.read_text(encoding="utf-8"))
        comparable = {key: actual.get(key) for key in expected}
        if comparable != expected:
            raise ValueError(f"{marker_path} belongs to a different protocol, source revision, prompt, mode, or model")
        return actual
    marker = dict(expected)
    marker["created_at"] = datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"
    _atomic_write_json(marker_path, marker)
    return marker


def _case_fingerprint(case: SemanticCase, marker: dict[str, Any]) -> str:
    return _sha256_json(
        {
            "protocol_id": marker["protocol_id"],
            "mode": marker["mode"],
            "artifacts": marker["artifacts"],
            "model": marker["model"],
            "case": {
                "id": case.case_id,
                "category": case.category,
                "messages": case.messages,
                "offline_output": case.offline_output if marker["mode"] == "offline" else None,
                "persisted": case.expected_persisted_canaries,
                "rejected": case.expected_rejected_canaries,
                "removed": case.expected_removed_canaries,
                "seed_facts": case.seed_facts,
            },
        }
    )


def _routing_fingerprint(protocol: Protocol, marker: dict[str, Any]) -> str:
    routing = protocol.routing_case
    return _sha256_json({"protocol_id": marker["protocol_id"], "mode": "offline", "artifacts": marker["artifacts"], "routing": routing.__dict__})


def _row_path(output_dir: Path, row_id: str) -> Path:
    return output_dir / "rows" / f"{row_id}.json"


def row_result_sha256(row: dict[str, Any]) -> str:
    """Hash a row without its self-authenticating result hash."""
    return _sha256_json({key: value for key, value in row.items() if key != "result_sha256"})


def _seal_row(row: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(row)
    sealed["result_sha256"] = row_result_sha256(sealed)
    return sealed


def row_is_intact(row: dict[str, Any]) -> bool:
    digest = row.get("result_sha256")
    return isinstance(digest, str) and digest == row_result_sha256(row)


def _load_reusable_row(path: Path, fingerprint: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict) or row.get("schema_version") != ROW_SCHEMA_VERSION or row.get("request_fingerprint") != fingerprint or not row_is_intact(row):
        return None
    if row.get("suite") == "semantic_model_quality" and row.get("update_succeeded") is not True:
        return None
    return row


def _messages(case: SemanticCase) -> list[Any]:
    classes = {"user": HumanMessage, "assistant": AIMessage}
    return [classes[message["role"]](content=message["content"]) for message in case.messages]


def _config(storage_path: Path, model: DeerMemModelConfig | None = None) -> DeerMemConfig:
    return DeerMemConfig(
        storage_path=str(storage_path),
        retrieval_adapter="",
        token_counting="char",
        staleness_review_enabled=False,
        consolidation_enabled=False,
        model=model or DeerMemModelConfig(),
    )


def _contains(memory: dict[str, Any], canary: str) -> bool:
    """Check agent-local facts only; shared summaries are not routing leaks."""
    return any(canary in str(fact.get("content", "")) for fact in memory.get("facts", []) if isinstance(fact, dict))


def _contains_semantic(memory: dict[str, Any], canary: str) -> bool:
    if _contains(memory, canary):
        return True
    for group in ("user", "history"):
        sections = memory.get(group, {})
        if not isinstance(sections, dict):
            continue
        for section in sections.values():
            if isinstance(section, dict) and isinstance(summary := section.get("summary"), str) and canary in summary:
                return True
    return False


def _seed(updater: MemoryUpdater, case: SemanticCase, *, agent_name: str, user_id: str) -> None:
    if not case.seed_facts:
        return
    memory = create_empty_memory()
    memory["facts"] = [dict(fact) for fact in case.seed_facts]
    updater.import_memory_data(memory, agent_name=agent_name, user_id=user_id)


def _live_model(settings: LiveSettings) -> tuple[DeerMemModelConfig, _CapturingModel]:
    api_key = os.environ.get(settings.api_key_env)
    if not api_key:
        raise ValueError(f"required API key environment variable {settings.api_key_env!r} is not set")
    base_url = os.environ.get(settings.base_url_env) if settings.base_url_env else None
    model_config = DeerMemModelConfig(
        provider=settings.provider,
        model=settings.model,
        api_key=api_key,
        base_url=base_url,
        temperature=settings.temperature,
    )
    model = build_llm(model_config)
    if model is None:
        raise ValueError("the configured live model could not be constructed")
    return model_config, _CapturingModel(model)


def _semantic_row(case: SemanticCase, *, mode: str, marker: dict[str, Any], settings: LiveSettings | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="deermem-scope-semantic-") as directory:
        if mode == "offline":
            model_config = DeerMemModelConfig(model="offline-fixture", temperature=0.0)
            model: _StaticModel | _CapturingModel = _StaticModel(case.offline_output)
        else:
            assert settings is not None
            model_config, model = _live_model(settings)
        config = _config(Path(directory), model_config)
        updater = MemoryUpdater(config, create_storage(config), llm=model)
        agent_name = "scope-benchmark-agent"
        user_id = f"scope-{case.case_id}"
        _seed(updater, case, agent_name=agent_name, user_id=user_id)
        succeeded = updater.update_memory(
            _messages(case),
            thread_id=f"scope-{case.case_id}",
            agent_name=agent_name,
            user_id=user_id,
            bypass_watermark=True,
        )
        if not succeeded:
            raise RuntimeError(f"memory update failed for benchmark case {case.case_id}; no result row was saved, rerun to retry")
        memory = updater.get_memory_data(agent_name, user_id=user_id)
        persisted_present = [canary for canary in case.expected_persisted_canaries if _contains_semantic(memory, canary)]
        rejected_present = [canary for canary in case.expected_rejected_canaries if _contains_semantic(memory, canary)]
        removed_present = [canary for canary in case.expected_removed_canaries if _contains_semantic(memory, canary)]
        correction_success = case.category != "atomic_correction" or (set(persisted_present) == set(case.expected_persisted_canaries) and not removed_present)
        return _seal_row(
            {
                "schema_version": ROW_SCHEMA_VERSION,
                "suite": "semantic_model_quality",
                "row_id": case.case_id,
                "category": case.category,
                "request_fingerprint": _case_fingerprint(case, marker),
                "update_succeeded": bool(succeeded),
                "expected_persisted_canaries": list(case.expected_persisted_canaries),
                "expected_rejected_canaries": list(case.expected_rejected_canaries),
                "expected_removed_canaries": list(case.expected_removed_canaries),
                "persisted_canaries_present": persisted_present,
                "rejected_canaries_present": rejected_present,
                "removed_canaries_present": removed_present,
                "atomic_correction_success": correction_success,
                "extraction_prompt_render_sha256": model.prompt_sha256,
                "response_model": getattr(model, "response_model", None),
                "usage": getattr(model, "usage_metadata", {}),
            }
        )


def _routing_row(protocol: Protocol, marker: dict[str, Any]) -> dict[str, Any]:
    routing = protocol.routing_case
    output = {
        "user": {},
        "history": {},
        "newFacts": [
            {
                "content": f"Synthetic routing marker {routing.canary}.",
                "category": "context",
                "confidence": 0.99,
                "scope": "user",
                "durability": "durable",
                "authority": "descriptive",
            }
        ],
        "factsToRemove": [],
    }
    with tempfile.TemporaryDirectory(prefix="deermem-scope-routing-") as directory:
        model = _StaticModel(output)
        config = _config(Path(directory), DeerMemModelConfig(model="offline-fixture", temperature=0.0))
        updater = MemoryUpdater(config, create_storage(config), llm=model)
        queue = MemoryUpdateQueue(config, updater)
        queue.add(
            "routing-thread",
            [HumanMessage(content=f"Remember my synthetic routing marker {routing.canary}.")],
            agent_name=routing.selected["agent_name"],
            user_id=routing.selected["user_id"],
        )
        queue.flush(skip_inter_item_delay=True)
        default_scope = {
            "user_id": routing.selected["user_id"],
            "agent_name": DEFAULT_AGENT_BUCKET,
        }

        def present(scope: dict[str, str]) -> bool:
            memory = updater.get_memory_data(
                scope["agent_name"],
                user_id=scope["user_id"],
            )
            return _contains(memory, routing.canary)

        return _seal_row(
            {
                "schema_version": ROW_SCHEMA_VERSION,
                "suite": "deterministic_identity_routing",
                "row_id": routing.case_id,
                "request_fingerprint": _routing_fingerprint(protocol, marker),
                "checked_scopes": {
                    "selected": routing.selected,
                    "default": default_scope,
                    "other_agent": routing.other_agent,
                    "other_user": routing.other_user,
                },
                "selected_present": present(routing.selected),
                "default_present": present(default_scope),
                "other_agent_present": present(routing.other_agent),
                "other_user_present": present(routing.other_user),
                "extraction_prompt_render_sha256": model.prompt_sha256,
            }
        )


def run(protocol: Protocol, *, manifest_path: Path, output_dir: Path, mode: str, settings: LiveSettings | None = None) -> RunReport:
    if mode not in {"offline", "live"}:
        raise ValueError("mode must be offline or live")
    if (mode == "live") != (settings is not None):
        raise ValueError("live settings are required exactly for live mode")
    marker = ensure_run_identity(output_dir, mode=mode, protocol=protocol, manifest_path=manifest_path, settings=settings)
    reused = 0
    executed = 0
    for case in protocol.semantic_cases:
        fingerprint = _case_fingerprint(case, marker)
        path = _row_path(output_dir, case.case_id)
        if _load_reusable_row(path, fingerprint) is not None:
            reused += 1
            continue
        _atomic_write_json(path, _semantic_row(case, mode=mode, marker=marker, settings=settings))
        executed += 1
    if mode == "offline":
        fingerprint = _routing_fingerprint(protocol, marker)
        path = _row_path(output_dir, protocol.routing_case.case_id)
        if _load_reusable_row(path, fingerprint) is not None:
            reused += 1
        else:
            _atomic_write_json(path, _routing_row(protocol, marker))
            executed += 1
    return RunReport(reused=reused, executed=executed)
