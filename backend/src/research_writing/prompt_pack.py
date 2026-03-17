"""Prompt-pack metadata + layered prompt registry for research-writing runtime."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_PROMPT_PACK_ID = "rw.superagent.v1.3"
PROMPT_PACK_ID_ENV_VAR = "DEER_FLOW_PROMPT_PACK_ID"
PROMPT_PACK_HASH_ENV_VAR = "DEER_FLOW_PROMPT_PACK_HASH"
PROMPT_LAYER_OVERRIDES_ENV_VAR = "DEER_FLOW_PROMPT_LAYER_OVERRIDES"
PROMPT_LAYER_SCHEMA_VERSION = "deerflow.prompt_layers.v1"
RUNTIME_STAGE_RECIPE_SCHEMA_VERSION = "deerflow.runtime_stage_recipe.v1"
STYLE_ADAPTER_SCHEMA_VERSION = "deerflow.venue_style_adapter.v1"

_PROMPT_PACK_FILES: tuple[str, ...] = (
    "skills/public/academic-superagent/SKILL.md",
    "skills/public/academic-superagent/prompt-pack.md",
    "skills/public/academic-superagent/evolution-playbook.md",
    "backend/src/research_writing/prompt_pack.py",
)

_PROMPT_LAYER_ORDER: tuple[str, ...] = ("L0", "L1", "L2", "L3", "L4", "L5")

_LAYER_BASELINES: dict[str, dict[str, str]] = {
    "L0": {
        "v0": (
            "Academic constitution (legacy): avoid explicit fabrication, but may summarize with implicit confidence.\n"
            "Fallback allowed when sources are thin."
        ),
        "v1": (
            "Academic constitution (strict):\n"
            "- Never fabricate data points, references, or experiment outcomes.\n"
            "- Evidence-first writing: prioritize verifiable artifacts over rhetoric.\n"
            "- If uncertainty exists, downgrade claim modality (suggest/may/possible).\n"
            "- Preserve negative findings and contradiction context; do not smooth conflicts away."
        ),
    },
    "L1": {
        "v0": (
            "Runtime protocol (legacy): produce useful text and optional references."
        ),
        "v1": (
            "Runtime protocol (strict contract):\n"
            "- Every compile/planning action must emit traceable artifacts.\n"
            "- Before writing prose, produce a Claim Map: claim_id -> data/citation bindings -> sentence draft.\n"
            "- Claims must carry binding markers where possible: [data:<id>] and [citation:<id>].\n"
            "- Outputs must be auditable through runtime metadata and artifact ledger.\n"
            "- Missing evidence must be surfaced as an actionable gap, not hidden."
        ),
    },
    "L2": {
        "v0": (
            "Stage recipe (legacy): ingest -> draft -> review."
        ),
        "v1": (
            "Stage recipe (standardized):\n"
            "ingest -> plan -> draft -> verify -> revise -> submit\n"
            "Canonical runtime mapping:\n"
            "- ingest: ingest_fulltext_evidence\n"
            "- plan: plan_project_section_narrative\n"
            "- draft: compile_project_section\n"
            "- verify: simulate_peer_review_cycle + claim grounding + compliance audit\n"
            "- revise: compile_project_section(auto_peer_review=true / policy-guided)\n"
            "- submit: build_latex_manuscript + evaluate_academic_and_persist"
        ),
    },
    "L3": {
        "v0": (
            "Role prompts (legacy): free-form writing/analysis guidance."
        ),
        "v1": (
            "Role prompts (handoff-contract first):\n"
            "- writer-agent: section narrative with calibrated claims and unresolved-gap bullets.\n"
            "- data-scientist: reproducible figure bundle (code + svg/pdf + provenance).\n"
            "- experiment-designer: quantitative protocol (power + controls + decision gates).\n"
            "- auditors: evidence-path audit with reproducibility steps and uncertainty labels."
        ),
    },
    "L4": {
        "v0": (
            "Venue style adapter (legacy): implicit prose rhythm imitation."
        ),
        "v1": (
            "Venue style adapter (parameterized):\n"
            "- Convert journal_style few-shot rhythm into explicit knobs.\n"
            "- Control knobs: claim_tone, evidence_density, max_templates, target_sentence_words, paragraph_sentence_target.\n"
            "- Keep style tuning reversible and comparable by versioned adapter metadata."
        ),
    },
    "L5": {
        "v0": (
            "Expert reasoning (legacy): output final answer only. Internal reasoning details are optional."
        ),
        "v1": (
            "Expert reasoning chain (required): Before any user-facing draft, run an internal <thinking> block and then generate output.\n"
            "- Counterfactual check: For each core claim, test the nearest counter-scenario and state what would falsify it.\n"
            "- Causal mechanism breakdown: Decompose key findings into mechanism chain (assumption -> mechanism -> observation -> uncertainty).\n"
            "- Confounder elimination: Explicitly list major confounders and mitigation or limits, or mark as unresolved if data is insufficient.\n"
            "- Do not skip this sequence for claim-sensitive sections and analytical conclusions."
        ),
    },
}

_LAYER_ROLLBACK_DEFAULT: dict[str, str] = {
    "L0": "v0",
    "L1": "v0",
    "L2": "v0",
    "L3": "v0",
    "L4": "v0",
    "L5": "v0",
}

_LAYER_DEFAULT_VERSION: dict[str, str] = {
    "L0": "v1",
    "L1": "v1",
    "L2": "v1",
    "L3": "v1",
    "L4": "v1",
    "L5": "v1",
}

_SUBAGENT_ROLE_HANDOFFS: dict[str, dict[str, str]] = {
    "bash": {
        "mission": "Execute delegated shell workflows safely, reproducibly, and with explicit command/result traceability.",
        "io_contract": (
            "Input: command objective + execution context/constraints.\n"
            "Output: executed command summary + success/failure status + relevant stdout/stderr + next-step notes."
        ),
        "workflow": (
            "1) Sequence dependent commands and parallelize only independent groups.\n"
            "2) Report critical outputs/errors faithfully without hiding failures.\n"
            "3) Flag destructive-risk commands and prefer safer alternatives when possible."
        ),
    },
    "general-purpose": {
        "mission": "Autonomously complete delegated multi-step tasks with traceable outputs and explicit uncertainty handling.",
        "io_contract": (
            "Input: delegated objective + context constraints + optional artifact paths.\n"
            "Output: concise accomplishment summary + key findings + artifact paths + unresolved risks/gaps."
        ),
        "workflow": (
            "1) Decompose into executable steps and track assumptions.\n"
            "2) Prefer verifiable actions over speculative answers.\n"
            "3) Expose blockers and evidence gaps explicitly instead of masking uncertainty."
        ),
    },
    "literature-reviewer": {
        "mission": "Synthesize reliable related-work evidence with verifiable identifiers and conservative interpretation.",
        "io_contract": (
            "Input: topic/query scope and optional seed papers.\n"
            "Output: evidence-backed synthesis + key-paper table + BibTeX/identifier set + research-gap bullets."
        ),
        "workflow": (
            "1) Query multiple sources and verify DOI/arXiv identifiers.\n"
            "2) Build support/contrast narrative from citation chains.\n"
            "3) Mark weak or missing evidence explicitly and avoid fabricated references."
        ),
    },
    "statistical-analyst": {
        "mission": "Deliver reproducible statistical analysis with diagnostics, effect sizes, and calibrated conclusions.",
        "io_contract": (
            "Input: datasets/analysis goals + variable assumptions.\n"
            "Output: data-quality audit + assumption diagnostics + test results (effect size + CI) + sensitivity checks."
        ),
        "workflow": (
            "1) Run quality and assumption diagnostics before inferential tests.\n"
            "2) Select robust/non-parametric alternatives when assumptions fail.\n"
            "3) Report limitations and avoid causal language for correlational evidence."
        ),
    },
    "code-reviewer": {
        "mission": "Audit research code for reproducibility, correctness, numerical stability, and test sufficiency.",
        "io_contract": (
            "Input: codebase scope and quality criteria.\n"
            "Output: severity-ranked findings + reproduction risk notes + concrete remediation suggestions."
        ),
        "workflow": (
            "1) Validate reproducibility first (seeds, pinned deps, rerun scripts).\n"
            "2) Check numerical stability and method-implementation alignment.\n"
            "3) Surface testing gaps and prioritize critical correctness risks."
        ),
    },
    "writer-agent": {
        "mission": "Convert structured evidence into publication-grade prose while calibrating claim strength conservatively.",
        "io_contract": (
            "Input: section context + evidence/citation IDs + hypothesis notes.\n"
            "Output: (1) Claim Map table first with strict columns "
            "(Claim ID | 核心主张 | 支撑 Data ID | 支撑 Citation ID | 局限性/Caveat), "
            "then (2) calibrated section text with [data:]/[citation:] binding and unresolved-gap action bullets."
        ),
        "workflow": (
            "1) Draft Claim Map rows before prose generation.\n"
            "2) Validate every Claim Map ID against available evidence/citation context; rewrite rows with unknown IDs.\n"
            "3) Convert Claim Map rows into claim-evidence-limitation-next-step sentences.\n"
            "4) Use [支持]/[反驳]/[调和] triad and mechanism-conflict writing in review/discussion sections.\n"
            "5) Downgrade certainty under missing/contradictory evidence.\n"
            "6) Keep provenance explicit and never fabricate statistics/citations."
        ),
    },
    "data-scientist": {
        "mission": "Produce reproducible publication-ready visual artifacts from audited analyses.",
        "io_contract": (
            "Input: analysis artifacts (analysis.json/csv) and optional narrative claims.\n"
            "Output: plotting script + svg/pdf + metadata/log + reproduction steps + fixed random seed + provenance hash + env requirements."
        ),
        "workflow": (
            "1) Prefer raw-data analysis artifacts as source of truth.\n"
            "2) Generate figures through generate_reproducible_figure.\n"
            "3) Include fixed random seed and explicit data provenance hash in outputs.\n"
            "4) Emit environment dependency requirements for rerun.\n"
            "5) Run cross-modal consistency checks before final claims."
        ),
    },
    "experiment-designer": {
        "mission": "Deliver quantitative experiment design with explicit decision criteria.",
        "io_contract": (
            "Input: objective/hypothesis assumptions.\n"
            "Output: power analysis + sample-size table + control/ablation matrix + go/no-go gates."
        ),
        "workflow": (
            "1) Define estimand and endpoint.\n"
            "2) Provide power assumptions and sensitivity ranges.\n"
            "3) Specify randomization/blinding, analysis plan, and risk mitigations."
        ),
    },
    "facs-auditor": {
        "mission": "Audit FACS figures with raw-data preference and conservative uncertainty labeling.",
        "io_contract": (
            "Input: FCS or ImageReport evidence artifacts.\n"
            "Output: audit summary + artifact citations + reproduction path + limitations."
        ),
        "workflow": (
            "1) Prefer analyze_fcs when raw files exist.\n"
            "2) Cross-check manuscript p-value/n statements against analyze_fcs outputs exactly.\n"
            "3) Verify ROI evidence supports the sentence-level claim.\n"
            "4) Treat image-only metrics as proxy.\n"
            "5) Report threshold sensitivity and unresolved ambiguity explicitly."
        ),
    },
    "blot-auditor": {
        "mission": "Audit Western blot conclusions against explicit lane/control evidence.",
        "io_contract": (
            "Input: ImageReport artifacts and optional densitometry CSV.\n"
            "Output: evidence-grounded audit with normalization caveats and reproducibility steps."
        ),
        "workflow": (
            "1) Use extract_image_evidence when evidence tables are missing.\n"
            "2) Prefer analyze_densitometry_csv when quant tables exist.\n"
            "3) Cross-check manuscript p-value/n statements against analyzed outputs exactly.\n"
            "4) Verify ROI evidence supports the sentence-level claim.\n"
            "5) Flag missing controls, saturation, and lane inconsistencies."
        ),
    },
    "tsne-auditor": {
        "mission": "Audit embedding-map claims with reproducible metric evidence.",
        "io_contract": (
            "Input: embedding CSV or image evidence artifacts.\n"
            "Output: cluster/batch separation audit with caveat-aware interpretation."
        ),
        "workflow": (
            "1) Prefer analyze_embedding_csv on raw coordinates.\n"
            "2) Cross-check manuscript p-value/n statements against analyzed outputs exactly.\n"
            "3) Verify ROI evidence supports the sentence-level claim.\n"
            "4) Mark image-only ROI analysis as qualitative proxy.\n"
            "5) Report confounding and visualization failure modes."
        ),
    },
    "spectrum-auditor": {
        "mission": "Audit spectrum claims with numeric peak evidence and calibration caveats.",
        "io_contract": (
            "Input: spectrum CSV or image evidence artifacts.\n"
            "Output: peak-consistency audit + artifact paths + reproducibility instructions."
        ),
        "workflow": (
            "1) Prefer analyze_spectrum_csv for numeric peaks/AUC.\n"
            "2) Compare numeric vs image-derived peaks when both exist.\n"
            "3) Cross-check manuscript p-value/n statements against analyzed outputs exactly.\n"
            "4) Verify ROI evidence supports the sentence-level claim.\n"
            "5) Never infer compound/element identities without calibration metadata."
        ),
    },
}


@dataclass(frozen=True)
class StageRecipeItem:
    stage: str
    operation: str
    runtime_api: str
    required_outputs: tuple[str, ...]


_STAGE_RECIPES: tuple[StageRecipeItem, ...] = (
    StageRecipeItem(
        stage="ingest",
        operation="collect_evidence",
        runtime_api="ingest_fulltext_evidence",
        required_outputs=("evidence_units", "citation_graph", "literature_graph"),
    ),
    StageRecipeItem(
        stage="plan",
        operation="plan_section_narrative",
        runtime_api="plan_project_section_narrative",
        required_outputs=("takeaway_message", "logical_flow", "self_questioning", "figure_storyboard"),
    ),
    StageRecipeItem(
        stage="draft",
        operation="compile_draft",
        runtime_api="compile_project_section",
        required_outputs=("compiled_text", "narrative_strategy", "issues"),
    ),
    StageRecipeItem(
        stage="verify",
        operation="run_verification",
        runtime_api="simulate_peer_review_cycle + claim_grounding + audit_compliance",
        required_outputs=("peer_review", "claim_grounding", "compliance_audit"),
    ),
    StageRecipeItem(
        stage="revise",
        operation="apply_revisions",
        runtime_api="compile_project_section(auto_peer_review=true)",
        required_outputs=("revised_text", "version_diff", "traceability"),
    ),
    StageRecipeItem(
        stage="submit",
        operation="build_submission_bundle",
        runtime_api="build_latex_manuscript + evaluate_academic_and_persist",
        required_outputs=("tex_or_pdf", "eval_summary", "artifact_ledger_records"),
    ),
)


def _project_root() -> Path:
    # backend/src/research_writing/prompt_pack.py -> project root
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _resolved_prompt_pack_files() -> tuple[Path, ...]:
    root = _project_root()
    files: list[Path] = []
    for relative_path in _PROMPT_PACK_FILES:
        candidate = root / relative_path
        if candidate.exists() and candidate.is_file():
            files.append(candidate)
    return tuple(files)


def _normalize_prompt_pack_id(value: str | None) -> str:
    normalized = (value or "").strip()
    return normalized or DEFAULT_PROMPT_PACK_ID


def _parse_layer_overrides() -> dict[str, Any]:
    raw = (os.getenv(PROMPT_LAYER_OVERRIDES_ENV_VAR) or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _layer_version_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _resolve_layer_active_version(layer_id: str, *, overrides: dict[str, Any]) -> str:
    versions = _LAYER_BASELINES.get(layer_id, {})
    fallback = _LAYER_DEFAULT_VERSION.get(layer_id, "v1")
    override_value = overrides.get(layer_id)
    if layer_id == "L3":
        # Allow coarse override for all role prompts with {"L3": "v0"}.
        if isinstance(override_value, str) and override_value in versions:
            return override_value
    if isinstance(override_value, str) and override_value in versions:
        return override_value
    return fallback if fallback in versions else (next(iter(versions.keys())) if versions else "v1")


def _build_prompt_layers_metadata() -> dict[str, Any]:
    overrides = _parse_layer_overrides()
    rows: list[dict[str, Any]] = []
    for layer_id in _PROMPT_LAYER_ORDER:
        versions = _LAYER_BASELINES.get(layer_id, {})
        if not versions:
            continue
        active_version = _resolve_layer_active_version(layer_id, overrides=overrides)
        rollback_version = _LAYER_ROLLBACK_DEFAULT.get(layer_id)
        if rollback_version not in versions:
            rollback_version = _LAYER_DEFAULT_VERSION.get(layer_id)
        if rollback_version not in versions:
            rollback_version = next(iter(versions.keys()))
        active_text = versions.get(active_version, "")
        baseline_text = versions.get(rollback_version, "")
        rows.append(
            {
                "layer_id": layer_id,
                "active_version": active_version,
                "default_version": _LAYER_DEFAULT_VERSION.get(layer_id, active_version),
                "rollback_version": rollback_version,
                "available_versions": list(versions.keys()),
                "active_signature": _layer_version_hash(active_text),
                "baseline_signature": _layer_version_hash(baseline_text),
                "compare_ready": active_version != rollback_version,
            }
        )
    return {
        "schema_version": PROMPT_LAYER_SCHEMA_VERSION,
        "layers": rows,
        "overrides_applied": overrides,
    }


def _build_prompt_layer_snapshot(*, role_name: str | None = None) -> dict[str, Any]:
    layer_metadata = _build_prompt_layers_metadata()
    rows = layer_metadata.get("layers")
    if not isinstance(rows, list):
        rows = []
    version_map: dict[str, str] = {}
    rollback_map: dict[str, str] = {}
    signature_map: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        layer_id = str(row.get("layer_id") or "").strip()
        if not layer_id:
            continue
        version_map[layer_id] = str(row.get("active_version") or "")
        rollback_map[layer_id] = str(row.get("rollback_version") or "")
        signature_map[layer_id] = str(row.get("active_signature") or "")
    payload: dict[str, Any] = {
        "schema_version": PROMPT_LAYER_SCHEMA_VERSION,
        "versions": version_map,
        "rollbacks": rollback_map,
        "signatures": signature_map,
        "compare_ready_layers": [layer_id for layer_id in version_map if version_map.get(layer_id) != rollback_map.get(layer_id)],
    }
    if role_name:
        role = _SUBAGENT_ROLE_HANDOFFS.get(role_name)
        if isinstance(role, dict) and role:
            payload["role_name"] = role_name
            payload["role_contract_version"] = _resolve_layer_active_version("L3", overrides=_parse_layer_overrides())
    return payload


def _build_prompt_layer_diff_summary(layer_snapshot: dict[str, Any]) -> dict[str, Any]:
    versions_raw = layer_snapshot.get("versions")
    rollbacks_raw = layer_snapshot.get("rollbacks")
    signatures_raw = layer_snapshot.get("signatures")
    compare_ready_layers_raw = layer_snapshot.get("compare_ready_layers")
    versions = versions_raw if isinstance(versions_raw, dict) else {}
    rollbacks = rollbacks_raw if isinstance(rollbacks_raw, dict) else {}
    signatures = signatures_raw if isinstance(signatures_raw, dict) else {}
    compare_ready_layers = set(compare_ready_layers_raw) if isinstance(compare_ready_layers_raw, list) else set()
    layer_ids = sorted({*versions.keys(), *rollbacks.keys()})
    layer_entries: list[dict[str, Any]] = []
    changed_layers: list[dict[str, Any]] = []
    for layer_id in layer_ids:
        active_version = str(versions.get(layer_id) or "").strip()
        rollback_version = str(rollbacks.get(layer_id) or "").strip()
        if not active_version and not rollback_version:
            continue
        active_signature = str(signatures.get(layer_id) or "").strip()
        rollback_signature = ""
        rollback_text = _LAYER_BASELINES.get(layer_id, {}).get(rollback_version, "")
        if rollback_text:
            rollback_signature = _layer_version_hash(rollback_text)
        compare_ready = layer_id in compare_ready_layers or active_version != rollback_version
        compare_ready_source = (
            "prompt_layer_compare_ready_layers"
            if layer_id in compare_ready_layers
            else "computed_active_vs_rollback"
        )
        changed = active_version != rollback_version
        entry = {
            "layer_id": layer_id,
            "active_version": active_version,
            "rollback_version": rollback_version,
            "active_signature": active_signature,
            "rollback_signature": rollback_signature,
            "compare_ready": compare_ready,
            "compare_ready_source": compare_ready_source,
            "changed": changed,
        }
        layer_entries.append(entry)
        if changed:
            changed_layers.append(entry)
    return {
        "total_layers": len(layer_ids),
        "changed_layer_count": len(changed_layers),
        "layer_entries": layer_entries,
        "changed_layers": changed_layers,
        "has_diff": len(changed_layers) > 0,
    }


def get_runtime_stage_recipe(*, stage: str | None = None) -> dict[str, Any]:
    rows = [
        {
            "stage": item.stage,
            "operation": item.operation,
            "runtime_api": item.runtime_api,
            "required_outputs": list(item.required_outputs),
        }
        for item in _STAGE_RECIPES
    ]
    if stage:
        selected = [row for row in rows if row["stage"] == stage]
    else:
        selected = rows
    return {
        "schema_version": RUNTIME_STAGE_RECIPE_SCHEMA_VERSION,
        "stages": selected,
    }


def build_style_adapter_profile(
    *,
    journal_style_bundle: dict[str, Any] | None,
    claim_tone: str,
    evidence_density: str,
    max_templates: int,
    runtime_writing_directives: list[str] | None = None,
) -> dict[str, Any]:
    active_adapter_version = _resolve_layer_active_version("L4", overrides=_parse_layer_overrides())
    summary = journal_style_bundle.get("style_summary") if isinstance(journal_style_bundle, dict) else {}
    writing_directives = journal_style_bundle.get("writing_directives") if isinstance(journal_style_bundle, dict) else []
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(writing_directives, list):
        writing_directives = []
    runtime_directives = runtime_writing_directives if isinstance(runtime_writing_directives, list) else []
    avg_sentence_words = summary.get("avg_sentence_words")
    if isinstance(avg_sentence_words, (int, float)) and avg_sentence_words > 0:
        if avg_sentence_words <= 18:
            rhythm_profile = "concise_dense"
            paragraph_sentence_target = "3-5"
        elif avg_sentence_words <= 25:
            rhythm_profile = "balanced"
            paragraph_sentence_target = "4-6"
        else:
            rhythm_profile = "long_form_argumentative"
            paragraph_sentence_target = "5-7"
    else:
        rhythm_profile = "balanced"
        paragraph_sentence_target = "4-6"

    merged_directives: list[str] = []
    seen_directives: set[str] = set()
    for row in [*runtime_directives, *writing_directives]:
        token = str(row or "").strip()
        if not token:
            continue
        key = token.lower()
        if key in seen_directives:
            continue
        seen_directives.add(key)
        merged_directives.append(token)
    merged_directives = merged_directives[:8]

    if merged_directives and isinstance(journal_style_bundle, dict):
        source = "journal_style_bundle+policy_snapshot"
    elif merged_directives:
        source = "policy_snapshot"
    elif isinstance(journal_style_bundle, dict):
        source = "journal_style_bundle"
    else:
        source = "runtime_default"
    return {
        "schema_version": STYLE_ADAPTER_SCHEMA_VERSION,
        "adapter_version": active_adapter_version,
        "source": source,
        "control_knobs": {
            "claim_tone": claim_tone,
            "evidence_density": evidence_density,
            "max_templates": max(1, int(max_templates)),
            "rhythm_profile": rhythm_profile,
            "target_sentence_words": float(avg_sentence_words) if isinstance(avg_sentence_words, (int, float)) else None,
            "paragraph_sentence_target": paragraph_sentence_target,
        },
        "writing_directives": merged_directives,
    }


def _active_layer_text(layer_id: str) -> str:
    overrides = _parse_layer_overrides()
    versions = _LAYER_BASELINES.get(layer_id, {})
    if not versions:
        return ""
    active_version = _resolve_layer_active_version(layer_id, overrides=overrides)
    return versions.get(active_version, "")


def _build_role_block(role_name: str) -> str:
    role = _SUBAGENT_ROLE_HANDOFFS.get(role_name, {})
    if not role:
        return "Role contract unavailable. Use conservative evidence-first behavior."
    return (
        f"Role mission: {role.get('mission', '').strip()}\n"
        f"I/O contract:\n{role.get('io_contract', '').strip()}\n"
        f"Workflow:\n{role.get('workflow', '').strip()}"
    ).strip()


def build_subagent_system_prompt(role_name: str) -> str:
    """Compose layered subagent prompt using L0-L5 contracts."""
    l0 = _active_layer_text("L0")
    l1 = _active_layer_text("L1")
    l2 = _active_layer_text("L2")
    l4 = _active_layer_text("L4")
    l5 = _active_layer_text("L5")
    role_block = _build_role_block(role_name)
    return (
        f"You are the '{role_name}' specialized academic subagent.\n\n"
        f"[L0 Constitution]\n{l0}\n\n"
        f"[L1 Runtime Protocol]\n{l1}\n\n"
        f"[L2 Stage Recipe]\n{l2}\n\n"
        f"[L3 Role Contract]\n{role_block}\n\n"
        f"[L4 Venue Style Adapter]\n{l4}\n\n"
        f"[L5 Expert Reasoning]\n{l5}\n\n"
        "Working directories:\n"
        "- uploads: `/mnt/user-data/uploads`\n"
        "- outputs: `/mnt/user-data/outputs`\n"
    ).strip()


def build_subagent_layered_prompt(role_name: str, *, base_prompt: str | None = None) -> str:
    """Compose role prompt as layered header + role-local base instructions."""
    layered_header = build_subagent_system_prompt(role_name)
    base = (base_prompt or "").strip()
    if not base:
        return layered_header
    return f"{layered_header}\n\n{base}"


@lru_cache(maxsize=1)
def _compute_prompt_pack_hash() -> str:
    hasher = hashlib.sha256()
    files = _resolved_prompt_pack_files()
    root = _project_root()
    if not files:
        hasher.update(DEFAULT_PROMPT_PACK_ID.encode("utf-8"))
        return hasher.hexdigest()[:16]

    for path in sorted(files):
        try:
            path_key = path.relative_to(root).as_posix()
        except ValueError:
            path_key = path.name
        hasher.update(path_key.encode("utf-8"))
        hasher.update(path.read_bytes())
    # Include active layer selection so A/B can be attributed even with same file hash.
    layer_meta = _build_prompt_layers_metadata()
    hasher.update(json.dumps(layer_meta, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return hasher.hexdigest()[:16]


def get_prompt_pack_metadata() -> dict[str, Any]:
    """Return prompt-pack metadata used for artifact traceability and layer comparison."""
    prompt_pack_id = _normalize_prompt_pack_id(os.getenv(PROMPT_PACK_ID_ENV_VAR))
    hash_override = (os.getenv(PROMPT_PACK_HASH_ENV_VAR) or "").strip()
    prompt_pack_hash = hash_override or _compute_prompt_pack_hash()
    hash_source = "env_override" if hash_override else "auto_computed"

    root = _project_root()
    source_files: list[str] = []
    for path in _resolved_prompt_pack_files():
        try:
            source_files.append(path.relative_to(root).as_posix())
        except ValueError:
            source_files.append(path.as_posix())

    layer_metadata = _build_prompt_layers_metadata()
    layer_snapshot = _build_prompt_layer_snapshot()
    layer_diff_summary = _build_prompt_layer_diff_summary(layer_snapshot)
    stage_recipe = get_runtime_stage_recipe()
    stage_rows = stage_recipe.get("stages")
    if not isinstance(stage_rows, list):
        stage_rows = []
    return {
        "prompt_pack_id": prompt_pack_id,
        "prompt_pack_hash": prompt_pack_hash,
        "prompt_pack_hash_source": hash_source,
        "prompt_pack_source_files": source_files,
        "prompt_layer_schema_version": layer_metadata["schema_version"],
        "prompt_layers": layer_metadata["layers"],
        "prompt_layer_overrides_applied": layer_metadata["overrides_applied"],
        "prompt_layer_versions": layer_snapshot.get("versions", {}),
        "prompt_layer_rollbacks": layer_snapshot.get("rollbacks", {}),
        "prompt_layer_signatures": layer_snapshot.get("signatures", {}),
        "prompt_layer_compare_ready_layers": layer_snapshot.get("compare_ready_layers", []),
        "prompt_layer_diff_summary": layer_diff_summary,
        "runtime_stage_recipe_schema_version": stage_recipe.get("schema_version"),
        "runtime_stage_recipe_stages": [str(item.get("stage") or "") for item in stage_rows if isinstance(item, dict)],
    }
