#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
"""Script to add or check license headers in Python and TypeScript files."""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

# License headers for different file types
LICENSE_HEADERS: Dict[str, str] = {
    "python": """# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
""",
    "typescript": """// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT
""",
}

# File extensions mapping
FILE_TYPE_MAP = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# Patterns to skip
SKIP_PATTERNS = [
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".next",
    ".venv",
    "venv",
    ".tox",
    "build",
    "dist",
    ".git",
    ".mypy_cache",
]


def should_skip(path: Path) -> bool:
    """Check if a path should be skipped."""
    return any(pattern in str(path) for pattern in SKIP_PATTERNS)


def get_file_type(file_path: Path) -> str | None:
    """Get the file type based on extension."""
    return FILE_TYPE_MAP.get(file_path.suffix)


def has_license_header(content: str, file_type: str) -> bool:
    """Check if content already has the license header."""
    lines = content.split("\n")
    license_header = LICENSE_HEADERS[file_type]
    
    # Skip shebang if present (Python files)
    start_idx = 0
    if lines and lines[0].startswith("#!"):
        start_idx = 1
        # Skip empty lines after shebang
        while start_idx < len(lines) and not lines[start_idx].strip():
            start_idx += 1
    
    # Check if license header is present
    header_lines = license_header.strip().split("\n")
    if len(lines) < start_idx + len(header_lines):
        return False
    
    for i, header_line in enumerate(header_lines):
        if lines[start_idx + i].strip() != header_line.strip():
            return False
    
    return True


def add_license_header(file_path: Path, dry_run: bool = False) -> bool:
    """Add license header to a file if not present.
    
    Args:
        file_path: Path to the file
        dry_run: If True, only check without modifying
        
    Returns:
        True if header was added (or would be added in dry-run), False if already present
    """
    file_type = get_file_type(file_path)
    if not file_type:
        return False
    
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return False
    
    if has_license_header(content, file_type):
        return False
    
    if dry_run:
        return True
    
    # Prepare new content with license header
    license_header = LICENSE_HEADERS[file_type]
    lines = content.split("\n")
    new_lines = []
    
    # Preserve shebang at the top if present (Python files)
    start_idx = 0
    if lines and lines[0].startswith("#!"):
        new_lines.append(lines[0])
        start_idx = 1
        # Skip empty lines after shebang
        while start_idx < len(lines) and not lines[start_idx].strip():
            start_idx += 1
        new_lines.append("")  # Empty line after shebang
    
    # Add license header
    new_lines.extend(license_header.strip().split("\n"))
    new_lines.append("")  # Empty line after header
    
    # Add the rest of the file
    new_lines.extend(lines[start_idx:])
    
    # Write back to file
    try:
        file_path.write_text("\n".join(new_lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"Error writing {file_path}: {e}", file=sys.stderr)
        return False


def find_source_files(root: Path) -> List[Path]:
    """Find all Python and TypeScript files in the given directory tree."""
    source_files = []
    
    for extension in FILE_TYPE_MAP.keys():
        for path in root.rglob(f"*{extension}"):
            if should_skip(path):
                continue
            source_files.append(path)
    
    return sorted(source_files)


def main():
    parser = argparse.ArgumentParser(
        description="Add or check license headers in Python and TypeScript files"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Paths to check (files or directories)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if headers are present without modifying files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    
    args = parser.parse_args()
    
    # Collect all source files
    all_files = []
    for path_str in args.paths:
        path = Path(path_str)
        if not path.exists():
            print(f"Error: Path does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        
        if path.is_file():
            if path.suffix in FILE_TYPE_MAP and not should_skip(path):
                all_files.append(path)
        else:
            all_files.extend(find_source_files(path))
    
    if not all_files:
        print("No source files found.")
        return 0
    
    # Process files
    missing_header = []
    modified = []
    
    for file_path in all_files:
        if add_license_header(file_path, dry_run=args.check):
            missing_header.append(file_path)
            if not args.check:
                modified.append(file_path)
                if args.verbose:
                    print(f"Added header to: {file_path}")
        elif args.verbose:
            print(f"Header already present: {file_path}")
    
    # Report results
    if args.check:
        if missing_header:
            print(f"\n❌ {len(missing_header)} file(s) missing license header:")
            for path in missing_header:
                print(f"  - {path}")
            print("\nRun 'make add-license' to add headers.")
            return 1
        else:
            print(f"✅ All {len(all_files)} source file(s) have license headers.")
            return 0
    else:
        if modified:
            print(f"✅ Added license header to {len(modified)} file(s).")
        else:
            print(f"✅ All {len(all_files)} source file(s) already have license headers.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

