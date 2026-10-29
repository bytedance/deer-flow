"""Regression coverage for the opt-in --skip-frontend-build startup flag."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"
ROOT_MAKEFILE = REPO_ROOT / "Makefile"


def _make_recipe(target: str) -> str:
    makefile = ROOT_MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{target}:\n((?:\t.*\n?)+)", makefile, re.M)
    assert match, f"target {target!r} not found in root Makefile"
    return match.group(1)


def test_serve_script_parses_skip_frontend_build_flag() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")

    assert "SKIP_FRONTEND_BUILD=false" in serve
    assert "--skip-frontend-build) SKIP_FRONTEND_BUILD=true ;;" in serve


def test_prod_default_still_builds_via_preview() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")

    # Verify the control-flow: skip flag -> `run start`, otherwise -> `run preview`.
    assert re.search(
        r"elif\s+\$SKIP_FRONTEND_BUILD;\s+then.*?FRONTEND_CMD=.*?run start.*?\nelse\n\s*FRONTEND_CMD=.*?run preview",
        serve,
        re.S,
    ), "expected prod default to use `run preview` and --skip-frontend-build to use `run start`"


def test_skip_build_reuses_existing_build_and_requires_build_id() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")

    assert 'if [ ! -f "$REPO_ROOT/frontend/.next/BUILD_ID" ]; then' in serve
    assert "Run 'make start' once (full build)" in serve


def test_skip_build_preflight_runs_before_stop_all() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")

    assert serve.index("frontend/.next/BUILD_ID") < serve.index('if [ "$ACTION" = "restart" ]; then')


def test_make_start_exposes_flag_as_opt_in() -> None:
    for target in ("start", "start-daemon"):
        recipe = _make_recipe(target)
        assert "--skip-frontend-build" in recipe
        assert "$(if $(filter 1,$(SKIP_FRONTEND_BUILD)),--skip-frontend-build)" in recipe
