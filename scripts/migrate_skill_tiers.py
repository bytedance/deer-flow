"""Migration script: assign tier labels to existing skills in extensions_config.json.

Industrial skills (vibration/rotating/reciprocating fault diagnosis, InS device
analysis, pump diagnosis, static equipment corrosion, rotating device context)
are tagged ``core-industrial``.

Everything else (data-analysis, deep-research, image-generation, and all
bundled public skills) is tagged ``foundation``.

Usage::

    python scripts/migrate_skill_tiers.py            # apply
    python scripts/migrate_skill_tiers.py --dry-run  # preview
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INDUSTRIAL_SKILLS: set[str] = {
    "vibration-fault-diagnosis",
    "reciprocating-fault-diagnosis",
    "rotating-fault-diagnosis",
    "rotating-device-context",
    "pump-fault-diagnosis",
    "static-equipment-corrosion-diagnosis",
    "ins-device-analysis",
    "ins-get-trend-data",
    "ins-get-waveform-data",
    "ins-get-orbit-data",
    "ins-extract-orbit-centerline-features",
    "ins-extract-spectral-waveform-features",
    "ins-extract-trend-features",
    "ins-get-trend-data-2k",
    "ins-extract-trend-features-2k",
    "ins-device-analysis-2k",
    "ins-get-trend-data-6k",
    "ins-extract-trend-features-6k",
    "ins-device-analysis-6k",
    "ins-get-trend-data-9k",
    "ins-extract-trend-features-9k",
    "ins-device-analysis-9k",
}

CORE_TIER = "core-industrial"
FOUNDATION_TIER = "foundation"


def resolve_config_path() -> Path:
    """Locate extensions_config.json using project-root heuristics."""
    candidates = [
        Path.cwd() / "extensions_config.json",
        Path.cwd().parent / "extensions_config.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("extensions_config.json not found in project root")


def discover_skill_names(skills_root: Path) -> set[str]:
    """Scan skills/{public,custom}/*/SKILL.md and collect skill directory names."""
    names: set[str] = set()
    for category in ("public", "custom"):
        category_dir = skills_root / category
        if not category_dir.exists():
            continue
        for md_file in category_dir.rglob("SKILL.md"):
            skill_dir = md_file.parent
            if skill_dir.name and skill_dir.name != ".history":
                names.add(skill_dir.name)
    return names


def migrate(config_path: Path, skills_root: Path, dry_run: bool = False) -> int:
    """Apply tier labels and return number of skills modified."""
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    skill_names = discover_skill_names(skills_root)
    skills_section = config.setdefault("skills", {})

    modified = 0
    for name in sorted(skill_names):
        target_tier = CORE_TIER if name in INDUSTRIAL_SKILLS else FOUNDATION_TIER
        entry = skills_section.get(name, {})
        current_tier = entry.get("tier")
        if current_tier == target_tier:
            continue

        if dry_run:
            action = "ADD" if name not in skills_section else "UPDATE"
            print(f"  [{action}] {name}: tier={target_tier}")
        else:
            if name not in skills_section:
                skills_section[name] = {"enabled": True, "tier": target_tier}
            else:
                skills_section[name]["tier"] = target_tier
        modified += 1

    if not dry_run and modified > 0:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Wrote {modified} tier label(s) to {config_path}")
    elif dry_run:
        print(f"Dry run: {modified} skill(s) would be modified")
    else:
        print("No changes needed")

    return modified


def main() -> int:
    parser = argparse.ArgumentParser(description="Assign tier labels to skills")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--config", type=str, help="Path to extensions_config.json")
    parser.add_argument("--skills-root", type=str, help="Path to skills/ directory")
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else resolve_config_path()
    skills_root = Path(args.skills_root) if args.skills_root else config_path.parent / "skills"

    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1
    if not skills_root.exists():
        print(f"Skills root not found: {skills_root}", file=sys.stderr)
        return 1

    migrate(config_path, skills_root, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
