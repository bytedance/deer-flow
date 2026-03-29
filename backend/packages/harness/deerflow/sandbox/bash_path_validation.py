import re

_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![:/\w])/(?:[^\s\"'`;&|<>()]+)")


def extract_absolute_path_candidates(command: str) -> list[str]:
    """Extract local absolute-path candidates from a shell command string."""
    return _ABSOLUTE_PATH_PATTERN.findall(command)
