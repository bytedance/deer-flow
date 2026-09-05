from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

from .manifest import IdentityCase, ScopeIsolationManifest, SemanticCase, sha256_file, validate_production_contract
from .report import compute_metrics

ROW_SCHEMA_VERSION = 1
RESPONSES_DIRNAME = "responses"


@dataclass(frozen=True)
class BenchmarkRunReport:
    semantic_cases: int
    identity_observations: int


@dataclass(frozen=True)
class LiveRunReport:
    reused: int
    called: int
    failed: tuple[str, ...]


def response_path(output_dir: Path, case_id: str) -> Path:
    return output_dir / RESPONSES_DIRNAME / f"{case_id}.json"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _json_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _git_metadata(backend_root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=backend_root, check=True, capture_output=True, text=True)
        return result.stdout.strip()

    return {"head": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def _prompt_text(prompt: object) -> str:
    items = prompt if isinstance(prompt, list) else [prompt]
    parts: list[str] = []
    for item in items:
        content = getattr(item, "content", item)
        if isinstance(content, str):
            parts.append(content)
        else:
            parts.append(json.dumps(content, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


def _replace_seed_placeholders(value: object, seed_ids: dict[str, str]) -> object:
    if isinstance(value, str) and value.startswith("$seed:"):
        canary = value.removeprefix("$seed:")
        if canary not in seed_ids:
            raise ValueError(f"missing seeded fact for {canary}")
        return seed_ids[canary]
    if isinstance(value, list):
        return [_replace_seed_placeholders(item, seed_ids) for item in value]
    if isinstance(value, dict):
        return {key: _replace_seed_placeholders(item, seed_ids) for key, item in value.items()}
    return value


class ManifestReplayModel:
    """Deterministic model double that still receives the production prompt."""

    def __init__(self, manifest: ScopeIsolationManifest):
        self._cases = {case.id: case for case in manifest.semantic_cases}
        self._case_id: str | None = None
        self._seed_ids: dict[str, str] = {}
        self.prompts: list[str] = []

    def prepare(self, case_id: str, seed_ids: dict[str, str]) -> None:
        self._case_id = case_id
        self._seed_ids = dict(seed_ids)

    def invoke(self, prompt: object, config: object | None = None) -> AIMessage:
        del config
        prompt_text = _prompt_text(prompt)
        self.prompts.append(prompt_text)
        if self._case_id is None:
            raise RuntimeError("replay model was not prepared for a case")
        response = _replace_seed_placeholders(copy.deepcopy(self._cases[self._case_id].replay_response), self._seed_ids)
        return AIMessage(content=json.dumps(response, ensure_ascii=False))


def _build_manager(storage_path: Path, model: object, extraction_events: list[dict[str, Any]]) -> DeerMem:
    return DeerMem.from_config(
        {
            "storage_path": str(storage_path),
            "retrieval_adapter": "",
            "token_counting": "char",
            "debounce_seconds": 300,
            "max_facts": 100,
            "staleness_review_enabled": False,
        },
        host_llm_factory=lambda: model,
        extraction_callback=lambda event: extraction_events.append(dict(event)),
    )


def _messages(case: SemanticCase) -> list[HumanMessage | AIMessage]:
    types = {"human": HumanMessage, "ai": AIMessage}
    return [types[message.role](content=message.content) for message in case.messages]


def _memory_text(manager: DeerMem, *, user_id: str, agent_name: str | None) -> str:
    memory = manager.get_memory(user_id=user_id, agent_name=agent_name)
    return json.dumps(memory, ensure_ascii=False, sort_keys=True)


def _fact_text(manager: DeerMem, *, user_id: str, agent_name: str | None) -> str:
    memory = manager.get_memory(user_id=user_id, agent_name=agent_name)
    return json.dumps(memory.get("facts", []), ensure_ascii=False, sort_keys=True)


def _identity_rows(
    manager: DeerMem,
    identity_case: IdentityCase,
    source_case: SemanticCase,
    canary: str,
) -> list[dict[str, object]]:
    rows = []
    for probe in identity_case.probes:
        # Summaries are intentionally user-global in DeerMem. Agent isolation
        # applies to facts, so inspect only the fact collection here.
        observed = canary in _fact_text(manager, user_id=probe.user_id, agent_name=probe.agent_name)
        rows.append(
            {
                "schema_version": ROW_SCHEMA_VERSION,
                "protocol_id": "deermem-scope-isolation-v1",
                "case_id": identity_case.id,
                "probe_id": probe.id,
                "source_case_id": source_case.id,
                "source_user_id": source_case.user_id,
                "source_agent_name": source_case.agent_name,
                "probe_user_id": probe.user_id,
                "probe_agent_name": probe.agent_name,
                "dimension": probe.dimension,
                "expected_visible": probe.expected_visible,
                "observed_visible": observed,
                "passed": observed == probe.expected_visible,
            }
        )
    return rows


def _evaluate_case(
    case: SemanticCase,
    *,
    model: object,
    identity_cases: list[IdentityCase],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    extraction_events: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="deermem-scope-isolation-") as temporary:
        manager = _build_manager(Path(temporary), model, extraction_events)
        seed_ids: dict[str, str] = {}
        try:
            for fact in case.seed_facts:
                _, fact_id = manager.create_fact(
                    fact.content,
                    category=fact.category,
                    confidence=fact.confidence,
                    user_id=case.user_id,
                    agent_name=case.agent_name,
                )
                if fact_id is None:
                    raise RuntimeError(f"failed to seed fact for {case.id}")
                seed_ids[fact.content] = fact_id

            prepare = getattr(model, "prepare", None)
            if callable(prepare):
                prepare(case.id, seed_ids)
            manager.add(
                f"benchmark-{case.id}",
                _messages(case),
                user_id=case.user_id,
                agent_name=case.agent_name,
            )
            flush_completed = manager.shutdown_flush(30.0)
            extraction_success = bool(extraction_events and extraction_events[-1].get("success"))
            if not flush_completed or not extraction_success:
                raise RuntimeError(f"DeerMem extraction failed for {case.id} (flush_completed={flush_completed}, extraction_success={extraction_success})")

            stored = _memory_text(manager, user_id=case.user_id, agent_name=case.agent_name)
            persist_checks = [{"canary": canary, "observed": canary in stored, "passed": canary in stored} for canary in case.expected.persist_canaries]
            reject_checks = [{"canary": canary, "observed": canary in stored, "passed": canary not in stored} for canary in case.expected.reject_canaries]
            correction_checks = []
            for correction in case.expected.corrections:
                old_observed = correction.old_canary in stored
                new_observed = correction.new_canary in stored
                correction_checks.append(
                    {
                        "new_canary": correction.new_canary,
                        "new_observed": new_observed,
                        "old_canary": correction.old_canary,
                        "old_observed": old_observed,
                        "passed": new_observed and not old_observed,
                    }
                )

            semantic_row: dict[str, object] = {
                "schema_version": ROW_SCHEMA_VERSION,
                "protocol_id": "deermem-scope-isolation-v1",
                "case_id": case.id,
                "scenario": case.scenario,
                "flush_completed": flush_completed,
                "extraction_success": extraction_success,
                "persist_checks": persist_checks,
                "reject_checks": reject_checks,
                "correction_checks": correction_checks,
            }
            observations: list[dict[str, object]] = []
            for identity_case in identity_cases:
                if identity_case.source_semantic_case_id != case.id:
                    continue
                if len(case.expected.persist_canaries) != 1:
                    raise ValueError("an identity source case must have exactly one persistence canary")
                observations.extend(_identity_rows(manager, identity_case, case, case.expected.persist_canaries[0]))
            return semantic_row, observations
        finally:
            manager.close()


def _write_aggregate_files(
    output_dir: Path,
    *,
    protocol_id: str,
    semantic_rows: list[dict[str, object]],
    identity_rows: list[dict[str, object]],
) -> None:
    semantic_text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in semantic_rows)
    identity_text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in identity_rows)
    summary = {
        "schema_version": 1,
        "protocol_id": protocol_id,
        "semantic_cases": len(semantic_rows),
        "identity_observations": len(identity_rows),
        "metrics": compute_metrics(semantic_rows, identity_rows),
    }
    _atomic_write_text(output_dir / "semantic.rows.jsonl", semantic_text)
    _atomic_write_text(output_dir / "identity.rows.jsonl", identity_text)
    _atomic_write_text(output_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _artifact_hashes(manifest_path: Path, prompt_path: Path) -> dict[str, str]:
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "production_prompt_sha256": sha256_file(prompt_path),
    }


def run_offline(
    manifest: ScopeIsolationManifest,
    *,
    output_dir: Path,
    manifest_path: Path,
    prompt_path: Path,
    backend_root: Path,
) -> BenchmarkRunReport:
    validate_production_contract(manifest, prompt_path)
    targets = [output_dir / name for name in ("run.json", "semantic.rows.jsonl", "identity.rows.jsonl", "summary.json")]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing result files: {', '.join(str(path) for path in existing)}")
    model = ManifestReplayModel(manifest)
    semantic_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    for case in manifest.semantic_cases:
        semantic, observations = _evaluate_case(case, model=model, identity_cases=manifest.identity_cases)
        semantic_rows.append(semantic)
        identity_rows.extend(observations)
    _write_aggregate_files(
        output_dir,
        protocol_id=manifest.protocol_id,
        semantic_rows=semantic_rows,
        identity_rows=identity_rows,
    )
    marker = {
        "schema_version": 1,
        "protocol_id": manifest.protocol_id,
        "mode": "offline",
        "created_at": _timestamp(),
        "git": _git_metadata(backend_root),
        "artifacts": _artifact_hashes(manifest_path, prompt_path),
    }
    _atomic_write_text(output_dir / "run.json", json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return BenchmarkRunReport(semantic_cases=len(semantic_rows), identity_observations=len(identity_rows))


def _request_fingerprint(
    case: SemanticCase,
    *,
    manifest: ScopeIsolationManifest,
    prompt_path: Path,
    model_name: str,
    temperature: float,
) -> str:
    return _json_hash(
        {
            "protocol_id": manifest.protocol_id,
            "production_prompt_sha256": sha256_file(prompt_path),
            "case": case.model_dump(mode="json"),
            "model": model_name,
            "temperature": temperature,
        }
    )


def _load_reusable_response(path: Path, case: SemanticCase, fingerprint: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict):
        return None
    if (
        row.get("schema_version") != ROW_SCHEMA_VERSION
        or row.get("case_id") != case.id
        or row.get("scenario") != case.scenario
        or row.get("request_fingerprint") != fingerprint
        or not isinstance(row.get("semantic_row"), dict)
        or not isinstance(row.get("identity_rows"), list)
    ):
        return None
    return row


def _ensure_live_identity(
    output_dir: Path,
    *,
    manifest: ScopeIsolationManifest,
    manifest_path: Path,
    prompt_path: Path,
    backend_root: Path,
    model_name: str,
    temperature: float,
) -> None:
    marker_path = output_dir / "run.json"
    identity = {
        "protocol_id": manifest.protocol_id,
        "mode": "live",
        "artifacts": _artifact_hashes(manifest_path, prompt_path),
        "model": {"name": model_name, "temperature": temperature},
    }
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if any(marker.get(key) != value for key, value in identity.items()):
            raise ValueError(f"{marker_path} belongs to a different run identity; use a new output directory")
        return
    marker = {
        "schema_version": 1,
        "created_at": _timestamp(),
        "git": _git_metadata(backend_root),
        **identity,
    }
    _atomic_write_text(marker_path, json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def run_live(
    manifest: ScopeIsolationManifest,
    *,
    model: object,
    model_name: str,
    temperature: float,
    output_dir: Path,
    manifest_path: Path,
    prompt_path: Path,
    backend_root: Path,
) -> LiveRunReport:
    validate_production_contract(manifest, prompt_path)
    _ensure_live_identity(
        output_dir,
        manifest=manifest,
        manifest_path=manifest_path,
        prompt_path=prompt_path,
        backend_root=backend_root,
        model_name=model_name,
        temperature=temperature,
    )
    reused = 0
    called = 0
    failed: list[str] = []
    semantic_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    for case in manifest.semantic_cases:
        fingerprint = _request_fingerprint(
            case,
            manifest=manifest,
            prompt_path=prompt_path,
            model_name=model_name,
            temperature=temperature,
        )
        path = response_path(output_dir, case.id)
        completed = _load_reusable_response(path, case, fingerprint)
        if completed is not None:
            reused += 1
        else:
            try:
                semantic, observations = _evaluate_case(case, model=model, identity_cases=manifest.identity_cases)
            except Exception as error:
                failed.append(f"{case.id}: {error}")
                continue
            completed = {
                "schema_version": ROW_SCHEMA_VERSION,
                "protocol_id": manifest.protocol_id,
                "case_id": case.id,
                "scenario": case.scenario,
                "request_fingerprint": fingerprint,
                "model": model_name,
                "temperature": temperature,
                "created_at": _timestamp(),
                "semantic_row": semantic,
                "identity_rows": observations,
            }
            _atomic_write_text(path, json.dumps(completed, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            called += 1
        semantic_rows.append(completed["semantic_row"])
        identity_rows.extend(completed["identity_rows"])
    _write_aggregate_files(
        output_dir,
        protocol_id=manifest.protocol_id,
        semantic_rows=semantic_rows,
        identity_rows=identity_rows,
    )
    return LiveRunReport(reused=reused, called=called, failed=tuple(sorted(failed)))
