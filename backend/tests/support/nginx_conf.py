"""Helpers for asserting on the three maintained nginx configs.

The Docker production config, the local-dev config used by ``make dev`` and the
Kubernetes/Helm ConfigMap template carry the same routing and must not drift;
tests parametrize over ``NGINX_CONFIGS`` and inspect one ``location`` block at
a time so a directive that merely appears elsewhere in the file cannot satisfy
an assertion by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NGINX_CONFIGS = (
    "docker/nginx/nginx.conf",
    "docker/nginx/nginx.local.conf",
    "deploy/helm/deer-flow/templates/configmap-nginx.yaml",
)

_SIZE_MULTIPLIERS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_DURATION_MULTIPLIERS = {"": 1, "s": 1, "m": 60, "h": 3600}


def read_config(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def extract_location_block(content: str, location_selector: str) -> str:
    """Return the single ``location <location_selector> { ... }`` block.

    Brace-depth matching keeps assertions inside that location, so the
    neighboring uploads location (which already has the large-body settings)
    cannot make another route's assertions pass.
    """
    marker = re.compile(r"location\s+" + re.escape(location_selector) + r"\s*\{")
    match = marker.search(content)
    assert match, f"could not find `location {location_selector}` block"

    start = match.end() - 1  # index of the opening brace
    depth = 0
    for i, ch in enumerate(content[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return content[start : i + 1]

    raise AssertionError(f"unbalanced braces in `location {location_selector}` block")


def parse_body_size_bytes(block: str) -> int:
    match = re.search(r"client_max_body_size\s+(\d+)\s*([mMkKgG]?)\s*;", block)
    assert match, "client_max_body_size value not found or not parseable"
    value, unit = match.groups()
    return int(value) * _SIZE_MULTIPLIERS[unit.lower()]


def parse_read_timeout_seconds(block: str) -> int:
    # Anchored to the start of a line so a commented-out directive does not count.
    match = re.search(r"^\s*proxy_read_timeout\s+(\d+)([smh]?)\s*;", block, re.M)
    assert match, "no active proxy_read_timeout directive"
    value, unit = match.groups()
    return int(value) * _DURATION_MULTIPLIERS[unit]
