"""Regression test pinning the nginx image tag in the shipped compose files.

Both compose files deployed ``image: nginx:alpine`` — a floating tag. When the
``nginx:alpine`` alias moved to the 1.31.3 alpine build (musl 1.2.6), nginx's
pid-file ``pwrite()`` started issuing the ``pwritev2(RWF_NOAPPEND)`` syscall,
which the default seccomp profile of older Docker releases (and EOL kernels
such as CentOS 7) does not allowlist. The master then dies with ``pwrite()
"/run/nginx.pid" failed (1: Operation not permitted)`` and the container
restart-loops, so ``make docker-start`` / ``make up`` never become healthy
(#7615; upstream nginx/docker-nginx#1059 — the image cannot fix this, only a
pinned pre-musl-1.2.6 build or a host upgrade helps).

This test pins the exact-tag policy so the alias (or any other floating tag)
cannot silently return.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}

# An exact tag carries a full major.minor.patch; `alpine` / `latest` /
# `1.31` style tags float and can re-resolve to a broken build overnight.
EXACT_TAG = re.compile(r"^[^:]+:\d+\.\d+\.\d+(-[a-z]+)?$")


def test_nginx_image_is_pinned_to_an_exact_tag() -> None:
    for name, compose_path in COMPOSE_PATHS.items():
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        image = (compose.get("services") or {}).get("nginx", {}).get("image")
        assert isinstance(image, str) and image, f"{name}: nginx service must declare an image"
        assert EXACT_TAG.match(image), f"{name}: nginx image {image!r} must pin an exact tag — a floating tag resolved to the musl-1.2.6 alpine build whose pwritev2 syscall older Docker seccomp profiles reject (#7615)"


def test_both_compose_files_pin_the_same_nginx_image() -> None:
    images = set()
    for compose_path in COMPOSE_PATHS.values():
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        images.add((compose.get("services") or {}).get("nginx", {}).get("image"))
    assert len(images) == 1, "prod and dev compose files must pin the same nginx image"
