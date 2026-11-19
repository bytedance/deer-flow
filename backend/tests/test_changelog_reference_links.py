"""The change logs must render every ``[#1234]`` mention as a link.

Both change logs list pull requests with reference-style links: the entry text
carries ``[#1234]`` and a ``[#1234]: <url>`` line at the bottom supplies the
target. A missing definition renders as the literal characters ``[#1234]``, and a
definition whose number or repository differs from its key silently points at a
different page. Neither is visible while reviewing an entry, so pin both here.

These checks read the two files only — no network, no fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGELOGS = ("CHANGELOG.md", "CHANGELOG_zh.md")

_DEFINITION = re.compile(r"^\[\s*#?(?P<key>\d+)\s*\]:\s*(?P<url>\S+)\s*$")
# ``[#1234]`` used as reference text. A following ``(`` or ``[`` makes it an
# inline link (``[#1234](url)``), which needs no definition.
_REFERENCE = re.compile(r"\[#(\d+)\](?![\[(])")
_SAME_REPO_TARGET = re.compile(r"^https://github\.com/bytedance/deer-flow/(?:pull|issues)/(?P<number>\d+)$")
_COMMIT_PERMALINK = re.compile(r"^https://github\.com/bytedance/deer-flow/commit/[0-9a-f]{40}$")


def _scan(path: Path) -> tuple[set[int], dict[int, str]]:
    """Return the ``[#n]`` tokens used in prose and the ``[#n]:`` definitions."""
    used: set[int] = set()
    defined: dict[int, str] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        definition = _DEFINITION.match(stripped)
        if definition:
            defined[int(definition.group("key"))] = definition.group("url")
            continue
        if in_fence:
            continue
        used.update(int(match.group(1)) for match in _REFERENCE.finditer(line))
    return used, defined


@pytest.mark.parametrize("changelog", CHANGELOGS)
def test_every_reference_mention_has_a_definition(changelog: str) -> None:
    used, defined = _scan(REPO_ROOT / changelog)

    missing = sorted(used - set(defined))
    assert not missing, f"{changelog} mentions {['#' + str(n) for n in missing]} as [#n] reference text without a '[#n]: <url>' definition, so it renders as literal text."


@pytest.mark.parametrize("changelog", CHANGELOGS)
def test_definitions_target_their_own_number_in_this_repository(changelog: str) -> None:
    _, defined = _scan(REPO_ROOT / changelog)

    drifted = []
    for number, url in defined.items():
        same_repo = _SAME_REPO_TARGET.match(url)
        if same_repo is not None:
            if int(same_repo.group("number")) != number:
                drifted.append(f"[#{number}]: {url}")
        elif _COMMIT_PERMALINK.match(url) is None:
            drifted.append(f"[#{number}]: {url}")
    assert not drifted, f"{changelog} defines a reference outside bytedance/deer-flow, or aimed at a different number than its key: {drifted[:5]}"
