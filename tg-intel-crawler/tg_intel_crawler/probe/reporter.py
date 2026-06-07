"""Write probe results to disk: JSON dump + Markdown human report."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from tg_intel_crawler.probe.runner import ProbeRecord


_CLASSIFICATIONS = ["direct_hit", "indirect_hit", "no_results", "empty_reply", "error"]
_STRATA = ["L1", "L2", "L3", "L4", "L5", "L6"]
_STRATUM_DESC = {
    "L1": "公开 count=1",
    "L2": "公开 count 2-9",
    "L3": "公开 count ≥10",
    "L4": "私密 count=1",
    "L5": "私密 count 2-9",
    "L6": "私密 count ≥10",
}


class ProbeReporter:
    """Persist a probe run as JSON + Markdown.

    The JSON is the source of truth (parseable for follow-up analysis); the
    Markdown is what a human reads to decide next steps.
    """

    def __init__(
        self,
        *,
        dest_dir: Path | str,
        bot: str,
        sample_size: int,
        seed: int,
        candidate_pool_total: int,
        truncated: bool,
        generated_at: datetime,
    ):
        self._dest_dir = Path(dest_dir)
        self._meta = {
            "bot": bot,
            "sample_size": sample_size,
            "seed": seed,
            "candidate_pool_total": candidate_pool_total,
            "truncated": truncated,
            "generated_at": generated_at.isoformat(),
        }
        self._date_str = generated_at.date().isoformat()

    def write(self, records: list[ProbeRecord]) -> tuple[Path, Path]:
        self._dest_dir.mkdir(parents=True, exist_ok=True)
        json_path = self._dest_dir / f"bot_lookup_{self._date_str}.json"
        md_path = self._dest_dir / f"bot_lookup_{self._date_str}.md"
        json_path.write_text(self._render_json(records), encoding="utf-8")
        md_path.write_text(self._render_markdown(records), encoding="utf-8")
        return json_path, md_path

    # ----- JSON -----

    def _render_json(self, records: list[ProbeRecord]) -> str:
        payload = {
            "meta": self._meta,
            "records": [self._record_to_dict(r) for r in records],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _record_to_dict(r: ProbeRecord) -> dict:
        d = asdict(r)
        # asdict() handles SampledCandidate fine; nothing else needs massage.
        return d

    # ----- Markdown -----

    def _render_markdown(self, records: list[ProbeRecord]) -> str:
        lines: list[str] = []
        lines.append(f"# Bot Lookup Probe — {self._date_str}")
        lines.append("")
        lines.append(f"bot: {self._meta['bot']}")
        lines.append(
            f"sample: {len(records)} / {self._meta['candidate_pool_total']} "
            f"(seed={self._meta['seed']})"
        )
        if self._meta["truncated"]:
            lines.append("")
            lines.append("> ⚠️  **truncated** — throttle cap was hit before all samples ran.")
        lines.append("")
        lines.extend(self._overall_table(records))
        lines.append("")
        lines.extend(self._per_layer_table(records))
        lines.append("")
        lines.extend(self._examples(records))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _overall_table(records: list[ProbeRecord]) -> list[str]:
        # rows: classification → (public, private, total)
        rows: dict[str, list[int]] = {c: [0, 0, 0] for c in _CLASSIFICATIONS}
        for r in records:
            c = r.classification
            t = r.candidate.candidate_type
            rows[c][2] += 1
            if t == "public":
                rows[c][0] += 1
            else:
                rows[c][1] += 1

        out = [
            "## 命中分布",
            "| 分类           | 公开 | 私密 | 合计 |",
            "|----------------|------|------|------|",
        ]
        for c in _CLASSIFICATIONS:
            pub, priv, total = rows[c]
            out.append(f"| {c:<14} | {pub:>4} | {priv:>4} | {total:>4} |")
        return out

    @staticmethod
    def _per_layer_table(records: list[ProbeRecord]) -> list[str]:
        # rows: stratum → {classification: count, "n": int}
        per: dict[str, dict[str, int]] = {
            s: {c: 0 for c in _CLASSIFICATIONS} | {"n": 0}
            for s in _STRATA
        }
        for r in records:
            s = r.candidate.stratum
            per[s][r.classification] += 1
            per[s]["n"] += 1

        out = [
            "## 按层细分",
            "| 层 | 描述              | n | direct | indirect | none | empty | err |",
            "|----|-------------------|---|--------|----------|------|-------|-----|",
        ]
        for s in _STRATA:
            row = per[s]
            desc = _STRATUM_DESC[s]
            # Private strata never show direct_hit (key starts with +).
            direct_cell = (
                str(row["direct_hit"]) if s in ("L1", "L2", "L3") else "-"
            )
            out.append(
                f"| {s} | {desc:<17} | {row['n']:>1} | "
                f"{direct_cell:>6} | {row['indirect_hit']:>8} | "
                f"{row['no_results']:>4} | {row['empty_reply']:>5} | "
                f"{row['error']:>3} |"
            )
        return out

    @staticmethod
    def _examples(records: list[ProbeRecord]) -> list[str]:
        out = ["## 典型样本"]
        # One example per classification (first occurrence).
        for c in _CLASSIFICATIONS:
            ex = next((r for r in records if r.classification == c), None)
            if ex is None:
                continue  # skip section with no occurrence
            sc = ex.candidate
            out.append("")
            out.append(f"### {c} · {sc.key} ({sc.stratum}, count={sc.count})")
            out.append(f"query: `{ex.query_sent}`")
            if c == "direct_hit" and ex.matched_preview:
                out.append("matched preview:")
                out.append(f"> {ex.matched_preview.get('raw_line', '')}")
            elif c == "error":
                out.append(f"error: `{ex.error}`")
            elif c == "empty_reply":
                out.append("(empty reply)")
            elif c in ("indirect_hit", "no_results"):
                # Show a snippet of the reply.
                snippet = (ex.reply_raw or "").strip().splitlines()
                preview = snippet[0] if snippet else "(no content)"
                out.append(f"> {preview[:200]}")
        return out
