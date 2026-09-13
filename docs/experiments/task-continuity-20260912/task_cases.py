"""Independently authored replay prefixes followed by live tool execution.

These are controlled memory-dependent manifest tasks, not a claim of full
software-engineering benchmark coverage. Gold state is never sent to the actor.
"""
from __future__ import annotations

import hashlib
import json
import random

from common import ROOT, digest, write_json

FAMILIES = ["correction", "failed_attempt", "units", "artifact", "constraint", "provenance"]
NAMES = ["alder", "birch", "cedar", "dahlia", "elm", "fir", "ginkgo", "hazel", "iris", "juniper", "kelp", "larch", "maple", "nettle", "olive", "pine", "quince", "reed", "spruce", "thyme", "umber", "violet", "willow", "yarrow"]


def case_for(family: str, variant: int, split="test") -> tuple[dict, dict]:
    seed = int(hashlib.sha256(f"{family}:{variant}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    cid = f"task-{family}-{variant:02d}"
    service = f"{NAMES[(FAMILIES.index(family)*4+variant)%24]}-{rng.randint(100,999)}"
    release = f"rel-{rng.randint(3000,9999)}"
    records, stages, source_ids = [], [], []
    def add(stage, role, text):
        item = {"id": f"r{len(records):05d}", "session_id": f"workday-{stage+1}",
                "date": f"2026-08-{10+stage:02d}T{8+len(records)%10:02d}:00:00Z", "role": role, "content": text}
        records.append(item)
        return item["id"]
    goal = "Maintain an accurate operational handoff across the services in this work session. Preserve verified settings, rejected approaches, units, corrections, and exact artifact references so a requested service manifest can be completed later. All records are synthetic."
    add(0, "user", goal)
    if family == "correction":
        old = {"service": service, "region": "west-lab", "replicas": 2, "release": release}
        expected = {"service": service, "region": "north-lab", "replicas": 3+variant, "release": release}
        early = f"For service {service}, provisional rollout configuration: region west-lab, replicas 2, release {release}. It has not yet been approved."
        update = f"Correction for {service}: the west-lab placement was cancelled. The approved manifest must use region north-lab and {3+variant} replicas. Keep release {release}. This supersedes the provisional values."
        ask = f"Complete the approved rollout manifest for {service}, using the latest correction from our earlier work. Required keys: service, region, replicas, release."
    elif family == "failed_attempt":
        batch = 17+variant*3
        old = {"service": service, "strategy": "shared_pool", "batch_size": 64, "retry_policy": "unbounded"}
        expected = {"service": service, "strategy": "isolated_cursor", "batch_size": batch, "retry_policy": "bounded_two"}
        early = f"Service {service} attempted shared_pool with batch_size 64 and unbounded retries. Load-test result: worker starvation when an unrelated slow tenant monopolized connections. Status FAILED; this approach must not be retried unchanged."
        update = f"For the starvation incident in {service}, the accepted replacement isolates progress by tenant. Exact strategy name isolated_cursor; batch_size {batch}; retry_policy bounded_two. The regression probe passed with these settings."
        ask = f"Prepare the recovery manifest for {service} using the approach that avoided the earlier workers getting stuck behind another tenant. Required keys: service, strategy, batch_size, retry_policy."
    elif family == "units":
        sec = 7.5+variant*1.25
        kib = 48+variant*8
        old = {"service": service, "timeout_ms": int(sec), "max_payload_bytes": kib*1000, "replicas": 2}
        expected = {"service": service, "timeout_ms": int(sec*1000), "max_payload_bytes": kib*1024, "replicas": 2}
        early = f"Service {service} approved timeout {sec} seconds and payload limit {kib} KiB (binary, 1024 bytes per KiB). Replicas stay 2. The handoff manifest fields use milliseconds and bytes, so convert units."
        update = f"A later dashboard for {service} displayed a rounded timeout and decimal KB. Those are presentation values only: use the original approved seconds and binary KiB values when constructing the manifest. No configuration change was approved."
        ask = f"Finish the manifest for {service}; convert the original approved limits into the schema's units. Required keys: service, timeout_ms, max_payload_bytes, replicas."
    elif family == "artifact":
        sha = hashlib.sha256(f"verified-output:{service}:{release}".encode()).hexdigest()
        path = f"/artifacts/{service}/{release}/verified_bundle.tar"
        old = {"service": service, "artifact_path": f"/artifacts/{service}/latest.tar", "sha256": "unknown", "schema_version": 2}
        expected = {"service": service, "artifact_path": path, "sha256": sha, "schema_version": 3}
        early = f"Artifact verification completed for {service}. Path: {path}. SHA256: {sha}. Schema version: 3. Signature and checksum were checked successfully. The /latest.tar alias is an unverified draft and must not be used."
        update = f"Release review for {service}: consume the exact versioned artifact that passed checksum verification earlier. No new artifact was built today; do not substitute a latest alias or invent the digest."
        ask = f"Create the artifact manifest for {service} from the successfully verified build. Required keys: service, artifact_path, sha256, schema_version."
    elif family == "constraint":
        days = 9+variant*4
        old = {"service": service, "retention_days": 90, "export_mode": "raw", "pii_allowed": True}
        expected = {"service": service, "retention_days": days, "export_mode": "aggregate", "pii_allowed": False}
        early = f"Binding constraint for service {service}: retention_days must be {days}; export_mode aggregate; pii_allowed false. No raw personal rows may be included. This remains in force even if later examples use defaults."
        update = f"A sample integration guide shown during work on {service} contained retention_days=90, export_mode=raw, pii_allowed=true. That example is not approved for this service and does not override the binding constraint."
        ask = f"Finish the compliant export manifest for {service} under its original binding limits. Required keys: service, retention_days, export_mode, pii_allowed."
    else:
        owner = ["Mira", "Owen", "Leah", "Noah"][variant%4]
        old = {"service": service, "status": "ready", "approved_by": "unverified", "source_id": "none"}
        expected = {"service": service, "status": "ready", "approved_by": owner, "source_id": "SET_AFTER_RECORD"}
        early = f"Planning note for {service}: an assistant proposed marking the release ready, but there is no approval yet. This is only a hypothesis; do not treat it as verified."
        update = f"Approval event for {service}: reviewer {owner} completed the checks and explicitly approved status ready. This is the first verified approval. Cite this record's ID as the source, not the earlier assistant proposal."
        ask = f"Complete the evidence-backed status manifest for {service}. Required keys: service, status, approved_by, source_id. The source_id must be the original record ID of the verified approval."
    for stage in range(3):
        start = 0 if stage == 0 else len(records)
        for j in range(22):
            other = f"{rng.choice(NAMES)}-{rng.randint(1000,9999)}"
            detail = {"region": rng.choice(["west-lab", "north-lab", "east-lab"]),
                      "replicas": rng.randint(1,9), "release": f"rel-{rng.randint(3000,9999)}",
                      "timeout_ms": rng.randint(3,40)*1000, "retention_days": rng.randint(7,60),
                      "strategy": rng.choice(["isolated_cursor", "bounded_pool", "serial_queue"])}
            if stage == 0 and j == 3:
                source_ids.append(add(stage, "tool" if family in {"failed_attempt", "artifact"} else "user", early))
            if stage == 1 and j == 9:
                sid = add(stage, "user" if family in {"correction", "constraint", "units"} else "tool", update)
                source_ids.append(sid)
                if family == "provenance":
                    expected["source_id"] = sid
            note = f"Operational review of {other}: {json.dumps(detail)}. Verification was scoped to this service only. The experiment compared cold start and steady state; old retries were examined separately from rollout configuration. A follow-up ticket remains open for documentation."
            add(stage, "tool", note)
            if j % 4 == 0:
                add(stage, "assistant", f"Recorded {other}'s result. Keep its region, limits and release separate from similarly named services. Next, review the next service in the queue.")
        add(stage, "user", f"Day {stage+1} handoff: retain earlier approved settings and corrections. We will select a service for the final manifest after all reviews are complete.")
        stages.append(records[start:])
    case = {"id": cid, "split": split, "family": family, "goal": goal, "question": ask,
            "records": records, "stage_record_ids": [[r["id"] for r in s] for s in stages],
            "required_keys": list(expected), "initial_manifest": {"service": service}}
    gold = {"id": cid, "expected_manifest": expected, "superseded_manifest": old,
            "evidence_records": source_ids, "forbidden_pii": family == "constraint"}
    return case, gold


def prepare_tasks():
    manifest = {"test": [], "dev": []}
    for family in FAMILIES:
        for variant in range(4):
            case, gold = case_for(family, variant)
            write_json(ROOT / "cases/tasks" / f"{case['id']}.json", case)
            write_json(ROOT / "gold/tasks" / f"{case['id']}.json", gold)
            manifest["test"].append({"id": case["id"], "family": family, "history_hash": digest(case["records"])})
    for family in ["correction", "artifact"]:
        case, gold = case_for(family, 100, "dev")
        write_json(ROOT / "cases/tasks" / f"{case['id']}.json", case)
        write_json(ROOT / "gold/tasks" / f"{case['id']}.json", gold)
        manifest["dev"].append({"id": case["id"], "family": family, "history_hash": digest(case["records"])})
    write_json(ROOT / "task-manifest.json", manifest)
    print(json.dumps({k: len(v) for k,v in manifest.items()}))


if __name__ == "__main__":
    prepare_tasks()
