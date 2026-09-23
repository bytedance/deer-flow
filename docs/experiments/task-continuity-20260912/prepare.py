from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from common import ENC, PROTOCOL, ROOT, digest, tokens, write_json


def render_record(record: dict) -> str:
    return f"[{record['id']}] SESSION {record['session_id']} AT {record['date']} ROLE {record['role']}\n{record['content']}"


def render_history(records: list[dict]) -> str:
    return "\n\n".join(render_record(r) for r in records)


def record_chunks(records: list[dict], size: int = 384, overlap: int = 64) -> list[dict]:
    chunks = []
    for record in records:
        ids = ENC.encode(record["content"], disallowed_special=())
        for start in range(0, max(1, len(ids)), size - overlap):
            body = ENC.decode(ids[start:start + size])
            if not body.strip():
                continue
            chunks.append({"id": f"{record['id']}-c{start}", "record_id": record["id"],
                           "session_id": record["session_id"], "date": record["date"],
                           "role": record["role"], "text": body,
                           "rendered": f"[{record['id']}-c{start}] SESSION {record['session_id']} AT {record['date']} ROLE {record['role']}\n{body}"})
            if start + size >= len(ids):
                break
    return chunks


def history_batches(records: list[dict], budget: int) -> list[str]:
    batches, current, used = [], [], 0
    for record in records:
        text = render_record(record)
        parts = [text]
        if tokens(text) > budget:
            chunks = record_chunks([record], size=budget - 100, overlap=0)
            parts = [c["rendered"] for c in chunks]
        for part in parts:
            n = tokens(part) + 2
            if current and used + n > budget:
                batches.append("\n\n".join(current))
                current, used = [], 0
            current.append(part)
            used += n
    if current:
        batches.append("\n\n".join(current))
    return batches


def prepare_public() -> dict:
    path = ROOT / "data" / PROTOCOL["dataset_file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != PROTOCOL["dataset_sha256"]:
        raise ValueError("Pinned dataset hash mismatch")
    data = json.loads(path.read_text())
    groups = collections.defaultdict(list)
    for row in data:
        group = "abstention" if row["question_id"].endswith("_abs") else row["question_type"]
        groups[group].append(row)
    manifest = {"protocol_hash": digest(PROTOCOL), "dev": [], "test": [], "stratum_counts": {k: len(v) for k, v in groups.items()}}
    for group in PROTOCOL["strata"]:
        candidates = sorted(groups[group], key=lambda row: hashlib.sha256(f"20260912:{row['question_id']}".encode()).hexdigest())
        for i, row in enumerate(candidates[:1 + PROTOCOL["public_test_per_stratum"]]):
            split = "dev" if i == 0 else "test"
            records, evidence_records = [], []
            for sid, date, session in zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"], strict=True):
                for message in session:
                    record = {"id": f"r{len(records):05d}", "session_id": str(sid), "date": date,
                              "role": message["role"], "content": message["content"]}
                    records.append(record)
                    if message.get("has_answer"):
                        evidence_records.append(record["id"])
            public = {"id": row["question_id"], "split": split, "stratum": group,
                      "records": records, "question": row["question"], "question_date": row["question_date"]}
            gold = {"id": row["question_id"], "answer": row["answer"],
                    "evidence_sessions": row["answer_session_ids"], "evidence_records": evidence_records,
                    "abstention": group == "abstention"}
            write_json(ROOT / "cases" / "public" / f"{row['question_id']}.json", public)
            write_json(ROOT / "gold" / "public" / f"{row['question_id']}.json", gold)
            manifest[split].append({"id": row["question_id"], "stratum": group,
                                    "history_tokens": tokens(render_history(records)), "records": len(records),
                                    "history_hash": digest(records)})
    write_json(ROOT / "public-manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    m = prepare_public()
    print(json.dumps({"dev": len(m["dev"]), "test": len(m["test"]),
                      "test_history_tokens": sum(r["history_tokens"] for r in m["test"]),
                      "strata": m["stratum_counts"]}, ensure_ascii=False))
