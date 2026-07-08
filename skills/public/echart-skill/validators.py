import re
from pathlib import Path
from typing import Final

TABLE_NAME_PATTERN: Final = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')
MAX_TABLE_NAME_LENGTH: Final = 128

SQL_RESERVED_WORDS: Final = frozenset({
    'select', 'insert', 'update', 'delete', 'drop', 'create', 'alter',
    'table', 'index', 'view', 'trigger', 'schema', 'database',
    'from', 'where', 'join', 'inner', 'outer', 'left', 'right',
    'on', 'group', 'order', 'having', 'limit', 'offset', 'union',
    'all', 'distinct', 'as', 'and', 'or', 'not', 'null', 'true', 'false',
})


def validate_table_name(table_name: str) -> str:
    """
    Validate table name for SQL safety.

    Rules:
    - Must start with a letter
    - Can only contain letters, numbers, underscores
    - Cannot be a SQL reserved word
    - Max length 128 characters

    Raises:
        ValueError: If table name is invalid
    """
    if not table_name:
        raise ValueError("表名不能为空")

    if len(table_name) > MAX_TABLE_NAME_LENGTH:
        raise ValueError(f"表名过长，最大允许 {MAX_TABLE_NAME_LENGTH} 个字符")

    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(
            f"无效的表名 '{table_name}': "
            "表名只能包含字母、数字和下划线，且必须以字母开头"
        )

    if table_name.lower() in SQL_RESERVED_WORDS:
        raise ValueError(f"'{table_name}' 是 SQL 保留字，不能作为表名")

    return table_name


def sanitize_table_name(name: str, default: str = "data") -> str:
    """Convert arbitrary text into a safe DuckDB table name."""
    stem = Path(str(name)).stem
    sanitized = re.sub(r'\W+', '_', stem).strip('_')

    if not sanitized:
        sanitized = default

    if not sanitized[0].isalpha():
        sanitized = f"{default}_{sanitized}"

    sanitized = sanitized[:MAX_TABLE_NAME_LENGTH].rstrip('_') or default

    if sanitized.lower() in SQL_RESERVED_WORDS:
        sanitized = f"{sanitized}_table"

    return validate_table_name(sanitized)


def quote_identifier(identifier: str) -> str:
    """Validate and quote a SQL identifier for DuckDB."""
    return f'"{validate_table_name(identifier)}"'


def validate_file_path(
    file_path: str,
    base_dir: str,
    must_exist: bool = False
) -> str:
    """
    Validate that file path is within base directory.

    Args:
        file_path: Path to validate
        base_dir: Base directory that paths must be within
        must_exist: If True, raise error if file doesn't exist

    Returns:
        Validated absolute path

    Raises:
        ValueError: If path is outside base directory
        FileNotFoundError: If must_exist=True and file not found
    """
    import os
    from pathlib import Path

    file_path = Path(file_path)
    base_dir = Path(base_dir).resolve()

    try:
        resolved_path = file_path.resolve()
    except OSError as e:
        raise ValueError(f"无效的文件路径: {e}")

    if not str(resolved_path).startswith(str(base_dir) + os.sep):
        if resolved_path != base_dir:
            raise ValueError(
                f"路径 '{file_path}' 不在允许的目录 '{base_dir}' 内"
            )

    if must_exist and not resolved_path.exists():
        raise FileNotFoundError(f"文件不存在: {resolved_path}")

    return str(resolved_path)
