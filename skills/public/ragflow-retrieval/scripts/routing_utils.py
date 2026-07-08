"""Shared routing + metadata filter path resolution for ragflow-retrieval."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTING_CONFIG = SKILL_ROOT / "config" / "routing.json"
SKILL_ENV_FILE = SKILL_ROOT / ".env"
SANDBOX_SKILL_PREFIX = "/mnt/skills/public/ragflow-retrieval"


def to_sandbox_skill_path(rel_or_abs: str) -> str:
    if rel_or_abs.startswith("/"):
        return rel_or_abs
    return f"{SANDBOX_SKILL_PREFIX}/{rel_or_abs.lstrip('/')}"


def from_sandbox_skill_path(path: str) -> Path:
    if path.startswith(SANDBOX_SKILL_PREFIX + "/"):
        rel = path[len(SANDBOX_SKILL_PREFIX) + 1 :]
        return SKILL_ROOT / rel
    return Path(path)


def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def is_effective_filter(data: dict[str, Any] | None) -> bool:
    if data is None or not data:
        return False
    if data.get("conditions") == []:
        return False
    if data.get("manual") == []:
        return False
    if data.get("method") == "auto" and not data.get("semi_auto"):
        return True
    if data.get("method") in {"auto", "semi_auto", "manual"}:
        return True
    if data.get("conditions"):
        return True
    if data.get("manual"):
        return True
    return False


def is_effective_filter_file(path: Path) -> bool:
    return is_effective_filter(load_json_file(path))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


@dataclass
class DepartmentDefinition:
    id: str
    label: str
    metadata_value: str
    keywords: list[str]


@dataclass
class DepartmentScore:
    id: str
    label: str
    metadata_value: str
    score: int
    matched_keywords: list[str]


def parse_departments(route_item: dict[str, Any]) -> list[DepartmentDefinition]:
    departments: list[DepartmentDefinition] = []
    for item in route_item.get("departments", []) or []:
        dept_id = str(item.get("id", "")).strip()
        label = str(item.get("label", dept_id)).strip()
        metadata_value = str(item.get("metadata_value") or label).strip()
        keywords = [str(k).strip() for k in item.get("keywords", []) if str(k).strip()]
        if dept_id:
            departments.append(
                DepartmentDefinition(
                    id=dept_id,
                    label=label,
                    metadata_value=metadata_value,
                    keywords=keywords,
                )
            )
    return departments


def score_departments(
    question: str,
    departments: list[DepartmentDefinition],
) -> list[DepartmentScore]:
    q = _normalize(question)
    scored: list[DepartmentScore] = []
    for dept in departments:
        matched: list[str] = []
        score = 0
        for kw in dept.keywords:
            if _normalize(kw) and _normalize(kw) in q:
                matched.append(kw)
                score += 1
        for token in (dept.id, dept.label, dept.metadata_value):
            if token and _normalize(token) in q:
                matched.append(token)
                score += 2
        scored.append(
            DepartmentScore(
                id=dept.id,
                label=dept.label,
                metadata_value=dept.metadata_value,
                score=score,
                matched_keywords=matched,
            )
        )
    scored.sort(key=lambda x: (-x.score, x.id))
    return scored


def select_top_departments(
    scores: list[DepartmentScore],
    *,
    top_k: int,
    min_score: int = 1,
) -> list[DepartmentScore]:
    positive = [s for s in scores if s.score >= min_score]
    if not positive:
        return []
    return positive[: max(1, top_k)]


def resolve_department_selection(
    route_item: dict[str, Any],
    config: dict[str, Any],
    question: str,
    *,
    explicit_departments: list[str] | None = None,
    department_top_k: int | None = None,
    department_min_score: int | None = None,
) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    enabled = bool(route_item.get("department_filter_enabled", False))
    departments = parse_departments(route_item)
    top_k = department_top_k if department_top_k is not None else int(
        route_item.get("department_top_k") or defaults.get("department_top_k", 3)
    )
    min_score = department_min_score if department_min_score is not None else int(
        route_item.get("department_min_score") or defaults.get("department_min_score", 1)
    )
    metadata_field = str(
        route_item.get("department_metadata_field")
        or defaults.get("department_metadata_field", "部门")
    ).strip()

    result: dict[str, Any] = {
        "enabled": enabled,
        "metadata_field": metadata_field,
        "top_k": top_k,
        "min_score": min_score,
        "available_departments": [
            {
                "id": d.id,
                "label": d.label,
                "metadata_value": d.metadata_value,
            }
            for d in departments
        ],
        "selected_departments": [],
        "department_scores": [],
        "selection_method": None,
        "filter_applied": False,
    }

    if not enabled or not departments:
        result["selection_method"] = "disabled"
        return result

    if explicit_departments:
        lookup = {d.id: d for d in departments}
        lookup_label = {d.label: d for d in departments}
        lookup_value = {d.metadata_value: d for d in departments}
        selected: list[DepartmentDefinition] = []
        for raw in explicit_departments:
            token = raw.strip()
            dept = lookup.get(token) or lookup_label.get(token) or lookup_value.get(token)
            if dept and dept not in selected:
                selected.append(dept)
        if not selected:
            raise ValueError(f"unknown departments for intent: {explicit_departments}")
        result["selection_method"] = "explicit"
        result["selected_departments"] = [_dept_summary(d, method="explicit") for d in selected]
        result["filter_applied"] = True
        return result

    scores = score_departments(question, departments)
    result["department_scores"] = [
        {
            "id": s.id,
            "label": s.label,
            "metadata_value": s.metadata_value,
            "score": s.score,
            "matched_keywords": s.matched_keywords,
        }
        for s in scores
    ]
    picked = select_top_departments(scores, top_k=top_k, min_score=min_score)
    if not picked:
        result["selection_method"] = "none_matched"
        return result

    result["selection_method"] = "keyword_top_k"
    result["selected_departments"] = [
        _dept_summary(
            next(d for d in departments if d.id == s.id),
            method="keyword_top_k",
            score=s.score,
            matched_keywords=s.matched_keywords,
        )
        for s in picked
    ]
    result["filter_applied"] = True
    return result


def _dept_summary(
    dept: DepartmentDefinition,
    *,
    method: str,
    score: int | None = None,
    matched_keywords: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": dept.id,
        "label": dept.label,
        "metadata_value": dept.metadata_value,
        "method": method,
    }
    if score is not None:
        payload["score"] = score
    if matched_keywords is not None:
        payload["matched_keywords"] = matched_keywords
    return payload


def build_department_meta_data_filter(
    metadata_field: str,
    metadata_values: list[str],
) -> dict[str, Any]:
    values = [v for v in metadata_values if v]
    if not values:
        return {}
    if len(values) == 1:
        return {
            "method": "manual",
            "logic": "and",
            "manual": [{"key": metadata_field, "op": "=", "value": values[0]}],
        }
    return {
        "method": "manual",
        "logic": "and",
        "manual": [{"key": metadata_field, "op": "in", "value": values}],
    }


def build_department_metadata_condition(
    metadata_field: str,
    metadata_values: list[str],
) -> dict[str, Any]:
    values = [v for v in metadata_values if v]
    if not values:
        return {}
    if len(values) == 1:
        return {
            "logic": "and",
            "conditions": [
                {
                    "name": metadata_field,
                    "comparison_operator": "=",
                    "value": values[0],
                }
            ],
        }
    return {
        "logic": "and",
        "conditions": [
            {
                "name": metadata_field,
                "comparison_operator": "in",
                "value": values,
            }
        ],
    }


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from a .env file (no external deps)."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def load_routing_config(path: Path | str | None = None) -> dict[str, Any] | None:
    cfg_path = Path(path) if path else DEFAULT_ROUTING_CONFIG
    return load_json_file(cfg_path)


def load_skill_dotenv(path: Path | None = None) -> None:
    """Load skill .env into os.environ (does not override existing vars)."""
    env_path = path or SKILL_ENV_FILE
    for key, value in parse_env_file(env_path).items():
        if value and key not in os.environ:
            os.environ[key] = value


def resolve_ragflow_credentials(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Resolve RAGFlow URL/key: CLI > os.environ > skill .env file."""
    load_skill_dotenv()

    url = (
        (base_url or "").strip()
        or os.environ.get("RAGFLOW_BASE_URL", "").strip()
    )
    key = (
        (api_key or "").strip()
        or os.environ.get("RAGFLOW_API_KEY", "").strip()
    )
    return url, key


def compose_model_id(model_info: dict[str, Any]) -> str:
    """Build RAGFlow API model id from GET /models/default item."""
    name = str(model_info.get("model_name") or "").strip()
    provider = str(model_info.get("model_provider") or "").strip()
    instance = str(model_info.get("model_instance") or "").strip()
    if not name:
        return ""
    if provider and instance and instance not in ("", "default"):
        return f"{name}@{instance}@{provider}"
    if provider:
        return f"{name}@{provider}"
    return name


def resolve_rerank_id(config: dict[str, Any], route_item: dict[str, Any]) -> str | None:
    defaults = config.get("defaults", {})

    def _rerank_enabled(item: dict[str, Any]) -> bool:
        if "rerank_enabled" in item:
            return bool(item["rerank_enabled"])
        if "rerank_enabled" in defaults:
            return bool(defaults["rerank_enabled"])
        return True

    if not _rerank_enabled(route_item):
        return None

    raw = route_item.get("rerank_id")
    if raw is None:
        raw = defaults.get("rerank_id", "auto")
    value = str(raw).strip()
    if not value or value.lower() == "auto":
        return "auto"
    return value


RECALL_TOP_K_DEFAULT = 64
PAGE_SIZE_DEFAULT = 10


def resolve_retrieval_settings(config: dict[str, Any], route_item: dict[str, Any]) -> dict[str, Any]:
    """Resolve recall vs return limits from routing.json (route overrides defaults)."""
    defaults = config.get("defaults", {})

    def _pick(key: str, fallback: int | float) -> int | float:
        val = route_item.get(key)
        if val is None:
            val = defaults.get(key)
        return val if val is not None else fallback

    page_size = int(_pick("page_size", PAGE_SIZE_DEFAULT))
    return {
        "recall_top_k": int(_pick("recall_top_k", RECALL_TOP_K_DEFAULT)),
        "page_size": page_size,
        "max_citations": int(_pick("max_citations", page_size)),
        "similarity_threshold": float(_pick("similarity_threshold", 0.2)),
    }


def resolve_run_retrieval_params(
    route: dict[str, Any],
    *,
    recall_top_k: int | None = None,
    page_size: int | None = None,
    max_citations: int | None = None,
    similarity_threshold: float | None = None,
) -> dict[str, Any]:
    """Merge CLI overrides with route.json retrieval fields."""
    resolved_page_size = (
        page_size if page_size is not None else int(route.get("page_size") or PAGE_SIZE_DEFAULT)
    )
    return {
        "recall_top_k": (
            recall_top_k if recall_top_k is not None else int(route.get("recall_top_k") or RECALL_TOP_K_DEFAULT)
        ),
        "page_size": resolved_page_size,
        "max_citations": (
            max_citations
            if max_citations is not None
            else int(route.get("max_citations") or resolved_page_size)
        ),
        "similarity_threshold": (
            similarity_threshold
            if similarity_threshold is not None
            else float(route.get("similarity_threshold") or 0.2)
        ),
    }


def resolve_filters_for_route(
    config: dict[str, Any],
    route_item: dict[str, Any],
    *,
    question: str = "",
    explicit_departments: list[str] | None = None,
    department_top_k: int | None = None,
    department_min_score: int | None = None,
    skill_root: Path = SKILL_ROOT,
) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    intent = str(route_item.get("intent", "")).strip()
    filters_dir = str(defaults.get("filters_dir", "config/filters")).strip()
    filter_mode = str(
        route_item.get("filter_mode") or defaults.get("filter_mode", "search")
    ).strip()

    mc_name = str(
        route_item.get("metadata_condition") or f"{intent}.metadata_condition.json"
    ).strip()
    mf_name = str(
        route_item.get("meta_data_filter") or f"{intent}.meta_data_filter.json"
    ).strip()

    mc_rel = f"{filters_dir}/{mc_name}"
    mf_rel = f"{filters_dir}/{mf_name}"
    mc_path = skill_root / mc_rel
    mf_path = skill_root / mf_rel

    department_selection = resolve_department_selection(
        route_item,
        config,
        question,
        explicit_departments=explicit_departments,
        department_top_k=department_top_k,
        department_min_score=department_min_score,
    )

    runtime_meta_data_filter: dict[str, Any] | None = None
    runtime_metadata_condition: dict[str, Any] | None = None
    if department_selection.get("filter_applied"):
        values = [
            str(item.get("metadata_value", "")).strip()
            for item in department_selection.get("selected_departments", [])
            if str(item.get("metadata_value", "")).strip()
        ]
        field = str(department_selection.get("metadata_field", "部门"))
        runtime_meta_data_filter = build_department_meta_data_filter(field, values)
        runtime_metadata_condition = build_department_metadata_condition(field, values)

    mc_file_data = load_json_file(mc_path)
    mf_file_data = load_json_file(mf_path)
    mc_file_enabled = is_effective_filter(mc_file_data)
    mf_file_enabled = is_effective_filter(mf_file_data)

    active_filter: dict[str, Any] | None = None
    active_type: str | None = None
    active_source: str | None = None
    mode = filter_mode

    if runtime_meta_data_filter and filter_mode == "search":
        active_filter = runtime_meta_data_filter
        active_type = "meta_data_filter"
        active_source = "runtime_department"
    elif runtime_metadata_condition and filter_mode == "retrieve":
        active_filter = runtime_metadata_condition
        active_type = "metadata_condition"
        active_source = "runtime_department"
    elif runtime_meta_data_filter:
        active_filter = runtime_meta_data_filter
        active_type = "meta_data_filter"
        active_source = "runtime_department"
        mode = "search"
    elif filter_mode == "search" and mf_file_enabled:
        active_filter = mf_file_data
        active_type = "meta_data_filter"
        active_source = "file"
    elif filter_mode == "retrieve" and mc_file_enabled:
        active_filter = mc_file_data
        active_type = "metadata_condition"
        active_source = "file"
    elif mf_file_enabled:
        active_filter = mf_file_data
        active_type = "meta_data_filter"
        active_source = "file"
        mode = "search"
    elif mc_file_enabled:
        active_filter = mc_file_data
        active_type = "metadata_condition"
        active_source = "file"
        mode = "retrieve"

    example_mc = skill_root / "example" / "metadata_condition.author.json"
    example_mf = skill_root / "example" / "meta_data_filter.manual.json"

    return {
        "mode": mode,
        "filters_dir": to_sandbox_skill_path(filters_dir),
        "metadata_condition_file": mc_name,
        "meta_data_filter_file": mf_name,
        "metadata_condition_path": to_sandbox_skill_path(mc_rel),
        "meta_data_filter_path": to_sandbox_skill_path(mf_rel),
        "metadata_condition_exists": mc_path.exists(),
        "meta_data_filter_exists": mf_path.exists(),
        "metadata_condition_enabled": mc_file_enabled,
        "meta_data_filter_enabled": mf_file_enabled,
        "department_selection": department_selection,
        "runtime_filter": active_filter if active_source == "runtime_department" else None,
        "active_filter": active_filter,
        "active_filter_path": to_sandbox_skill_path(
            mf_rel if active_type == "meta_data_filter" and active_source == "file" else mc_rel
        )
        if active_source == "file"
        else None,
        "active_filter_type": active_type,
        "active_filter_source": active_source,
        "filter_enabled": active_filter is not None,
        "fallback_examples": {
            "metadata_condition": to_sandbox_skill_path("example/metadata_condition.author.json"),
            "meta_data_filter": to_sandbox_skill_path("example/meta_data_filter.manual.json"),
            "metadata_condition_exists": example_mc.exists(),
            "meta_data_filter_exists": example_mf.exists(),
        },
    }


def discover_filter_files(*, skill_root: Path = SKILL_ROOT) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    scan_dirs = [
        ("config/filters", "intent-bound"),
        ("example", "example"),
    ]
    patterns = [
        "*.metadata_condition.json",
        "*.meta_data_filter.json",
        "metadata_condition*.json",
        "meta_data_filter*.json",
    ]
    seen: set[str] = set()
    for rel_dir, kind in scan_dirs:
        base = skill_root / rel_dir
        if not base.exists():
            continue
        for pattern in patterns:
            for path in sorted(base.glob(pattern)):
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                rel = path.relative_to(skill_root).as_posix()
                filter_type = (
                    "metadata_condition"
                    if "metadata_condition" in path.name
                    else "meta_data_filter"
                )
                discovered.append(
                    {
                        "kind": kind,
                        "filter_type": filter_type,
                        "filename": path.name,
                        "path": to_sandbox_skill_path(rel),
                        "enabled": is_effective_filter_file(path),
                    }
                )
    return discovered
