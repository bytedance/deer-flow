"""PROPOSAL: hygiene only; never contributes normal STOP/report evidence."""

import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
prefix, image = sys.argv[2:4]
assert re.fullmatch(r"deer-c-aio-[0-9a-f]{24}", prefix)
assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)


def inspect(identity):
    assert re.fullmatch(r"[0-9a-f]{64}", identity)
    result = subprocess.run(["docker", "inspect", identity], capture_output=True, text=True, timeout=10)
    if result.returncode:
        assert "no such object" in result.stderr.lower() or "no such container" in result.stderr.lower(), "Inspection unknown; refuse cleanup"
        return None
    value = json.loads(result.stdout)[0]
    assert value["Id"] == identity
    return value


report = {"normal_acceptance_evidence": False, "removed_ids": []}
# Only the exact harness ID returned to Docker's own cidfile is eligible.
cid = root / "harness.cid"
if cid.exists():
    identity = cid.read_text().strip()
    row = inspect(identity)
    if row is not None:
        assert row["Name"] == "/deer-c-harness-" + prefix.removeprefix("deer-c-aio-")
        assert row["Config"]["Labels"]["deerflow.role"] == "fixture-harness"
        assert row["Config"]["Labels"]["org.deerflow.tenant.owned"] == prefix
        subprocess.run(["docker", "rm", "-f", identity], check=True, capture_output=True, timeout=30)
        assert inspect(identity) is None
        report["removed_ids"].append(identity)
manifest = root / "evidence.json"
if manifest.exists():
    evidence = json.loads(manifest.read_text())
    identity = evidence.get("container_id")
    if identity:
        row = inspect(identity)
        if row is not None:
            assert row["Image"] == image == evidence["image_id"]
            assert row["Name"] == "/" + evidence["container_name"] == "/" + prefix + "-" + evidence["sandbox_id"]
            labels = row["Config"].get("Labels") or {}
            assert labels["org.deerflow.tenant.owned"] == prefix
            assert labels["deerflow.role"] == "sandbox" and labels["deerflow.sandbox_id"] == evidence["sandbox_id"]
            subprocess.run(["docker", "rm", "-f", identity], check=True, capture_output=True, timeout=30)
            assert inspect(identity) is None
            report["removed_ids"].append(identity)
(root / "cleanup.json").write_text(json.dumps(report, indent=2))
# Diagnose pre-acquire/manifest failures without guessing which object to stop.
leftovers = subprocess.run(["docker", "ps", "-aq", "--filter", "label=org.deerflow.tenant.owned=" + prefix], check=True, capture_output=True, text=True, timeout=10).stdout.split()
assert not leftovers, "Owned objects remain without a valid exact-ID cleanup receipt; manual review required"
