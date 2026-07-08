"""Data lineage records for generated BI artifacts.

Lineage is intentionally append-only JSONL so reports, dashboards, charts, and
exports can all record where their evidence came from without sharing a heavy
runtime dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_LINEAGE_PATH = PROJECT_ROOT / "outputs" / "lineage" / "lineage.jsonl"


@dataclass
class LineageRecord:
    """One generated artifact's evidence lineage."""

    artifact_path: str
    artifact_type: str
    source_tables: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    query_hashes: list[str] = field(default_factory=list)
    metric_scopes: list[str] = field(default_factory=list)
    generated_by: str = ""
    cwd: str = field(default_factory=lambda: os.getcwd())
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cwd"] = str(Path(data["cwd"]).resolve())
        return data


def hash_query(query: str) -> str:
    """Return a stable short hash for a SQL/query string."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _lineage_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        p = Path(path)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return DEFAULT_LINEAGE_PATH


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def record_lineage(record: LineageRecord, path: str | os.PathLike[str] | None = None) -> Path:
    """Append one lineage record and return the JSONL path."""
    lineage_path = _lineage_path(path)
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    with lineage_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return lineage_path


def read_lineage(path: str | os.PathLike[str] | None = None) -> list[LineageRecord]:
    """Read lineage records from JSONL, skipping malformed rows."""
    lineage_path = _lineage_path(path)
    if not lineage_path.exists():
        return []
    records: list[LineageRecord] = []
    with lineage_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                records.append(LineageRecord(**data))
            except (TypeError, json.JSONDecodeError):
                continue
    return records


def find_lineage(
    artifact_path: str | None = None,
    artifact_type: str | None = None,
    source_table: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> list[LineageRecord]:
    """Filter lineage records by artifact path/type/source table."""
    records = read_lineage(path)
    if artifact_path:
        target = str(Path(artifact_path).resolve())
        records = [
            r for r in records
            if str(Path(r.artifact_path).resolve()) == target or r.artifact_path == artifact_path
        ]
    if artifact_type:
        records = [r for r in records if r.artifact_type == artifact_type]
    if source_table:
        records = [r for r in records if source_table in r.source_tables]
    return records


def render_lineage_markdown(records: list[LineageRecord]) -> str:
    """Render lineage records as compact Markdown."""
    lines = ["# 数据血缘记录", ""]
    if not records:
        lines.append("暂无血缘记录。")
        return "\n".join(lines) + "\n"

    lines.append("| 时间 | 类型 | 产物 | 来源表 | 字段 | Query Hash | 口径 |")
    lines.append("|---|---|---|---|---|---|---|")
    for record in records:
        lines.append(
            f"| {record.created_at} | {record.artifact_type} | `{record.artifact_path}` | "
            f"{', '.join(record.source_tables)} | {', '.join(record.columns)} | "
            f"{', '.join(record.query_hashes)} | {', '.join(record.metric_scopes)} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="记录和查询数据血缘")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="记录产物血缘")
    record_parser.add_argument("--artifact", required=True, help="产物路径")
    record_parser.add_argument("--type", required=True, choices=["chart", "dashboard", "report", "export", "query"], help="产物类型")
    record_parser.add_argument("--tables", default="", help="来源表，逗号分隔")
    record_parser.add_argument("--files", default="", help="来源文件，逗号分隔")
    record_parser.add_argument("--columns", default="", help="使用字段，逗号分隔")
    record_parser.add_argument("--query", default="", help="SQL/query 文本；会记录 hash，不记录明文")
    record_parser.add_argument("--query-hash", default="", help="已计算的 query hash，逗号分隔")
    record_parser.add_argument("--metrics", default="", help="统计口径名称，逗号分隔")
    record_parser.add_argument("--generated-by", default="", help="生成指令或模块")
    record_parser.add_argument("--cwd", default="", help="执行目录")
    record_parser.add_argument("--notes", default="", help="备注")
    record_parser.add_argument("--lineage-path", default="", help="血缘 JSONL 路径")

    list_parser = subparsers.add_parser("list", help="查询血缘记录")
    list_parser.add_argument("--artifact", help="按产物路径筛选")
    list_parser.add_argument("--type", choices=["chart", "dashboard", "report", "export", "query"], help="按产物类型筛选")
    list_parser.add_argument("--table", help="按来源表筛选")
    list_parser.add_argument("--lineage-path", default="", help="血缘 JSONL 路径")
    list_parser.add_argument("--json", action="store_true", help="输出 JSON")

    args = parser.parse_args()

    if args.command == "record":
        query_hashes = _split_csv(args.query_hash)
        if args.query:
            query_hashes.append(hash_query(args.query))
        record = LineageRecord(
            artifact_path=str(Path(args.artifact).resolve()),
            artifact_type=args.type,
            source_tables=_split_csv(args.tables),
            source_files=_split_csv(args.files),
            columns=_split_csv(args.columns),
            query_hashes=query_hashes,
            metric_scopes=_split_csv(args.metrics),
            generated_by=args.generated_by,
            cwd=args.cwd or os.getcwd(),
            notes=args.notes,
        )
        path = record_lineage(record, args.lineage_path or None)
        print(f"✅ 血缘已记录: {path}")
        return

    records = find_lineage(args.artifact, args.type, args.table, args.lineage_path or None)
    if args.json:
        print(json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2))
    else:
        print(render_lineage_markdown(records))


if __name__ == "__main__":  # pragma: no cover
    main()
