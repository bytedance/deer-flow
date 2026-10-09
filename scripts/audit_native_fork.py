"""Verify the frozen local user-fork path disposition; no network or mutations."""

import json
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "docs/ecs-native-fork-disposition.v1.json").read_text(encoding="utf-8")
    )
    changes = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-status",
            manifest["ancestor"],
            manifest["cached_user_fork"],
        ],
        cwd=root,
        text=True,
    )
    expected = dict(line.split("\t", 1)[::-1] for line in changes.splitlines())
    actual = {entry["path"]: entry["fork_change"] for entry in manifest["paths"]}
    if actual != expected or len(actual) != len(manifest["paths"]):
        raise SystemExit("Fork delta coverage mismatch or duplicate paths")
    for entry in manifest["paths"]:
        if (
            entry["disposition"]
            not in {"retained_exact", "adapted", "replaced", "retired"}
            or not entry["behavior"]
            or not entry["replacement"]
        ):
            raise SystemExit("Incomplete fork path disposition")
        source = subprocess.check_output(
            ["git", "rev-parse", manifest["cached_user_fork"] + ":" + entry["path"]],
            cwd=root,
            text=True,
        ).strip()
        if source != entry["fork_blob"]:
            raise SystemExit("Fork source blob mismatch")
        if entry["disposition"] == "adapted" and (
            not (root / entry["path"]).is_file() or not entry.get("verification")
        ):
            raise SystemExit(
                "Adapted behavior is missing its current file or verification mapping"
            )
        if entry["disposition"] == "retained_exact":
            local = subprocess.check_output(
                ["git", "hash-object", entry["path"]], cwd=root, text=True
            ).strip()
            if local != source:
                raise SystemExit("Retained content differs from its source")
    print(
        f"Audited coverage: {len(actual)} cached fork paths; no unclassified or duplicate paths"
    )
    print(json.dumps(manifest["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
