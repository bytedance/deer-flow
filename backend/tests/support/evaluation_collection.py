from __future__ import annotations

from pathlib import Path

INDUSTRY_DERIVED_ORACLE_TEST_PARTS = ("fixtures", "evaluation", "industry_derived")


def is_industry_derived_fixture_oracle_path(path: str | Path, *, tests_root: str | Path) -> bool:
    """Return true for eval fixture oracle tests that must not join backend collection."""

    try:
        relative = Path(path).resolve().relative_to(Path(tests_root).resolve())
    except ValueError:
        return False

    parts = relative.parts
    return len(parts) >= 6 and parts[:3] == INDUSTRY_DERIVED_ORACLE_TEST_PARTS and parts[4:6] == ("fixture", "tests")
