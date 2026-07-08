#!/usr/bin/env python3
"""Search/list/get chart recipe .md files directly from disk.

All operations work against individual .md files in references/examples/.
No index file, no merge step — just read files on the fly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SCAN_DIR = "references/examples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]+|[一-鿿]+", value.lower())
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _chart_type(name: str) -> str:
    if "-" in name:
        return name.split("-", 1)[0]
    return ""


def _title(content: str, name: str) -> str:
    for line in content.splitlines()[:10]:
        s = line.strip()
        if s.startswith("#") and not s.startswith("##"):
            return s.lstrip("#").strip() or name
    return name


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_files(root: Path) -> list[Path]:
    base = root / SCAN_DIR
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*.md") if p.is_file() and p.name != "INDEX.md")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_assets(
    root: Path,
    query: str,
    *,
    chart_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    """Search .md files by tokenized query, return scored results."""
    terms = _tokenize(query)
    if not terms:
        return []

    files = _iter_files(root)
    qlower = query.lower()
    results: list[dict] = []

    for fp in files:
        rel = fp.relative_to(root).as_posix()
        name = fp.stem
        ct = _chart_type(name)
        if chart_type and ct != chart_type:
            continue

        name_lower = name.lower()
        ct_lower = ct.lower()

        # Quick filename check first
        if not any(t in name_lower or t in ct_lower for t in terms):
            text = fp.read_text(encoding="utf-8", errors="replace")
            head = "\n".join(text.splitlines()[:80])
            if not all(t in head.lower() for t in terms):
                continue
        else:
            text = fp.read_text(encoding="utf-8", errors="replace")
            head = "\n".join(text.splitlines()[:80])

        title_str = _title(text, name)
        score = 100
        if name_lower == qlower:
            score += 200
        if ct_lower == qlower:
            score += 80
        for term in terms:
            if term in name_lower:
                score += 60
            if term in title_str.lower():
                score += 40
            if term in head.lower():
                score += 8

        results.append({
            "path": rel,
            "name": name,
            "chart_type": ct,
            "title": title_str,
            "content_bytes": fp.stat().st_size,
            "score": score,
        })

    results.sort(key=lambda r: (-r["score"], r["content_bytes"], r["path"]))
    return results[:limit]


def get_asset(root: Path, name_or_path: str) -> dict[str, object]:
    """Read a recipe .md file from disk."""
    name = name_or_path
    if name.endswith(".md"):
        name = name[:-3]
    if "/" in name:
        name = name.rsplit("/", 1)[-1]

    file_path = root / SCAN_DIR / f"{name}.md"
    if not file_path.exists():
        raise FileNotFoundError(f"Recipe not found: {file_path}")

    content = file_path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": name,
        "chart_type": _chart_type(name),
        "title": _title(content, name),
        "content": content,
    }


def list_assets(
    root: Path,
    *,
    chart_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """List .md files, optionally filtered by chart type."""
    files = _iter_files(root)
    results: list[dict] = []
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        name = fp.stem
        ct = _chart_type(name)
        if chart_type and ct != chart_type:
            continue
        # Read just enough for title
        text = fp.read_text(encoding="utf-8", errors="replace")
        results.append({
            "path": rel,
            "name": name,
            "chart_type": ct,
            "title": _title(text, name),
        })
    results.sort(key=lambda r: (r.get("chart_type") or "", r["name"]))
    return results[:limit]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search/list/get chart recipe .md files")
    parser.add_argument("--root", default=str(default_root()), help="Project root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search chart recipes by keywords")
    search.add_argument("query")
    search.add_argument("--chart-type", help="Filter by chart type (bar/line/pie/...)")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true", help="Emit JSON")

    get = subparsers.add_parser("get", help="Print one recipe by name")
    get.add_argument("name", help="Chart name (e.g. line-simple)")
    get.add_argument("--json", action="store_true", help="Emit JSON")

    list_cmd = subparsers.add_parser("list", help="List chart recipes")
    list_cmd.add_argument("--chart-type", help="Filter by chart type")
    list_cmd.add_argument("--limit", type=int, default=50)
    list_cmd.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args(argv)


def emit_rows(rows: list[dict[str, object]], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for row in rows:
        score = f" score={row['score']}" if "score" in row else ""
        ct = f" type={row.get('chart_type')}" if row.get("chart_type") else ""
        print(f"{row.get('path', row.get('name', ''))}{ct}{score}")
        title = row.get("title")
        if title:
            print(f"  {title}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = Path(args.root).resolve()

    if args.command == "search":
        rows = search_assets(root, args.query, chart_type=args.chart_type, limit=args.limit)
        emit_rows(rows, as_json=args.json)
        return 0

    if args.command == "get":
        try:
            asset = get_asset(root, args.name)
            if args.json:
                print(json.dumps(asset, ensure_ascii=False, indent=2))
            else:
                print(asset["content"])
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "list":
        rows = list_assets(root, chart_type=args.chart_type, limit=args.limit)
        emit_rows(rows, as_json=args.json)
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
