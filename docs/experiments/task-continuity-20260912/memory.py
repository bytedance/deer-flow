from __future__ import annotations

import asyncio
import html
import json
import re

from common import PROTOCOL, ROOT, LiveClient, clip, digest, tokens, write_json
from prepare import history_batches, render_history

SUMMARY = (ROOT / "prompts" / "deerflow-default-summary.txt").read_text()
NOTES = (ROOT / "prompts" / "notes.txt").read_text()


async def build_memory(case: dict, client: LiveClient, *, forced_stages: list[list[dict]] | None = None) -> dict:
    cid = case["id"]
    records = case["records"]
    if forced_stages is None:
        # Preserve recent records separately, and compact only the old prefix.
        recent, count = [], 0
        for record in reversed(records):
            n = tokens(render_history([record]))
            if recent and count + n > PROTOCOL["recent_tail_tokens"]:
                break
            recent.insert(0, record)
            count += n
        old = records[:-len(recent)] if recent else records
        batches = history_batches(old, PROTOCOL["history_batch_tokens"])
        tail = clip(render_history(recent), PROTOCOL["recent_tail_tokens"], tail=True)
    else:
        stages_copy = [list(stage) for stage in forced_stages]
        recent, count = [], 0
        for record in reversed(stages_copy[-1]):
            n = tokens(render_history([record]))
            if recent and count + n > PROTOCOL["recent_tail_tokens"]:
                break
            recent.insert(0, record)
            count += n
        if recent:
            stages_copy[-1] = stages_copy[-1][:-len(recent)]
        batches = [render_history(stage) for stage in stages_copy]
        tail = clip(render_history(recent), PROTOCOL["recent_tail_tokens"], tail=True)
    signature = digest({"records": records, "batches": batches, "protocol": PROTOCOL,
                        "summary_prompt": SUMMARY, "notes_prompt": NOTES})
    dest = ROOT / "memory" / f"{cid}.json"
    previous_summary, previous_notes, stages = "", "", []
    if dest.exists():
        saved = json.loads(dest.read_text())
        if saved.get("signature") == signature:
            stages = saved["stages"]
            if stages:
                previous_summary = stages[-1]["summary"]
                previous_notes = stages[-1]["notes"]
            if len(stages) == len(batches):
                return saved
    for i, batch in enumerate(batches):
        if i < len(stages):
            continue
        wrapped = ""
        if previous_summary:
            wrapped += "<existing_summary>\n" + html.escape(previous_summary, quote=False) + "\n</existing_summary>\n"
        wrapped += "<new_messages>\n" + html.escape(batch, quote=False) + "\n</new_messages>"
        summary_prompt = SUMMARY.format(messages=wrapped)
        notes_prompt = NOTES.format(previous=previous_notes, history=batch)
        summary_result, notes_result = await asyncio.gather(
            client.chat([{"role": "user", "content": summary_prompt}], max_tokens=PROTOCOL["summary_max_output_tokens"], tag=f"{cid}:summary:{i}"),
            client.chat([{"role": "user", "content": notes_prompt}], max_tokens=PROTOCOL["notes_max_output_tokens"], tag=f"{cid}:notes:{i}"))
        previous_summary = summary_result["message"].get("content") or ""
        previous_notes = notes_result["message"].get("content") or ""
        known_ids = set(re.findall(r"\br\d{5}\b", "\n".join(batches[:i + 1])))
        referenced = set(re.findall(r"\br\d{5}\b", previous_notes))
        stages.append({"index": i, "input_tokens_proxy": tokens(batch), "summary": previous_summary,
                       "notes": previous_notes, "invalid_note_refs": sorted(referenced - known_ids),
                       "summary_request": summary_result["request_hash"], "notes_request": notes_result["request_hash"],
                       "summary_metrics": summary_result["metrics"], "notes_metrics": notes_result["metrics"]})
        write_json(dest, {"id": cid, "signature": signature, "stages": stages, "recent_tail": tail,
                          "summary": previous_summary, "notes": previous_notes, "total_batches": len(batches)})
        print(f"memory {cid} {i+1}/{len(batches)}", flush=True)
    return json.loads(dest.read_text())


def reader_context(memory: dict, arm: str, hits: list[dict] | None = None) -> str:
    parts = ["<conversation_summary>\n" + memory["summary"] + "\n</conversation_summary>"]
    if arm != "A":
        parts.append("<working_notebook>\n" + clip(memory["notes"], PROTOCOL["notes_context_tokens"]) + "\n</working_notebook>")
    if hits:
        parts.append("<retrieved_original_records>\n" + "\n\n".join(c["rendered"] for c in hits) + "\n</retrieved_original_records>")
    if memory["recent_tail"]:
        parts.append("<recent_history>\n" + memory["recent_tail"] + "\n</recent_history>")
    context = "\n\n".join(parts)
    if tokens(context) > PROTOCOL["reader_context_limit_tokens"]:
        raise ValueError("Reader memory exceeds preregistered hard cap")
    return context
