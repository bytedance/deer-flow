"""Macro-evolution prompt optimizer for layered prompt assets."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.models.factory import create_chat_model

PROMPT_OPTIMIZER_SCHEMA_VERSION = "deerflow.prompt_optimizer.v1"
OPTIMIZER_ALLOWED_LAYERS = {"L1", "L4", "L5"}
OPTIMIZER_ALLOWED_MODES = {"rules", "llm_structured_patch"}


class VenueOverridePatch(BaseModel):
    venue_name: str
    layer_id: str
    version: str


class OptimizerConfig(BaseModel):
    enabled: bool = True
    optimizer_mode: Literal["rules", "llm_structured_patch"] = "rules"
    model_name: str | None = None
    thinking_enabled: bool = False
    temperature: float = 0.0
    max_candidate_count: int = 3
    fallback_to_rules: bool = True


class StructuredPromptLayerPatch(BaseModel):
    layer_id: str
    base_version: str
    new_version: str
    instructions_added: list[str] = Field(default_factory=list)
    instructions_removed: list[str] = Field(default_factory=list)
    rationale: str = ""


class StructuredPromptPatchPlan(BaseModel):
    optimizer_mode: Literal["llm_structured_patch"] = "llm_structured_patch"
    summary: str = ""
    patches: list[StructuredPromptLayerPatch] = Field(default_factory=list)


class PromptPatchCandidate(BaseModel):
    layer_id: str
    base_version: str
    new_version: str
    instructions_added: list[str] = Field(default_factory=list)
    instructions_removed: list[str] = Field(default_factory=list)
    rationale: str = ""
    set_as_default: bool = True
    venue_override: VenueOverridePatch | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _project_root() -> Path:
    # backend/src/research_writing/prompt_optimizer.py -> project root
    return Path(__file__).resolve().parents[3]


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_dump_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _safe_dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalized_reason_distribution(compile_metrics: dict[str, Any]) -> dict[str, int]:
    raw = compile_metrics.get("safety_valve_reason_distribution")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        reason = str(key).strip()
        if not reason:
            continue
        out[reason] = max(0, int(value or 0))
    return out


def _failed_checks(offline_report: dict[str, Any]) -> list[str]:
    rows = offline_report.get("failed_checks")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        layer = str(item.get("layer") or "").strip()
        name = str(item.get("name") or "").strip()
        if not layer and not name:
            continue
        out.append(f"{layer}:{name}".strip(":"))
    return out


def _collect_optimizer_signals(
    *,
    compile_metrics: dict[str, Any],
    offline_report: dict[str, Any],
) -> dict[str, Any]:
    reasons = _normalized_reason_distribution(compile_metrics)
    reason_text = "\n".join(reasons.keys()).lower()
    failed_checks = _failed_checks(offline_report)
    failed_text = "\n".join(failed_checks).lower()

    binding_failures = "binding" in reason_text or "citation" in reason_text or "grounding" in reason_text
    method_detail_omission = "experimental details" in reason_text or "protocol" in reason_text or "sample size" in reason_text
    causal_overclaim = "causal" in reason_text or "overclaim" in reason_text
    failure_mode_regression = any("failure_mode" in token for token in failed_checks)
    core_calibration_regression = any("core_" in token for token in failed_checks)
    domain_gap_regression = any("domain_" in token for token in failed_checks)

    if "citation_hallucination" in failed_text or "hallucination" in failed_text:
        binding_failures = True
    if "ece" in failed_text or "brier" in failed_text:
        core_calibration_regression = True

    return {
        "binding_failures": binding_failures,
        "method_detail_omission": method_detail_omission,
        "causal_overclaim": causal_overclaim,
        "failure_mode_regression": failure_mode_regression,
        "core_calibration_regression": core_calibration_regression,
        "domain_gap_regression": domain_gap_regression,
        "raw_reason_distribution": reasons,
        "failed_checks": failed_checks,
        "offline_status": str(offline_report.get("status") or "unknown"),
    }


def _existing_default_version(layer_row: dict[str, Any]) -> str:
    version = str(layer_row.get("default_version") or "").strip()
    if version:
        return version
    versions = layer_row.get("versions")
    if isinstance(versions, dict) and versions:
        return str(next(iter(versions.keys())))
    return "v1"


def _next_version_key(versions: dict[str, Any], *, prefix: str | None = None) -> str:
    if not versions:
        return f"{prefix}v1" if prefix else "v1"
    if prefix:
        matcher = re.compile(rf"^{re.escape(prefix)}v(\d+)$")
        nums = [int(match.group(1)) for key in versions.keys() if (match := matcher.match(str(key).strip()))]
        return f"{prefix}v{(max(nums) + 1) if nums else 1}"
    matcher = re.compile(r"^v(\d+)$")
    nums = [int(match.group(1)) for key in versions.keys() if (match := matcher.match(str(key).strip()))]
    return f"v{(max(nums) + 1) if nums else 1}"


def _append_unique_lines(base_text: str, lines: list[str]) -> str:
    existing_lines = [row.rstrip() for row in str(base_text or "").splitlines()]
    seen = {row.strip().lower() for row in existing_lines if row.strip()}
    out = list(existing_lines)
    for line in lines:
        token = str(line or "").strip()
        if not token:
            continue
        if token.lower() in seen:
            continue
        out.append(token)
        seen.add(token.lower())
    return "\n".join(out).strip()


def _remove_lines(base_text: str, lines: list[str]) -> str:
    blocked = {str(line or "").strip().lower() for line in lines if str(line or "").strip()}
    kept = [row.rstrip() for row in str(base_text or "").splitlines() if row.strip().lower() not in blocked]
    return "\n".join(kept).strip()


def _prompt_asset_layer_snapshot(prompt_layers: dict[str, Any]) -> dict[str, Any]:
    layers = prompt_layers.get("layers")
    if not isinstance(layers, dict):
        return {}
    snapshot: dict[str, Any] = {}
    for layer_id in sorted(OPTIMIZER_ALLOWED_LAYERS):
        row = layers.get(layer_id)
        if not isinstance(row, dict):
            continue
        versions = row.get("versions")
        if not isinstance(versions, dict):
            continue
        snapshot[layer_id] = {
            "default_version": str(row.get("default_version") or "").strip(),
            "rollback_version": str(row.get("rollback_version") or "").strip(),
            "available_versions": list(versions.keys()),
            "version_text": {str(version): str(text or "") for version, text in versions.items()},
        }
    return snapshot


def _derive_candidate_policy(*, layer_id: str, base_version: str, new_version: str) -> tuple[bool, VenueOverridePatch | None]:
    set_as_default = layer_id != "L4"
    venue_override: VenueOverridePatch | None = None
    if layer_id == "L4" and (base_version.startswith("ieee.") or new_version.startswith("ieee.")):
        venue_override = VenueOverridePatch(
            venue_name="ieee",
            layer_id="L4",
            version=new_version,
        )
    return set_as_default, venue_override


def build_prompt_patch_candidate(patch: StructuredPromptLayerPatch) -> PromptPatchCandidate:
    set_as_default, venue_override = _derive_candidate_policy(
        layer_id=patch.layer_id,
        base_version=patch.base_version,
        new_version=patch.new_version,
    )
    return PromptPatchCandidate(
        layer_id=patch.layer_id,
        base_version=patch.base_version,
        new_version=patch.new_version,
        instructions_added=list(patch.instructions_added),
        instructions_removed=list(patch.instructions_removed),
        rationale=str(patch.rationale or "").strip(),
        set_as_default=set_as_default,
        venue_override=venue_override,
    )


def _build_rule_patch_plan(prompt_layers: dict[str, Any], signals: dict[str, Any]) -> StructuredPromptPatchPlan:
    layers = prompt_layers.get("layers") if isinstance(prompt_layers.get("layers"), dict) else {}
    patches: list[StructuredPromptLayerPatch] = []

    if signals.get("binding_failures"):
        row = layers.get("L1")
        versions = row.get("versions") if isinstance(row, dict) else None
        if isinstance(versions, dict) and versions:
            base_version = _existing_default_version(row)
            patches.append(
                StructuredPromptLayerPatch(
                    layer_id="L1",
                    base_version=base_version,
                    new_version=_next_version_key(versions),
                    instructions_added=[
                        "- Fail-close gate: any unknown/placeholder [data:*] or [citation:*] marker triggers immediate rewrite.",
                        "- Reflection carry-over is mandatory after each rewrite rejection and must be attached to the next generation prompt.",
                    ],
                    rationale="Harden L1 fail-close behavior for recurring citation and binding failures.",
                )
            )

    if signals.get("method_detail_omission"):
        row = layers.get("L4")
        versions = row.get("versions") if isinstance(row, dict) else None
        if isinstance(versions, dict) and versions:
            base_version = "ieee.v1" if "ieee.v1" in versions else _existing_default_version(row)
            new_version = _next_version_key(versions, prefix="ieee.")
            patches.append(
                StructuredPromptLayerPatch(
                    layer_id="L4",
                    base_version=base_version,
                    new_version=new_version,
                    instructions_added=[
                        "- Methods completeness gate: force explicit n/sample size, random seed, protocol controls, and ablation assumptions in method-sensitive sections.",
                        "- If these details are unavailable, downgrade certainty and emit unresolved-gap action bullets instead of publication-ready claims.",
                    ],
                    rationale="Tighten venue-specific method reporting requirements for IEEE-style outputs.",
                )
            )

    if signals.get("causal_overclaim") or signals.get("core_calibration_regression"):
        row = layers.get("L5")
        versions = row.get("versions") if isinstance(row, dict) else None
        if isinstance(versions, dict) and versions:
            base_version = _existing_default_version(row)
            patches.append(
                StructuredPromptLayerPatch(
                    layer_id="L5",
                    base_version=base_version,
                    new_version=_next_version_key(versions),
                    instructions_added=[
                        "- Causal-overclaim guard: any mechanism/causal claim without explicit [data:*] + [citation:*] support must be rewritten with hedged modality.",
                        "- During reflection-guided rewrite, preserve unresolved confounders explicitly and forbid certainty escalation.",
                    ],
                    rationale="Reduce causal overclaiming and calibration regressions in expert reasoning output.",
                )
            )

    return StructuredPromptPatchPlan(
        summary="Metrics-guided structured patch candidate for L1/L4/L5.",
        patches=patches,
    )


def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty LLM response")
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _structured_patch_prompt(
    *,
    signals: dict[str, Any],
    prompt_layers: dict[str, Any],
    offline_report: dict[str, Any],
    compile_metrics: dict[str, Any],
    optimizer_config: OptimizerConfig,
) -> str:
    seed_plan = _build_rule_patch_plan(prompt_layers, signals)
    return (
        "You are a strict prompt-layer optimizer for DeerFlow.\n"
        "Return JSON only.\n"
        "You may edit only layers L1, L4, and L5.\n"
        "Do not rewrite the whole YAML file.\n"
        "Propose a structured patch plan that keeps version naming stable and minimizes edits.\n"
        f"Return at most {optimizer_config.max_candidate_count} patches.\n"
        "Each patch can add at most 4 instructions and remove at most 2 instructions.\n"
        "Do not output file-writing or activation policy fields such as set_as_default or venue_override.\n"
        "JSON schema:\n"
        "{\n"
        '  "optimizer_mode":"llm_structured_patch",\n'
        '  "summary":"...",\n'
        '  "patches":[\n'
        "    {\n"
        '      "layer_id":"L1|L4|L5",\n'
        '      "base_version":"existing version id",\n'
        '      "new_version":"new version id",\n'
        '      "instructions_added":["..."],\n'
        '      "instructions_removed":["..."],\n'
        '      "rationale":"why this change helps"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Signals:\n"
        f"{json.dumps(signals, ensure_ascii=False, indent=2)}\n\n"
        "Compile metrics summary:\n"
        f"{json.dumps({'safety_valve_reason_distribution': compile_metrics.get('safety_valve_reason_distribution', {})}, ensure_ascii=False, indent=2)}\n\n"
        "Offline regression summary:\n"
        f"{json.dumps({'status': offline_report.get('status'), 'failed_checks': offline_report.get('failed_checks', [])}, ensure_ascii=False, indent=2)}\n\n"
        "Current target prompt-layer snapshot:\n"
        f"{json.dumps(_prompt_asset_layer_snapshot(prompt_layers), ensure_ascii=False, indent=2)}\n\n"
        "A safe baseline patch candidate is shown below. Improve it only if helpful and stay equally conservative.\n"
        f"{json.dumps(seed_plan.model_dump(), ensure_ascii=False, indent=2)}"
    )


def _validate_version_transition(*, base_version: str, new_version: str) -> str | None:
    if not base_version or not new_version:
        return "base_version and new_version are required"
    if base_version == new_version:
        return "new_version must differ from base_version"
    dotted = re.match(r"^([a-z0-9_-]+\.)v\d+$", base_version, flags=re.IGNORECASE)
    if dotted:
        prefix = dotted.group(1)
        if not re.match(rf"^{re.escape(prefix)}v\d+$", new_version, flags=re.IGNORECASE):
            return f"new_version must keep prefix '{prefix}'"
    elif not re.match(r"^v\d+$", new_version, flags=re.IGNORECASE):
        return "new_version must match vN pattern"
    return None


def _validate_structured_patch_plan(
    *,
    plan_payload: dict[str, Any],
    prompt_layers: dict[str, Any],
) -> tuple[StructuredPromptPatchPlan | None, list[PromptPatchCandidate] | None, list[str]]:
    try:
        plan = StructuredPromptPatchPlan.model_validate(plan_payload)
    except Exception as exc:
        return None, None, [f"schema_validation_failed: {exc}"]

    layers = prompt_layers.get("layers")
    if not isinstance(layers, dict):
        return None, None, ["prompt_layers asset has no valid layers mapping"]

    issues: list[str] = []
    seen_layer_ids: set[str] = set()
    candidates: list[PromptPatchCandidate] = []
    for patch in plan.patches:
        if patch.layer_id not in OPTIMIZER_ALLOWED_LAYERS:
            issues.append(f"{patch.layer_id}: layer is outside the allowed scope")
            continue
        if patch.layer_id in seen_layer_ids:
            issues.append(f"{patch.layer_id}: duplicate layer patch is not allowed")
        seen_layer_ids.add(patch.layer_id)

        row = layers.get(patch.layer_id)
        versions = row.get("versions") if isinstance(row, dict) else None
        if not isinstance(row, dict) or not isinstance(versions, dict):
            issues.append(f"{patch.layer_id}: layer row is missing or invalid")
            continue
        if patch.base_version not in versions:
            issues.append(f"{patch.layer_id}: base_version '{patch.base_version}' does not exist")
        if patch.new_version in versions:
            issues.append(f"{patch.layer_id}: new_version '{patch.new_version}' already exists")
        version_issue = _validate_version_transition(base_version=patch.base_version, new_version=patch.new_version)
        if version_issue:
            issues.append(f"{patch.layer_id}: {version_issue}")
        if len(patch.instructions_added) > 4:
            issues.append(f"{patch.layer_id}: instructions_added exceeds hard limit")
        if len(patch.instructions_removed) > 2:
            issues.append(f"{patch.layer_id}: instructions_removed exceeds hard limit")
        if not patch.instructions_added and not patch.instructions_removed:
            issues.append(f"{patch.layer_id}: patch must include instructions_added or instructions_removed")
        candidates.append(build_prompt_patch_candidate(patch))

    if issues:
        return None, None, issues
    return plan, candidates, []


def _apply_structured_patch_plan(
    prompt_layers: dict[str, Any],
    plan: StructuredPromptPatchPlan | list[PromptPatchCandidate],
    *,
    optimizer_mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = json.loads(json.dumps(prompt_layers))
    layers = updated.get("layers")
    if not isinstance(layers, dict):
        return updated, []

    changes: list[dict[str, Any]] = []
    patches = plan if isinstance(plan, list) else [build_prompt_patch_candidate(item) for item in plan.patches]
    for patch in patches:
        row = layers.get(patch.layer_id)
        versions = row.get("versions") if isinstance(row, dict) else None
        if not isinstance(row, dict) or not isinstance(versions, dict):
            continue
        base_text = str(versions.get(patch.base_version) or "")
        rewritten = _remove_lines(base_text, patch.instructions_removed)
        rewritten = _append_unique_lines(rewritten, patch.instructions_added)
        versions[patch.new_version] = rewritten
        if patch.set_as_default:
            row["default_version"] = patch.new_version
        if patch.venue_override is not None:
            venue_overrides = updated.get("venue_layer_overrides")
            if not isinstance(venue_overrides, dict):
                venue_overrides = {}
                updated["venue_layer_overrides"] = venue_overrides
            venue_key = str(patch.venue_override.venue_name).strip().lower()
            venue_row = venue_overrides.get(venue_key)
            if not isinstance(venue_row, dict):
                venue_row = {}
                venue_overrides[venue_key] = venue_row
            venue_row[patch.layer_id] = patch.new_version
        changes.append(
            {
                "layer_id": patch.layer_id,
                "old_version": patch.base_version,
                "new_version": patch.new_version,
                "rationale": patch.rationale,
                "reason": patch.rationale,
                "optimizer_mode": optimizer_mode,
                "instructions_added": list(patch.instructions_added),
                "instructions_removed": list(patch.instructions_removed),
                "append_line_count": len(patch.instructions_added),
                "remove_line_count": len(patch.instructions_removed),
                "set_as_default": patch.set_as_default,
                "venue_override": patch.venue_override.model_dump() if patch.venue_override is not None else None,
            }
        )
    return updated, changes


def _resolve_optimizer_config(
    *,
    optimizer_config: OptimizerConfig | dict[str, Any] | None = None,
    optimizer_mode: str = "rules",
    llm_model_name: str | None = None,
    llm_thinking_enabled: bool = False,
    llm_temperature: float = 0.0,
) -> OptimizerConfig:
    if isinstance(optimizer_config, OptimizerConfig):
        resolved = optimizer_config.model_copy()
    elif isinstance(optimizer_config, dict):
        resolved = OptimizerConfig.model_validate(optimizer_config)
    else:
        resolved = OptimizerConfig(
            optimizer_mode=optimizer_mode,
            model_name=llm_model_name,
            thinking_enabled=llm_thinking_enabled,
            temperature=llm_temperature,
        )
    if resolved.optimizer_mode not in OPTIMIZER_ALLOWED_MODES:
        raise ValueError(f"Unsupported optimizer_mode: {resolved.optimizer_mode}")
    return resolved


def llm_generate_prompt_patch(
    *,
    prompt_layers: dict[str, Any],
    signals: dict[str, Any],
    compile_metrics: dict[str, Any],
    offline_report: dict[str, Any],
    optimizer_config: OptimizerConfig,
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    try:
        model = create_chat_model(
            name=optimizer_config.model_name,
            thinking_enabled=optimizer_config.thinking_enabled,
            temperature=optimizer_config.temperature,
        )
        response = model.invoke(
            [
                HumanMessage(
                    content=_structured_patch_prompt(
                        signals=signals,
                        prompt_layers=prompt_layers,
                        offline_report=offline_report,
                        compile_metrics=compile_metrics,
                        optimizer_config=optimizer_config,
                    )
                )
            ]
        )
        payload = _extract_json_payload(str(response.content or ""))
        resolved_model_name = getattr(model, "model", None) or optimizer_config.model_name
        return payload, [], resolved_model_name
    except Exception as exc:
        return None, [f"llm_generation_failed: {exc}"], optimizer_config.model_name


def _apply_signal_updates(prompt_layers: dict[str, Any], signals: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = _build_rule_patch_plan(prompt_layers, signals)
    return _apply_structured_patch_plan(prompt_layers, plan, optimizer_mode="rules")


def run_prompt_optimizer(
    *,
    thread_id: str,
    compile_metrics_path: Path | None = None,
    offline_regression_report_path: Path | None = None,
    prompt_layers_path: Path | None = None,
    output_dir: Path | None = None,
    apply_prompt_patch: bool = False,
    run_offline_validation: bool = True,
    dataset_version: str = "optimizer-candidate",
    optimizer_config: OptimizerConfig | dict[str, Any] | None = None,
    optimizer_mode: str = "rules",
    llm_model_name: str | None = None,
    llm_thinking_enabled: bool = False,
    llm_temperature: float = 0.0,
) -> dict[str, Any]:
    """Generate prompt-layer update candidates from runtime metrics and eval trends."""
    resolved_optimizer_config = _resolve_optimizer_config(
        optimizer_config=optimizer_config,
        optimizer_mode=optimizer_mode,
        llm_model_name=llm_model_name,
        llm_thinking_enabled=llm_thinking_enabled,
        llm_temperature=llm_temperature,
    )

    root = _project_root()
    resolved_prompt_layers = (
        prompt_layers_path
        if isinstance(prompt_layers_path, Path)
        else root / "backend/src/research_writing/prompt_assets/prompt_layers.yaml"
    )
    resolved_compile_metrics = (
        compile_metrics_path
        if isinstance(compile_metrics_path, Path)
        else root / "backend/.deer-flow/threads" / thread_id / "user-data" / "outputs" / "research-writing" / "metrics" / "compile-gates.json"
    )
    resolved_offline_report = (
        offline_regression_report_path
        if isinstance(offline_regression_report_path, Path)
        else root / "backend/src/evals/academic/datasets/offline_regression/offline-benchmark-regression.json"
    )
    resolved_output_dir = (
        output_dir
        if isinstance(output_dir, Path)
        else root / "backend/.deer-flow/threads" / thread_id / "user-data" / "outputs" / "research-writing" / "prompt-optimizer"
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    compile_metrics = _safe_load_json(resolved_compile_metrics)
    offline_report = _safe_load_json(resolved_offline_report)
    prompt_layers = _safe_load_yaml(resolved_prompt_layers)
    if not prompt_layers:
        raise ValueError(f"Prompt layers asset is missing or invalid: {resolved_prompt_layers}")

    signals = _collect_optimizer_signals(
        compile_metrics=compile_metrics,
        offline_report=offline_report,
    )

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    optimizer_mode_used = "rules"
    fallback_reason: str | None = None
    validation_issues: list[str] = []
    llm_candidate_payload: dict[str, Any] | None = None
    candidate_patch_plan_path: Path | None = None

    if not resolved_optimizer_config.enabled:
        updated_layers = json.loads(json.dumps(prompt_layers))
        changes: list[dict[str, Any]] = []
    elif resolved_optimizer_config.optimizer_mode == "llm_structured_patch":
        raw_plan, llm_errors, resolved_model_name = llm_generate_prompt_patch(
            prompt_layers=prompt_layers,
            signals=signals,
            compile_metrics=compile_metrics,
            offline_report=offline_report,
            optimizer_config=resolved_optimizer_config,
        )
        validation_issues.extend(llm_errors)
        if raw_plan is not None:
            llm_candidate_payload = dict(raw_plan)
            if resolved_model_name:
                llm_candidate_payload["llm_model_name"] = resolved_model_name
            plan, candidates, plan_issues = _validate_structured_patch_plan(
                plan_payload=raw_plan,
                prompt_layers=prompt_layers,
            )
            validation_issues.extend(plan_issues)
            candidate_patch_plan_path = resolved_output_dir / f"prompt_patch_plan.candidate.{ts}.json"
            _safe_dump_json(
                candidate_patch_plan_path,
                {
                    "schema_version": PROMPT_OPTIMIZER_SCHEMA_VERSION,
                    "thread_id": thread_id,
                    "generated_at": _now_iso(),
                    "optimizer_mode_requested": resolved_optimizer_config.optimizer_mode,
                    "optimizer_config": resolved_optimizer_config.model_dump(),
                    "llm_model_name": resolved_model_name,
                    "validation_issues": validation_issues,
                    "plan": llm_candidate_payload,
                },
            )
            if plan is not None and candidates is not None:
                updated_layers, changes = _apply_structured_patch_plan(prompt_layers, candidates, optimizer_mode="llm_structured_patch")
                optimizer_mode_used = "llm_structured_patch"
            elif resolved_optimizer_config.fallback_to_rules:
                updated_layers, changes = _apply_signal_updates(prompt_layers, signals)
                fallback_reason = "llm_structured_patch_validation_failed"
            else:
                updated_layers = json.loads(json.dumps(prompt_layers))
                changes = []
                fallback_reason = "llm_structured_patch_validation_failed"
        else:
            if resolved_optimizer_config.fallback_to_rules:
                updated_layers, changes = _apply_signal_updates(prompt_layers, signals)
                fallback_reason = "llm_structured_patch_generation_failed"
            else:
                updated_layers = json.loads(json.dumps(prompt_layers))
                changes = []
                fallback_reason = "llm_structured_patch_generation_failed"
    else:
        updated_layers, changes = _apply_signal_updates(prompt_layers, signals)

    candidate_path = resolved_output_dir / f"prompt_layers.candidate.{ts}.yaml"
    _safe_dump_yaml(candidate_path, updated_layers)

    applied = False
    applied_path: Path | None = None
    if apply_prompt_patch and changes:
        _safe_dump_yaml(resolved_prompt_layers, updated_layers)
        applied = True
        applied_path = resolved_prompt_layers

    validation_payload: dict[str, Any] | None = None
    if run_offline_validation:
        try:
            from src.evals.academic.offline_regression import (
                evaluate_offline_regression_layers,
                load_offline_layer_payloads,
            )

            suite_dir = root / "backend/src/evals/academic/templates/offline_benchmark_suite"
            layers = load_offline_layer_payloads(suite_dir)
            validation_payload = evaluate_offline_regression_layers(layers, dataset_version=dataset_version)
        except Exception as exc:
            validation_payload = {
                "status": "error",
                "error": str(exc),
            }

    status = "no_change"
    if changes:
        status = "candidate_generated"
    if applied:
        status = "applied"
    if isinstance(validation_payload, dict) and validation_payload.get("status") == "fail":
        status = "candidate_failed_validation"

    return {
        "schema_version": PROMPT_OPTIMIZER_SCHEMA_VERSION,
        "thread_id": thread_id,
        "generated_at": _now_iso(),
        "status": status,
        "optimizer_config": resolved_optimizer_config.model_dump(),
        "optimizer_mode_requested": resolved_optimizer_config.optimizer_mode,
        "optimizer_mode_used": optimizer_mode_used,
        "fallback_reason": fallback_reason,
        "signals": signals,
        "changes": changes,
        "change_count": len(changes),
        "candidate_prompt_layers_path": str(candidate_path),
        "candidate_prompt_patch_path": str(candidate_patch_plan_path) if candidate_patch_plan_path else None,
        "applied_prompt_patch": applied,
        "applied_prompt_layers_path": str(applied_path) if applied_path else None,
        "source_paths": {
            "compile_metrics_path": str(resolved_compile_metrics),
            "offline_regression_report_path": str(resolved_offline_report),
            "prompt_layers_path": str(resolved_prompt_layers),
        },
        "llm_candidate": llm_candidate_payload,
        "validation_issues": validation_issues,
        "offline_validation": validation_payload,
    }
