"""Intent routing: map user questions to RAGFlow dataset_ids without user specifying KB."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_ROUTING_CONFIG = (
    Path(__file__).resolve().parents[1] / "config" / "routing.json"
)


from routing_utils import (
    discover_filter_files,
    load_skill_dotenv,
    parse_departments,
    resolve_filters_for_route,
    resolve_rerank_id,
    resolve_retrieval_settings,
    score_departments,
)

load_skill_dotenv()


class RouteIntentError(Exception):
    pass


@dataclass
class RouteDefinition:
    intent: str
    label: str
    dataset_id: str
    dataset_name: str
    description: str
    keywords: list[str]


@dataclass
class RouteScore:
    intent: str
    label: str
    score: int
    matched_keywords: list[str]


def load_routing_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_routes(config: dict[str, Any]) -> list[RouteDefinition]:
    routes: list[RouteDefinition] = []
    for item in config.get("routes", []):
        routes.append(
            RouteDefinition(
                intent=str(item.get("intent", "")).strip(),
                label=str(item.get("label", "")).strip(),
                dataset_id=str(item.get("dataset_id", "")).strip(),
                dataset_name=str(item.get("dataset_name", "")).strip(),
                description=str(item.get("description", "")).strip(),
                keywords=[str(k).strip() for k in item.get("keywords", []) if str(k).strip()],
            )
        )
    if not routes:
        raise RouteIntentError("routing config has no routes")
    return routes


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def score_question(question: str, routes: list[RouteDefinition]) -> list[RouteScore]:
    q = _normalize(question)
    scored: list[RouteScore] = []
    for route in routes:
        matched: list[str] = []
        score = 0
        for kw in route.keywords:
            if _normalize(kw) and _normalize(kw) in q:
                matched.append(kw)
                score += 1
        if route.intent and route.intent in question:
            matched.append(route.intent)
            score += 2
        scored.append(
            RouteScore(
                intent=route.intent,
                label=route.label,
                score=score,
                matched_keywords=matched,
            )
        )
    scored.sort(key=lambda x: (-x.score, x.intent))
    return scored


def pick_intent_from_scores(
    scores: list[RouteScore],
    *,
    min_score: int = 1,
    min_gap: int = 1,
) -> tuple[str | None, str | None]:
    """Return (intent, reason). intent is None when ambiguous."""
    if not scores:
        return None, "no_routes"
    top = scores[0]
    if top.score < min_score:
        return None, "low_score"
    if len(scores) < 2 or scores[1].score == 0:
        return top.intent, "clear_winner"
    gap = top.score - scores[1].score
    if gap >= min_gap:
        return top.intent, f"score_gap_{gap}"
    return None, "tie"


def auto_pick_intent(
    question: str,
    routes: list[RouteDefinition],
    *,
    min_score: int = 1,
    min_gap: int = 1,
) -> tuple[str | None, list[RouteScore], str | None]:
    scores = score_question(question, routes)
    intent, reason = pick_intent_from_scores(scores, min_score=min_score, min_gap=min_gap)
    return intent, scores, reason


def find_route(routes: list[RouteDefinition], intent: str) -> RouteDefinition:
    normalized = intent.strip()
    for route in routes:
        if route.intent == normalized:
            return route
    raise RouteIntentError(f"unknown intent: {intent!r}")


def resolve_dataset_id(
    route: RouteDefinition,
    *,
    resolve_names: bool = False,
    mock: bool = False,
    config: dict[str, Any] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    if route.dataset_id:
        return route.dataset_id
    if not resolve_names:
        raise RouteIntentError(
            f"intent {route.intent!r} has empty dataset_id; "
            f"fill config/routing.json or pass --resolve-names"
        )
    if mock:
        return f"kb-mock-{route.intent}"

    import ragflow_client as rc

    client = rc.RealRAGFlowClient(base_url=base_url, api_key=api_key, config=config)
    datasets = client.list_datasets(name=route.dataset_name or route.intent)
    if not datasets:
        datasets = client.list_datasets()
    needle = (route.dataset_name or route.intent).lower()
    for ds in datasets:
        if needle in ds.name.lower() or ds.name.lower() in needle:
            return ds.id
    raise RouteIntentError(
        f"no dataset matched intent {route.intent!r} "
        f"(dataset_name={route.dataset_name!r})"
    )


def _route_item(config: dict[str, Any], intent: str) -> dict[str, Any]:
    for item in config.get("routes", []):
        if str(item.get("intent", "")).strip() == intent.strip():
            return item
    raise RouteIntentError(f"unknown intent: {intent!r}")


def build_resolve_payload(
    *,
    question: str,
    intent: str,
    config: dict[str, Any],
    routes: list[RouteDefinition],
    resolve_names: bool = False,
    mock: bool = False,
    method: str = "agent",
    explicit_departments: list[str] | None = None,
    department_top_k: int | None = None,
    department_min_score: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    if intent.strip().lower() in {"ambiguous", "unknown", ""}:
        return {
            "ok": False,
            "intent": intent,
            "reason": "ambiguous_intent",
            "question": question,
        }

    route = find_route(routes, intent)
    route_item = _route_item(config, intent)
    dataset_id = resolve_dataset_id(
        route,
        resolve_names=resolve_names,
        mock=mock,
        config=config,
        base_url=base_url,
        api_key=api_key,
    )
    scores = score_question(question, routes)
    filters = resolve_filters_for_route(
        config,
        route_item,
        question=question,
        explicit_departments=explicit_departments,
        department_top_k=department_top_k,
        department_min_score=department_min_score,
    )
    rerank_id = resolve_rerank_id(config, route_item)
    retrieval = resolve_retrieval_settings(config, route_item)
    return {
        "ok": True,
        "intent": route.intent,
        "label": route.label,
        "dataset_id": dataset_id,
        "dataset_ids": [dataset_id],
        "dataset_name": route.dataset_name,
        "question": question,
        "method": method,
        "rerank_id": rerank_id,
        **retrieval,
        "filters": filters,
        "keyword_scores": [
            {
                "intent": s.intent,
                "label": s.label,
                "score": s.score,
                "matched_keywords": s.matched_keywords,
            }
            for s in scores
        ],
    }


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    print(text)


def _cmd_score(args: argparse.Namespace) -> int:
    config = load_routing_config(args.config)
    routes = parse_routes(config)
    scores = score_question(args.question, routes)
    top = scores[0] if scores else None
    payload = {
        "question": args.question,
        "top_intent": top.intent if top else None,
        "top_score": top.score if top else 0,
        "scores": [
            {
                "intent": s.intent,
                "label": s.label,
                "score": s.score,
                "matched_keywords": s.matched_keywords,
            }
            for s in scores
        ],
    }
    _write_json(args.out, payload)
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    config = load_routing_config(args.config)
    routes = parse_routes(config)
    explicit_departments = None
    if args.departments:
        explicit_departments = [part.strip() for part in args.departments.split(",") if part.strip()]
    payload = build_resolve_payload(
        question=args.question,
        intent=args.intent,
        config=config,
        routes=routes,
        resolve_names=args.resolve_names,
        mock=args.mock,
        method="agent" if args.intent else "keyword",
        explicit_departments=explicit_departments,
        department_top_k=args.department_top_k,
        department_min_score=args.department_min_score,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    if not payload.get("ok"):
        fallback = config.get("fallback", {})
        payload["fallback"] = fallback
    _write_json(args.out, payload)
    return 0 if payload.get("ok") else 1


def _cmd_score_departments(args: argparse.Namespace) -> int:
    config = load_routing_config(args.config)
    route_item = _route_item(config, args.intent)
    departments = parse_departments(route_item)
    scores = score_departments(args.question, departments)
    picked = scores[: max(1, args.top_k)] if scores else []
    payload = {
        "intent": args.intent,
        "question": args.question,
        "top_k": args.top_k,
        "min_score": args.min_score,
        "scores": [
            {
                "id": s.id,
                "label": s.label,
                "metadata_value": s.metadata_value,
                "score": s.score,
                "matched_keywords": s.matched_keywords,
            }
            for s in scores
        ],
        "selected": [
            {
                "id": s.id,
                "label": s.label,
                "metadata_value": s.metadata_value,
                "score": s.score,
            }
            for s in picked
            if s.score >= args.min_score
        ],
    }
    _write_json(args.out, payload)
    return 0


def _cmd_list_routes(args: argparse.Namespace) -> int:
    config = load_routing_config(args.config)
    routes = parse_routes(config)
    payload = {
        "routes": [
            {
                "intent": r.intent,
                "label": r.label,
                "dataset_id": r.dataset_id,
                "dataset_name": r.dataset_name,
                "description": r.description,
                "keyword_count": len(r.keywords),
            }
            for r in routes
        ]
    }
    _write_json(args.out, payload)
    return 0


def _cmd_list_filters(args: argparse.Namespace) -> int:
    payload = {"filters": discover_filter_files()}
    _write_json(args.out, payload)
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    """One-shot: auto intent → resolve → RAGFlow retrieval (fast path)."""
    import ragflow_client as rc

    config = load_routing_config(args.config)
    routes = parse_routes(config)
    scores = score_question(args.question, routes)

    intent = args.intent.strip() if args.intent else None
    auto_reason: str | None = None
    if not intent:
        if args.no_auto_intent:
            payload = {
                "ok": False,
                "reason": "missing_intent",
                "question": args.question,
                "keyword_scores": [
                    {
                        "intent": s.intent,
                        "label": s.label,
                        "score": s.score,
                        "matched_keywords": s.matched_keywords,
                    }
                    for s in scores
                ],
            }
            fallback = config.get("fallback", {})
            payload["fallback"] = fallback
            _write_json(args.out, payload)
            return 1
        intent, _, auto_reason = auto_pick_intent(
            args.question,
            routes,
            min_score=args.min_intent_score,
            min_gap=args.min_intent_gap,
        )
        if not intent:
            payload = {
                "ok": False,
                "reason": "ambiguous_intent",
                "auto_reason": auto_reason,
                "question": args.question,
                "keyword_scores": [
                    {
                        "intent": s.intent,
                        "label": s.label,
                        "score": s.score,
                        "matched_keywords": s.matched_keywords,
                    }
                    for s in scores
                ],
            }
            fallback = config.get("fallback", {})
            payload["fallback"] = fallback
            _write_json(args.out, payload)
            return 1

    explicit_departments = None
    if args.departments:
        explicit_departments = [part.strip() for part in args.departments.split(",") if part.strip()]

    route_payload = build_resolve_payload(
        question=args.question,
        intent=intent,
        config=config,
        routes=routes,
        resolve_names=args.resolve_names,
        mock=args.mock,
        method="auto" if auto_reason else "agent",
        explicit_departments=explicit_departments,
        department_top_k=args.department_top_k,
        department_min_score=args.department_min_score,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    if not route_payload.get("ok"):
        fallback = config.get("fallback", {})
        route_payload["fallback"] = fallback
        _write_json(args.out, route_payload)
        return 1

    route_payload["auto_intent_reason"] = auto_reason
    route_payload["keyword_scores"] = [
        {
            "intent": s.intent,
            "label": s.label,
            "score": s.score,
            "matched_keywords": s.matched_keywords,
        }
        for s in scores
    ]

    route_out = args.route_out
    if not route_out and args.out:
        route_out = str(Path(args.out).with_name("route.json"))
    if route_out:
        Path(route_out).write_text(
            json.dumps(route_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    retrieval_out = args.retrieval_out
    if not retrieval_out and args.out:
        retrieval_out = str(Path(args.out).with_name("query.retrieval.json"))

    try:
        retrieval_payload = rc.execute_run(
            route_payload,
            question=args.question,
            mock=args.mock,
            mock_fixture=args.mock_fixture,
            base_url=args.base_url,
            api_key=args.api_key,
            recall_top_k=args.recall_top_k if args.recall_top_k is not None else args.top_k,
            page_size=args.page_size,
            similarity_threshold=args.similarity_threshold,
            rerank_id=args.rerank_id or route_payload.get("rerank_id"),
            max_citations=args.max_citations,
            citation_content_chars=args.citation_content_chars,
            write_citation_sidecars=not args.no_citation_files,
            json_out=retrieval_out,
        )
    except rc.RAGFlowError as exc:
        err = {"ok": False, "reason": "retrieval_failed", "message": str(exc), "route": route_payload}
        _write_json(args.out, err)
        return 1

    if retrieval_out:
        Path(retrieval_out).write_text(
            json.dumps(retrieval_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.quiet:
        summary = rc.build_run_summary(retrieval_payload)
        summary["route_path"] = route_out
        summary["retrieval_path"] = retrieval_out
        summary["auto_intent_reason"] = auto_reason
        _write_json(args.out, summary)
    else:
        combined = {
            "ok": True,
            "route": route_payload,
            "retrieval": retrieval_payload,
        }
        _write_json(args.out, combined)

    return 0


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=str(DEFAULT_ROUTING_CONFIG),
        help="Path to routing.json",
    )
    parser.add_argument("--mock", action="store_true", help="Use mock dataset ids")
    parser.add_argument("--out", help="Write JSON output to this path")


def _add_ragflow_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mock-fixture", help="Mock retrieval fixture JSON path")
    parser.add_argument("--base-url", help="Override RAGFLOW_BASE_URL")
    parser.add_argument("--api-key", help="Override RAGFLOW_API_KEY")
    parser.add_argument(
        "--recall-top-k",
        type=int,
        default=None,
        help="Vector recall pool before rerank (default: routing.json recall_top_k=64)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Alias for --recall-top-k",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Final chunks after rerank (default: routing.json page_size=10)",
    )
    parser.add_argument("--similarity-threshold", type=float, default=None)
    parser.add_argument("--rerank-id", help="Override rerank model ID from routing.json")
    parser.add_argument(
        "--max-citations",
        type=int,
        default=None,
        help="Max citation items (default: routing.json max_citations or page_size)",
    )
    parser.add_argument("--citation-content-chars", type=int, default=800)
    parser.add_argument(
        "--no-citation-files",
        action="store_true",
        help="Do not write *.citations.json / *.citations.md sidecars",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Route questions to RAGFlow datasets by intent")
    _add_global_args(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="Keyword-based intent scoring (hint for agent)")
    _add_global_args(p_score)
    p_score.add_argument("--question", required=True)
    p_score.set_defaults(func=_cmd_score)

    p_resolve = sub.add_parser("resolve", help="Resolve intent to dataset_id")
    _add_global_args(p_resolve)
    p_resolve.add_argument("--intent", required=True, help="信贷 | 制度 | ambiguous")
    p_resolve.add_argument("--question", default="", help="Original user question")
    p_resolve.add_argument(
        "--resolve-names",
        action="store_true",
        help="Look up dataset_id from RAGFlow by dataset_name when dataset_id is empty",
    )
    p_resolve.add_argument(
        "--departments",
        help="Comma-separated department ids/labels chosen by agent, e.g. 零售,对公,风控",
    )
    p_resolve.add_argument(
        "--department-top-k",
        type=int,
        default=None,
        help="Auto-pick top-k departments by keyword score when --departments omitted",
    )
    p_resolve.add_argument(
        "--department-min-score",
        type=int,
        default=None,
        help="Minimum keyword score for a department to be included",
    )
    p_resolve.set_defaults(func=_cmd_resolve)

    p_score_departments = sub.add_parser(
        "score-departments",
        help="Rank departments for an intent (hint for agent)",
    )
    _add_global_args(p_score_departments)
    p_score_departments.add_argument("--intent", required=True)
    p_score_departments.add_argument("--question", required=True)
    p_score_departments.add_argument("--top-k", type=int, default=3)
    p_score_departments.add_argument("--min-score", type=int, default=1)
    p_score_departments.set_defaults(func=_cmd_score_departments)

    p_list = sub.add_parser("list-routes", help="Show configured intent routes")
    _add_global_args(p_list)
    p_list.set_defaults(func=_cmd_list_routes)

    p_filters = sub.add_parser("list-filters", help="Discover metadata filter JSON files")
    _add_global_args(p_filters)
    p_filters.set_defaults(func=_cmd_list_filters)

    p_query = sub.add_parser(
        "query",
        help="One-shot: auto intent + resolve + RAGFlow retrieval (fast path)",
    )
    _add_global_args(p_query)
    _add_ragflow_args(p_query)
    p_query.add_argument("--question", required=True)
    p_query.add_argument(
        "--intent",
        help="Override auto intent (信贷 | 制度); omit to auto-detect from keywords",
    )
    p_query.add_argument(
        "--no-auto-intent",
        action="store_true",
        help="Require --intent; do not auto-detect",
    )
    p_query.add_argument(
        "--min-intent-score",
        type=int,
        default=1,
        help="Minimum keyword score for auto intent",
    )
    p_query.add_argument(
        "--min-intent-gap",
        type=int,
        default=1,
        help="Minimum score gap between top-1 and top-2 intents",
    )
    p_query.add_argument(
        "--resolve-names",
        action="store_true",
        help="Look up dataset_id from RAGFlow when routing.json dataset_id is empty",
    )
    p_query.add_argument(
        "--departments",
        help="Comma-separated department ids/labels (omit for keyword top-k)",
    )
    p_query.add_argument(
        "--department-top-k",
        type=int,
        default=3,
        help="Auto-pick top-k departments when --departments omitted",
    )
    p_query.add_argument(
        "--department-min-score",
        type=int,
        default=None,
        help="Minimum keyword score for department inclusion",
    )
    p_query.add_argument(
        "--route-out",
        help="Write intermediate route.json (default: same dir as --out with route.json name)",
    )
    p_query.add_argument(
        "--retrieval-out",
        help="Write full retrieval JSON (default: query.retrieval.json next to --out)",
    )
    p_query.add_argument(
        "--quiet",
        action="store_true",
        help="Write compact summary to --out (citations only, not full chunks)",
    )
    p_query.set_defaults(func=_cmd_query)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RouteIntentError as exc:
        print(json.dumps({"ok": False, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
