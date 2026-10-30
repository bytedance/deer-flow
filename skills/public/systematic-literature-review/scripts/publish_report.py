#!/usr/bin/env python3
"""Copy an SLR draft to its output path only after checking its arXiv IDs against retrieval.

This checks citation membership and coverage, not scientific claims or author/title formatting.
It is a skill workflow check, not a runtime restriction on other file-writing tools.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from merge_extractions import merge

ID = r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z][a-z.-]*(?:\.[A-Z]{2})?/[0-9]{7})"
BARE_ID = re.compile(rf"(?<![\w./-])({ID})(?:v[0-9]+)?(?!\w)")
PAPER_URL = re.compile(r"https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf)/([^\s<>\]\)\}]+)", re.IGNORECASE)


def publish(papers: list[dict], batches: list[list[dict]], draft: str, output: Path) -> None:
    """Recheck original evidence and refuse unknown or omitted IDs before writing anything."""
    verified = merge(papers, batches)
    expected = {paper["arxiv_id"] for paper in verified}
    if not expected or any(re.fullmatch(ID, paper_id) is None for paper_id in expected):
        raise ValueError("a report requires retrieved papers with valid arXiv IDs")
    text = unquote(draft)
    found = set(BARE_ID.findall(text))
    for value in PAPER_URL.findall(text):
        value = value.split("?", 1)[0].split("#", 1)[0].removesuffix(".pdf").rstrip(".,;")
        match = re.fullmatch(rf"({ID})(?:v[0-9]+)?", value)
        if match is None:
            raise ValueError(f"invalid arXiv paper URL: {value}")
        found.add(match.group(1))
    if unknown := found - expected:
        raise ValueError(f"unretrieved report IDs: {', '.join(sorted(unknown))}")
    if missing := expected - found:
        raise ValueError(f"missing report IDs: {', '.join(sorted(missing))}")
    with output.open("x", encoding="utf-8") as destination:
        destination.write(draft)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers", type=Path, required=True, help="original papers.json from retrieval")
    parser.add_argument("--extractions", type=Path, nargs="+", required=True, help="original worker extraction files")
    parser.add_argument("--draft", type=Path, required=True, help="Markdown draft in the evidence workspace")
    parser.add_argument("--output", type=Path, required=True, help="new final Markdown output path")
    args = parser.parse_args()
    try:
        papers = json.loads(args.papers.read_text(encoding="utf-8-sig"))
        batches = [json.loads(path.read_text(encoding="utf-8-sig")) for path in args.extractions]
        publish(papers, batches, args.draft.read_text(encoding="utf-8-sig"), args.output)
    except (OSError, ValueError, KeyError) as exc:
        print(f"publish_report.py: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_path": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
