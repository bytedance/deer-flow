#!/usr/bin/env python3
"""
Skill Packager - Creates a distributable .skill file of a skill folder

Usage:
    python scripts/package_skill.py <path/to/skill-folder> [output-directory]

Example:
    python scripts/package_skill.py skills/public/my-skill
    python scripts/package_skill.py skills/public/my-skill ./dist
"""

import fnmatch
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

if __name__ == "__main__" and not __package__:
    from quick_validate import validate_skill
else:
    from scripts.quick_validate import validate_skill

# Patterns to exclude when packaging skills.
EXCLUDE_DIRS = {"__pycache__", "node_modules"}
EXCLUDE_GLOBS = {"*.pyc"}
EXCLUDE_FILES = {".DS_Store"}
# Directories excluded only at the skill root (not when nested deeper).
ROOT_EXCLUDE_DIRS = {"evals"}


def should_exclude(rel_path: Path, *, is_directory: bool = False) -> bool:
    """Check if a path should be excluded from packaging."""
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    # rel_path is relative to skill_path.parent, so parts[0] is the skill
    # folder name and parts[1] (if present) is the first subdir.
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True
    if is_directory:
        return False
    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS)


def _is_link(info) -> bool:
    # The Windows name-surrogate bit marks path redirects (including junctions).
    # Cloud placeholders can be regular files with other reparse tags.
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_reparse_tag", 0) & 0x20000000)


def _write_files(archive, root: Path, destination: Path, staging_dir: Path):
    directories = [root]
    while directories:
        for path in directories.pop().iterdir():
            if path == destination or path == staging_dir:
                continue
            arcname = path.relative_to(root.parent)
            info = path.lstat()
            is_directory = stat.S_ISDIR(info.st_mode)
            if _is_link(info) or should_exclude(arcname, is_directory=is_directory):
                print(f"  Skipped: {arcname}")
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Entry is outside the skill directory: {arcname}")
            if is_directory:
                directories.append(path)
            elif stat.S_ISREG(info.st_mode):
                archive.write(path, arcname)
                print(f"  Added: {arcname}")


def package_skill(skill_path, output_dir=None):
    """
    Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory for the .skill file (defaults to current directory)

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_path.exists():
        print(f"❌ Error: Skill folder not found: {skill_path}", file=sys.stderr)
        return None

    if not skill_path.is_dir():
        print(f"❌ Error: Path is not a directory: {skill_path}", file=sys.stderr)
        return None

    # Validate SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    try:
        manifest_info = skill_md.lstat()
    except FileNotFoundError:
        print(f"❌ Error: SKILL.md not found in {skill_path}", file=sys.stderr)
        return None
    if _is_link(manifest_info) or not stat.S_ISREG(manifest_info.st_mode):
        print("❌ Error: SKILL.md must be a regular file inside the skill directory.", file=sys.stderr)
        return None

    # Run validation before packaging
    print("🔍 Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"❌ Validation failed: {message}", file=sys.stderr)
        print("   Please fix the validation errors before packaging.", file=sys.stderr)
        return None
    print(f"✅ {message}\n")

    # Determine output location
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"

    # Create the .skill file (zip format)
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        try:
            output_info = skill_filename.lstat()
        except FileNotFoundError:
            output_info = None
        if output_info and (_is_link(output_info) or not stat.S_ISREG(output_info.st_mode)):
            raise ValueError(f"Output must be a regular file: {skill_filename}")

        with tempfile.TemporaryDirectory(dir=output_path) as staging:
            staging_dir = Path(staging)
            staged = staging_dir / skill_filename.name
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as zipf:
                _write_files(zipf, skill_path, skill_filename, staging_dir)
            if output_info:
                staged.chmod(output_info.st_mode & 0o777)
            staged.replace(skill_filename)

        print(f"\n✅ Successfully packaged skill to: {skill_filename}")
        return skill_filename

    except Exception as e:
        print(f"❌ Error creating .skill file: {e}", file=sys.stderr)
        return None


def main():
    if len(sys.argv) < 2:
        print("❌ Error: A skill directory is required.", file=sys.stderr)
        print("Usage: python scripts/package_skill.py <path/to/skill-folder> [output-directory]")
        print("\nExample:")
        print("  python scripts/package_skill.py skills/public/my-skill")
        print("  python scripts/package_skill.py skills/public/my-skill ./dist")
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"📦 Packaging skill: {skill_path}")
    if output_dir:
        print(f"   Output directory: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
