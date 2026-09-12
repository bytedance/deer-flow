from __future__ import annotations

import argparse
import datetime
import hashlib
import json

import numpy as np

from common import PROTOCOL, ROOT, digest, write_json
from task_eval import manifest_matches


def run(args):
    counts = {"public_rows": 0, "task_rows": 0, "continued_arms": 0, "chat_cache": 0, "vector_batches": 0}
    issues = []
    missing = []
    discordant = []
    nonchronological = []
    manifests = [("public", json.loads((ROOT / "public-manifest.json").read_text())["test"]),
                 ("tasks", json.loads((ROOT / "task-manifest.json").read_text())["test"]),
                 ("tasks", json.loads((ROOT / "known-goal-manifest.json").read_text()))]
    for kind, entries in manifests:
        for entry in entries:
            cid = entry["id"]
            case = json.loads((ROOT / "cases" / kind / f"{cid}.json").read_text())
            assert digest(case["records"]) == entry["history_hash"], cid
            if kind == "public":
                dates = [datetime.datetime.strptime(r["date"], "%Y/%m/%d (%a) %H:%M") for r in case["records"]]
                if dates != sorted(dates):
                    nonchronological.append(cid)
            path = ROOT / "results" / kind / f"{cid}.json"
            if not path.exists():
                missing.append(cid)
                continue
            row = json.loads(path.read_text())
            assert row["protocol_hash"] == digest(PROTOCOL), cid
            memory = json.loads((ROOT / "memory" / f"{cid}.json").read_text())
            assert memory["signature"] == row["memory_signature"]
            assert len(memory["stages"]) == memory["total_batches"]
            if kind == "public":
                counts["public_rows"] += 1
                for arm in "ABCD":
                    assert row["arms"][arm]["context_tokens_proxy"] <= PROTOCOL["reader_context_limit_tokens"]
                    if not row["arms"][arm]["grade"]["valid"]:
                        issues.append({"id": cid, "arm": arm, "issue": "invalid_judge"})
                if len({row["arms"][a]["grade"]["correct"] for a in "ABCD"}) > 1:
                    discordant.append({"id": cid, "question": row["question"], "reference": row["reference"],
                        "arms": {a: {"correct": row["arms"][a]["grade"]["correct"],
                                     "prediction": row["arms"][a]["prediction"]} for a in "ABCD"}})
            else:
                counts["task_rows"] += 1
                for arm, value in row["arms"].items():
                    actual = json.loads((ROOT / value["artifact_path"]).read_text())
                    assert actual == value["actual_manifest"]
                    assert manifest_matches(actual, row["expected"]) == value["correct_artifact"]
                continued = ROOT / "results/continued" / f"{cid}.json"
                if continued.exists():
                    ext = json.loads(continued.read_text())
                    assert ext["original_result_hash"] == digest(row)
                    issues.extend({"id": cid, "issue": "continuation_error", **f} for f in ext["failures"])
                    for arm, value in ext["continued_arms"].items():
                        counts["continued_arms"] += 1
                        assert value["prefix_verified_identical"]
                        new = value["result"]
                        actual = json.loads((ROOT / new["artifact_path"]).read_text())
                        assert actual == new["actual_manifest"]
                        assert manifest_matches(actual, row["expected"]) == new["correct_artifact"]
    if args.full:
        assert hashlib.sha256((ROOT / "data" / PROTOCOL["dataset_file"]).read_bytes()).hexdigest() == PROTOCOL["dataset_sha256"]
        for path in (ROOT / "cache/chat").glob("*.json"):
            cache = json.loads(path.read_text())
            assert cache["request_hash"] == path.stem
            assert "reasoning_content" not in cache["message"]
            counts["chat_cache"] += 1
        for path in (ROOT / "cache/embeddings").glob("*.npz"):
            with np.load(path) as blob:
                array = blob["vectors"]
            meta = json.loads(path.with_suffix(".json").read_text())
            assert array.shape == (meta["count"], 1024)
            assert np.isfinite(array).all() and np.allclose(np.linalg.norm(array, axis=1), 1, atol=1e-5)
            counts["vector_batches"] += 1
    if args.endpoints:
        settings = json.loads(__import__("pathlib").Path(args.endpoints).read_text())
        needles = [value.encode() for key in ("llm_base", "llm_key", "embedding_base", "embedding_key")
                   if isinstance(value := settings.get(key), str) and value]
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".py", ".md", ".txt", ".log"}:
                body = path.read_bytes()
                if any(secret in body for secret in needles):
                    issues.append({"file": str(path.relative_to(ROOT)), "issue": "private_endpoint_or_token_in_artifact"})
    result = {"counts": counts, "missing": missing, "issues": issues,
              "nonchronological_public_input_ids": nonchronological}
    write_json(ROOT / "results/audit.json", result)
    write_json(ROOT / "results/discordant-public.json", discordant)
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true")
    p.add_argument("--endpoints")
    run(p.parse_args())
