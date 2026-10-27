from __future__ import annotations

import argparse
import asyncio
import json
import time

from common import ROOT, LiveClient, digest, write_json
from retrieval import HistoryIndex
from task_eval import actor


def budget_limited(row):
    if row["verified_completion"]:
        return False
    if any(e.get("reason") == "cumulative_context_budget" for e in row["events"]):
        return True
    return row["actor_cost"]["calls"] >= 8 and not any(e["type"] == "final" for e in row["events"])


async def continue_case(entry, client):
    cid = entry["id"]
    original = json.loads((ROOT / "results/tasks" / f"{cid}.json").read_text())
    protocol = json.loads((ROOT / "continuation-protocol.json").read_text())
    result = {"id": cid, "original_result_hash": digest(original), "protocol_hash": digest(protocol),
              "continued_arms": {}, "unchanged_arms": [], "failures": []}
    eligible = [a for a in "ABCD" if budget_limited(original["arms"][a])]
    result["unchanged_arms"] = [a for a in "ABCD" if a not in eligible]
    if eligible:
        case = json.loads((ROOT / "cases/tasks" / f"{cid}.json").read_text())
        gold = json.loads((ROOT / "gold/tasks" / f"{cid}.json").read_text())
        memory = json.loads((ROOT / "memory" / f"{cid}.json").read_text())
        assert memory["signature"] == original["memory_signature"]
        index = HistoryIndex(case["records"], cid)
        try:
            await index.build_vectors(client)
            for arm in eligible:
                old = original["arms"][arm]
                try:
                    new = await actor(case, gold, memory, index, client, arm,
                                      continuation={"prefix_calls": old["actor_cost"]["calls"]})
                    old_events = [e for e in old["events"] if e["type"] != "stop"]
                    assert new["events"][:len(old_events)] == old_events, "Original tool prefix changed"
                    result["continued_arms"][arm] = {"before_verified": old["verified_completion"],
                        "before_correct_artifact": old["correct_artifact"],
                        "added_model_calls": new["actor_cost"]["calls"] - old["actor_cost"]["calls"],
                        "added_prompt_tokens": new["actor_cost"]["prompt_tokens"] - old["actor_cost"]["prompt_tokens"],
                        "added_completion_tokens": new["actor_cost"]["completion_tokens"] - old["actor_cost"]["completion_tokens"],
                        "prefix_verified_identical": True, "result": new}
                except Exception as exc:
                    result["failures"].append({"arm": arm, "error_type": type(exc).__name__, "message": str(exc)})
        finally:
            index.close()
    write_json(ROOT / "results/continued" / f"{cid}.json", result)
    print("continued " + cid + " " + " ".join(a + "=" + str(int(v["result"]["verified_completion"]))
          for a, v in result["continued_arms"].items()), flush=True)
    return result


async def run(args):
    primary = json.loads((ROOT / "task-manifest.json").read_text())["test"]
    known = json.loads((ROOT / "known-goal-manifest.json").read_text())
    entries = primary + known
    client = LiveClient(args.endpoints, concurrency=4)
    sem = asyncio.Semaphore(2)
    scheduled = set()
    jobs = []
    async def one(entry):
        async with sem:
            return await continue_case(entry, client)
    try:
        while len(scheduled) < len(entries):
            for entry in entries:
                cid = entry["id"]
                if cid in scheduled:
                    continue
                path = ROOT / "results/tasks" / f"{cid}.json"
                if path.exists():
                    original = json.loads(path.read_text())
                    # Known-goal writer adds its diagnostic identity immediately after the base result.
                    if cid.startswith("known-") and "diagnostic_protocol_hash" not in original:
                        continue
                    scheduled.add(cid)
                    dest = ROOT / "results/continued" / f"{cid}.json"
                    if dest.exists():
                        saved = json.loads(dest.read_text())
                        assert saved["original_result_hash"] == digest(original)
                    else:
                        jobs.append(asyncio.create_task(one(entry)))
            if len(scheduled) < len(entries):
                if (ROOT / "results/tasks-test-run.json").exists() and (ROOT / "results/known-goal-run.json").exists():
                    break
                if not args.watch:
                    break
                await asyncio.sleep(15)
        rows = await asyncio.gather(*jobs)
        write_json(ROOT / "results/continuation-run.json", {"selected": len(entries),
            "scheduled": len(scheduled), "calls": client.calls,
            "failures": [{"id": r["id"], **f} for r in rows for f in r["failures"]]})
    finally:
        await client.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoints", required=True)
    p.add_argument("--watch", action="store_true")
    asyncio.run(run(p.parse_args()))
