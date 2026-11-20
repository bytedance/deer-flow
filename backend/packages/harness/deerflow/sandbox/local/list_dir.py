from pathlib import Path

from deerflow.sandbox.search import ignore_rules_for


def list_dir(path: str, max_depth: int = 2, *, user_data: bool = False) -> list[str]:
    """
    List files and directories up to max_depth levels deep.

    Args:
        path: The root directory path to list.
        max_depth: Maximum depth to traverse (default: 2).
                   1 = only direct children, 2 = children + grandchildren, etc.
        user_data: The path belongs to the user's own files, which the ignore
                   rules must not hide outside a checkout either.

    Returns:
        A list of absolute paths for files and directories, excluding repository
        noise and, inside a git checkout, data-looking names such as ``*.log``.
        An existing empty directory returns an empty list.

    Raises:
        FileNotFoundError: If ``path`` does not exist or is not a directory.
        PermissionError: If a directory cannot be listed because of access
            permissions. Callers must not treat this as an empty listing.
    """
    result: list[str] = []
    root_path = Path(path).resolve()
    rules = ignore_rules_for(root_path, user_data=user_data)

    if not root_path.is_dir():
        raise FileNotFoundError(path)

    def _is_within_root(candidate: Path) -> bool:
        try:
            candidate.relative_to(root_path)
            return True
        except ValueError:
            return False

    def _traverse(current_path: Path, current_depth: int) -> None:
        """Recursively traverse directories up to max_depth."""
        if current_depth > max_depth:
            return

        for item in current_path.iterdir():
            if rules.should_ignore(item.name):
                continue

            if item.is_symlink():
                try:
                    item_resolved = item.resolve()
                    if not _is_within_root(item_resolved):
                        continue
                except OSError:
                    continue
                post_fix = "/" if item_resolved.is_dir() else ""
                result.append(str(item_resolved) + post_fix)
                continue

            item_resolved = item.resolve()
            if not _is_within_root(item_resolved):
                continue

            post_fix = "/" if item.is_dir() else ""
            result.append(str(item_resolved) + post_fix)

            # Recurse into subdirectories if not at max depth
            if item.is_dir() and current_depth < max_depth:
                _traverse(item, current_depth + 1)

    _traverse(root_path, 1)

    return sorted(result)
