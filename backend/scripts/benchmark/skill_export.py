"""Reproducible bounded export measurements against production entry points.

Run from backend with PYTHONPATH=packages/harness:packages/extension-api:.:
    python scripts/benchmark/skill_export.py
Each workload uses a fresh process; RSS is that process's peak, including imports.
No scripts, network, models, or security scanners are invoked by this benchmark.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from deerflow.skills import export
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage


class Tracker:
    def __init__(self):
        self.files = []
        self.peak_count = 0
        self.peak_bytes = 0
        self.original = tempfile.TemporaryFile

    def sample(self):
        active = [file for file in self.files if not file.closed]
        self.peak_count = max(self.peak_count, len(active))
        self.peak_bytes = max(self.peak_bytes, sum(file.high_water for file in active))

    def create(self, *args, **kwargs):
        tracker = self

        class Tracked:
            def __init__(self, raw):
                self.raw = raw
                self.high_water = 0

            def write(self, data):
                written = self.raw.write(data)
                self.high_water = max(self.high_water, self.raw.tell())
                tracker.sample()
                return written

            def __getattr__(self, name):
                return getattr(self.raw, name)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.raw.close()

        file = Tracked(self.original(*args, **kwargs))
        self.files.append(file)
        self.sample()
        return file


def run(case):
    with tempfile.TemporaryDirectory(prefix="skill-export-benchmark-") as workspace:
        storage = LocalSkillStorage(host_path=workspace)
        name = "skill-creator" if case == "public" else "benchmark"
        root = storage.get_custom_skill_dir(name)
        if case == "public":
            public = Path(__file__).resolve().parents[3] / "skills/public/skill-creator"
            shutil.copytree(public, root, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text("---\nname: benchmark\ndescription: Export benchmark\n---\n", encoding="utf-8")
            if case in ("large", "cancel"):
                # Incompressible bytes exercise ZIP disk limits realistically.
                with (root / "asset.bin").open("wb") as file:
                    for _ in range(64):
                        file.write(os.urandom(1024 * 1024))
            elif case == "entries":
                for index in range(4094):
                    (root / f"asset-{index:04}").touch()
        tracker = Tracker()
        export.tempfile.TemporaryFile = tracker.create
        start = time.perf_counter()
        manifest_seconds = None
        archive_bytes = None
        outcome = "ok"
        try:
            if case == "cancel":
                event = threading.Event()
                timer = threading.Timer(0.02, event.set)
                timer.start()
                try:
                    export.export_manifest(storage, name, event)
                except export.SkillExportError as error:
                    outcome = error.code
                finally:
                    timer.cancel()
                    timer.join()
            else:
                manifest = export.export_manifest(storage, name)
                manifest_seconds = time.perf_counter() - start
                archive = export.build_skill_export(storage, name, manifest["revision"])
                try:
                    archive_bytes = archive.size
                finally:
                    archive.close()
            elapsed = time.perf_counter() - start
        finally:
            export.tempfile.TemporaryFile = tracker.original
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(
            json.dumps(
                {
                    "case": case,
                    "outcome": outcome,
                    "wall_seconds": round(elapsed, 4),
                    "manifest_seconds": round(manifest_seconds, 4) if manifest_seconds is not None else None,
                    "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
                    "peak_temp_files": tracker.peak_count,
                    "peak_temp_bytes": tracker.peak_bytes,
                    "remaining_temp_files": sum(not file.closed for file in tracker.files),
                    "archive_bytes": archive_bytes,
                }
            )
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        for case in ("public", "large", "entries", "cancel"):
            subprocess.run([sys.executable, __file__, case], check=True)
