"""Inspection attachment summary — per-record photo / note aggregation.

Sprint S5 enhancement — consumes ``inspection_data.json`` and produces a
per-record attachment summary. Output length equals records length (so the
renderer can join with the anomaly table 1-to-1).

Each entry carries:
  - record_id / equipment / severity (echoed from the source record)
  - photo_count / note_count
  - photo_refs (compact list of attachment ids + paths)
  - note_snippet — first 200 chars of concatenated note summaries
"""

from __future__ import annotations

import sys
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    read_json,
    write_json,
)


SCHEMA_VERSION = "1"

SNIPPET_MAX = 200


def main() -> int:
    parser = base_parser("Per-record attachment summary")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    try:
        raw = read_json(Path(args.input))
    except (FileNotFoundError, ValueError) as exc:
        return emit_error("INPUT_UNREADABLE", str(exc))

    records = raw.get("records") or []
    attachments = raw.get("attachments") or []
    by_id = {att.get("id"): att for att in attachments if att.get("id")}

    attachment_summary: list[dict] = []
    total_photos = 0
    total_notes = 0
    for record in records:
        refs = record.get("attachment_refs") or []
        photos = [by_id[r] for r in refs if r in by_id and by_id[r].get("type") == "photo"]
        notes = [by_id[r] for r in refs if r in by_id and by_id[r].get("type") == "note"]
        total_photos += len(photos)
        total_notes += len(notes)
        joined_notes = "；".join(n.get("summary", "") for n in notes if n.get("summary"))
        attachment_summary.append(
            {
                "record_id": record["id"],
                "equipment": record.get("equipment"),
                "severity": record.get("severity"),
                "photo_count": len(photos),
                "note_count": len(notes),
                "photo_refs": [{"id": p["id"], "ref": p.get("ref", ""), "summary": p.get("summary", "")} for p in photos],
                "note_snippet": (joined_notes[:SNIPPET_MAX] + "…") if len(joined_notes) > SNIPPET_MAX else joined_notes,
            }
        )

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "inspection_date": raw.get("inspection_date"),
            "record_count": len(records),
            "attachment_count": len(attachments),
            "photo_count_total": total_photos,
            "note_count_total": total_notes,
        },
        "attachment_summary": attachment_summary,
        "_meta": {"stub": True, "generated_at": iso_now()},
    }
    write_json(Path(args.output_dir), "inspection_attachments", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
