"""Regression coverage for direct offline skill package uploads through nginx."""

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

_MIN_EXPECTED_BODY_SIZE_BYTES = 513 * 1024 * 1024
_MAX_EXPECTED_BODY_SIZE_BYTES = 600 * 1024 * 1024
_SIZE_MULTIPLIERS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def _extract_location_block(content: str, location_selector: str) -> str:
    marker = re.compile(r"location\s+" + re.escape(location_selector) + r"\s*\{")
    match = marker.search(content)
    assert match, f"could not find `location {location_selector}` block"

    start = match.end() - 1
    depth = 0
    for index, character in enumerate(content[start:], start=start):
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]

    raise AssertionError(f"unbalanced braces in `location {location_selector}` block")


def _parse_body_size_bytes(block: str) -> int:
    match = re.search(r"client_max_body_size\s+(\d+)\s*([mMkKgG]?)\s*;", block)
    assert match, "client_max_body_size value not found or not parseable"
    value, unit = match.groups()
    return int(value) * _SIZE_MULTIPLIERS[unit.lower()]


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_skill_upload_route_streams_an_archive_sized_request(path):
    content = (REPO_ROOT / path).read_text(encoding="utf-8")
    block = _extract_location_block(content, "= /api/skills/install/upload")

    assert "proxy_request_buffering off;" in block
    body_size = _parse_body_size_bytes(block)
    assert _MIN_EXPECTED_BODY_SIZE_BYTES <= body_size <= _MAX_EXPECTED_BODY_SIZE_BYTES
