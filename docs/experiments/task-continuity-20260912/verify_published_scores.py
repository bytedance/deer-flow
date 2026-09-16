"""Check published aggregate counts from metadata only; no dataset or network."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def verify():
    rows = json.loads((ROOT / "results/case-scores.json").read_text())
    summary = json.loads((ROOT / "results/summary.json").read_text())
    public_ids = {r["id"] for r in json.loads((ROOT / "public-manifest.json").read_text())["test"]}
    continued = {r["id"]: r for r in rows if r["group"] == "continued"}
    checked = {}
    groups = [("public", "public", "test"), ("tasks", "tasks", "test"), ("known_goal", "tasks", "known_goal"),
              ("continued_tasks", "tasks", "test"), ("continued_known_goal", "tasks", "known_goal")]
    for name, group, split in groups:
        selected = [r for r in rows if r["group"] == group and r.get("split") == split]
        assert len(selected) == summary[name]["completed"], name
        if name == "public":
            assert {r["id"] for r in selected} | set(summary[name]["missing"]) == public_ids
        counts = {}
        for arm in "ABCD":
            total = 0
            for row in selected:
                value = row["arms"][arm]
                if name.startswith("continued_") and arm in continued[row["id"]]["continued_arms"]:
                    value = continued[row["id"]]["continued_arms"][arm]["result"]
                if name == "public":
                    total += bool(value["grade"]["correct"] and value["grade"]["valid"])
                else:
                    total += bool(value["verified_completion"] and not value["constraint_violations"])
            assert total == summary[name]["arms"][arm]["correct"], (name, arm, total)
            counts[arm] = total
        checked[name] = {"completed": len(selected), "correct": counts}
    print(json.dumps(checked, indent=2))


if __name__ == "__main__":
    verify()
