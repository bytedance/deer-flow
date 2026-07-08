"""Small text configuration helpers.

The project intentionally uses plain ``.txt`` files for user-editable
configuration.  The supported format is INI-like and deliberately simple:

    # comments are ignored
    server.enabled=false
    [connections.analytics]
    type=postgresql
    host=localhost

Values are parsed as booleans, numbers, comma-separated lists, or strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def parse_txt_config(path: str | Path) -> dict[str, Any]:
    """Parse a user-editable txt config file into a nested dict."""
    config_path = Path(path)
    data: dict[str, Any] = {}
    current_section: list[str] = []

    with config_path.open("r", encoding="utf-8-sig", newline=None) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                if not section:
                    raise ValueError(f"Empty section name in {config_path}:{line_number}")
                current_section = [part.strip() for part in section.split(".") if part.strip()]
                if not current_section:
                    raise ValueError(f"Invalid section name in {config_path}:{line_number}")
                _ensure_container(data, current_section)
                continue

            if "=" not in line:
                raise ValueError(f"Invalid config line in {config_path}:{line_number}: {raw_line.rstrip()}")

            key, value = line.split("=", 1)
            key_parts = [part.strip() for part in key.strip().split(".") if part.strip()]
            if not key_parts:
                raise ValueError(f"Invalid config key in {config_path}:{line_number}")

            target_path = current_section + key_parts
            _set_nested(data, target_path, _parse_value(value.strip()))

    return data


def dump_txt_config(data: dict[str, Any]) -> str:
    """Serialize a nested dict to stable dotted-key txt format."""
    lines = [
        "# echart-skill 配置文件",
        "# 使用 KEY=VALUE；支持 # 或 ; 注释。",
        "",
    ]
    for key_path, value in _flatten(data):
        lines.append(f"{'.'.join(key_path)}={_format_value(value)}")
    lines.append("")
    return "\n".join(lines)


def _ensure_container(root: dict[str, Any], key_path: list[str]) -> dict[str, Any]:
    current = root
    for part in key_path:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"Config path {'.'.join(key_path)} conflicts with scalar value")
        current = child
    return current


def _set_nested(root: dict[str, Any], key_path: list[str], value: Any) -> None:
    parent = _ensure_container(root, key_path[:-1])
    parent[key_path[-1]] = value


def _has_commas_outside_parens(value: str) -> bool:
    """Return True if value contains commas not enclosed in parentheses."""
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return True
    return False


def _split_outside_parens(value: str, sep: str = ",") -> list[str]:
    """Split string by separator, ignoring separators inside parentheses."""
    result: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in value:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            result.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        result.append("".join(current))
    return result


def _parse_value(value: str) -> Any:
    if value == "":
        return ""

    lower = value.lower()
    if lower in {"true", "yes", "on"}:
        return True
    if lower in {"false", "no", "off"}:
        return False
    if lower in {"none", "null"}:
        return None

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    # Only treat as list if commas exist outside parentheses (e.g. "1,2,3"
    # but NOT "DECIMAL(10,2)" or "GEOMETRY(POINT,4326)")
    if _has_commas_outside_parens(value):
        parts = _split_outside_parens(value, ",")
        return [_parse_value(item.strip()) for item in parts]

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value


def _flatten(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    flattened: list[tuple[tuple[str, ...], Any]] = []
    for key, value in data.items():
        key_path = prefix + (str(key),)
        if isinstance(value, dict):
            flattened.extend(_flatten(value, key_path))
        else:
            flattened.append((key_path, value))
    return flattened


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_format_value(item) for item in value)
    if value is None:
        return ""
    return str(value)
