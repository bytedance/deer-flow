#!/usr/bin/env python3
"""Join subagent analysis to retrieved metadata, rejecting invented paper identities."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ANALYSIS_FIELDS = ("research_question", "methodology", "key_findings", "limitations")


def merge(papers: list[dict], batches: list[list[dict]]) -> list[dict]:
    """Require one extraction per retrieved paper and preserve authoritative metadata."""
    if not isinstance(papers, list) or any(not isinstance(paper, dict) for paper in papers):
        raise ValueError("papers must be an array of paper objects")
    by_id = {}
    for paper in papers:
        paper_id = paper.get("id")
        if not isinstance(paper_id, str) or not paper_id or paper_id in by_id:
            raise ValueError("retrieved papers must have unique, non-empty ids")
        title = paper.get("title")
        authors = paper.get("authors")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{paper_id}: missing retrieved title")
        if not isinstance(authors, list) or not authors or any(not isinstance(author, str) or not author.strip() for author in authors):
            raise ValueError(f"{paper_id}: missing retrieved authors")
        published = paper.get("published")
        try:
            valid_date = isinstance(published, str) and date.fromisoformat(published).isoformat() == published
        except ValueError:
            valid_date = False
        if not valid_date:
            raise ValueError(f"{paper_id}: invalid retrieved publication date")
        by_id[paper_id] = paper

    extracted = {}
    for batch in batches:
        if not isinstance(batch, list):
            raise ValueError("each extraction file must contain a JSON array")
        for item in batch:
            if not isinstance(item, dict):
                raise ValueError("each extraction must be a paper object")
            paper_id = item.get("arxiv_id")
            if not isinstance(paper_id, str) or paper_id not in by_id:
                raise ValueError(f"unretrieved arXiv id: {paper_id}")
            if paper_id in extracted:
                raise ValueError(f"duplicate extraction: {paper_id}")
            source = by_id[paper_id]
            metadata = {
                "arxiv_id": paper_id,
                "title": source["title"],
                "authors": source["authors"],
                "published_date": source["published"],
            }
            for field in ("categories", "abs_url", "pdf_url"):
                if field in source:
                    metadata[field] = source[field]
            for field, value in metadata.items():
                if field in item and item[field] != value:
                    raise ValueError(f"{paper_id}: {field} differs from retrieved metadata")
            for field in ANALYSIS_FIELDS:
                value = item.get(field)
                if field == "key_findings":
                    valid = isinstance(value, list) and bool(value) and all(isinstance(finding, str) and finding.strip() for finding in value)
                else:
                    valid = isinstance(value, str) and bool(value.strip())
                if not valid:
                    raise ValueError(f"{paper_id}: invalid or missing {field}")
            extracted[paper_id] = {**metadata, **{field: item[field] for field in ANALYSIS_FIELDS}}

    missing = by_id.keys() - extracted.keys()
    if missing:
        raise ValueError(f"missing extractions: {', '.join(sorted(missing))}")
    return [extracted[paper_id] for paper_id in by_id]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers", type=Path, required=True, help="papers.json written by arxiv_search.py")
    parser.add_argument("--extractions", type=Path, nargs="+", required=True, help="JSON arrays saved by the subagents")
    parser.add_argument("--output", type=Path, required=True, help="new verified extraction file")
    args = parser.parse_args()
    try:
        papers = json.loads(args.papers.read_text(encoding="utf-8-sig"))
        batches = [json.loads(path.read_text(encoding="utf-8-sig")) for path in args.extractions]
        result = merge(papers, batches)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except (OSError, ValueError, KeyError) as exc:
        print(f"merge_extractions.py: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"paper_count": len(result), "output_path": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
