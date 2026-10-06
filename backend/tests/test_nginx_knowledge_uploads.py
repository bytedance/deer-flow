"""Regression coverage for the knowledge-base document upload route through
nginx (RFC v3 §7 部署材料): the route needs the same independent-location
treatment as the thread uploads route, otherwise uploads larger than nginx's
``1m`` default are rejected with a 413 before the request ever reaches
Gateway.

The route is ``POST /api/knowledge-bases/{kb_id}/documents``. Without its own
location it falls through to the generic ``/api/`` prefix, which carries no
``client_max_body_size`` override. This locks the large-body settings onto the
route across all three places this nginx config is maintained: the Docker
production config, the local-dev config used by ``make dev``, and the
Kubernetes/Helm ConfigMap template.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = (
    "docker/nginx/nginx.conf",
    "docker/nginx/nginx.local.conf",
    "deploy/helm/deer-flow/templates/configmap-nginx.yaml",
)

LOCATION_SELECTOR = r"~ ^/api/knowledge-bases/[^/]+/documents"

# Documents (PDF/Office/images) are far larger than text prompts; anything in
# this range comfortably clears nginx's 1m default (the actual bug) while
# staying bounded.
_MIN_EXPECTED_BODY_SIZE_BYTES = 16 * 1024 * 1024
_MAX_EXPECTED_BODY_SIZE_BYTES = 1024 * 1024 * 1024

_SIZE_MULTIPLIERS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _extract_location_block(content: str, location_selector: str) -> str:
    """Extract a single nginx ``location <location_selector> { ... }`` block
    by brace-depth matching, so assertions target only that location and can't
    be satisfied by a directive that merely appears elsewhere in the file."""
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


def _parse_body_size_bytes(block: str) -> int:
    match = re.search(r"client_max_body_size\s+(\d+)\s*([mMkKgG]?)\s*;", block)
    assert match, "client_max_body_size value not found or not parseable"
    value, unit = match.groups()
    return int(value) * _SIZE_MULTIPLIERS[unit.lower()]


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_knowledge_uploads_route_has_its_own_body_size_limit(path):
    content = _read(path)
    block = _extract_location_block(content, LOCATION_SELECTOR)

    size_bytes = _parse_body_size_bytes(block)

    assert _MIN_EXPECTED_BODY_SIZE_BYTES <= size_bytes <= _MAX_EXPECTED_BODY_SIZE_BYTES, (
        f"{path}: /api/knowledge-bases/.../documents client_max_body_size is "
        f"{size_bytes} bytes, expected between {_MIN_EXPECTED_BODY_SIZE_BYTES} "
        f"and {_MAX_EXPECTED_BODY_SIZE_BYTES} bytes -- comfortably above "
        "nginx's 1m default, which would otherwise reject document uploads "
        "before they reach Gateway (RFC v3 §7 部署材料)"
    )


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_knowledge_uploads_route_disables_request_buffering(path):
    content = _read(path)
    block = _extract_location_block(content, LOCATION_SELECTOR)

    assert "proxy_request_buffering off;" in block, (
        f"{path}: /api/knowledge-bases/.../documents does not disable request "
        "buffering, so nginx spools document upload bodies to a temp file "
        "before proxying them to Gateway, which can 500 with a permission "
        "error on non-root local runs"
    )
