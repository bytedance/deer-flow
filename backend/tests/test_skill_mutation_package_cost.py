"""Reproducible local capture measurements; not a model/provider benchmark."""

import statistics
import time

import pytest

from deerflow.skills.mutations.assets import capture_package


@pytest.mark.parametrize("files,size", [(4, 1024), (256, 65535)])
def test_capture_cost_at_typical_and_package_limit(tmp_path, files, size):
    (tmp_path / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\nBody\n", encoding="utf-8")
    for index in range(files - 1):
        (tmp_path / f"resource-{index:03}.bin").write_bytes(b"x" * size)
    timings, digests = [], set()
    for _ in range(5):
        start = time.perf_counter()
        package = capture_package(tmp_path)
        digests.add(package.digest)
        timings.append((time.perf_counter() - start) * 1000)
    assert len(digests) == 1
    assert len(package.files) == files
    print(f"capture+digest files={files} bytes={sum(len(item.content) for item in package.files)} median_ms={statistics.median(timings):.2f} max_ms={max(timings):.2f}")
