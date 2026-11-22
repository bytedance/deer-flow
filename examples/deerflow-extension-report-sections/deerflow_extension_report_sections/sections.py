"""Section storage and report assembly. No imports from DeerFlow host internals."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

ASSEMBLE_INDEX = 999
ASSEMBLE_TITLE = "__assemble__"

MAX_TITLE_CHARS = 200
MAX_CONTENT_CHARS = 24_000
# The host caps every plugin tool envelope at 64 KiB; leave room for the
# status text and JSON escaping before refusing an oversized assembly.
MAX_DOCUMENT_BYTES = 60_000

_DDL = """CREATE TABLE IF NOT EXISTS report_sections (
    owner TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    section_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (owner, thread_id, section_index)
)"""


def _norm_heading(text: str) -> str:
    """Whitespace- and marker-insensitive form for heading comparison."""
    return re.sub(r"[\s#]+", "", text)


def strip_duplicate_title_heading(content: str, title: str) -> str:
    """Drop a leading heading that restates the section title.

    Models tend to open each stored section with ``# <title>``; the assembler
    already emits ``## <title>`` for every non-outline section, so keeping
    both produced doubled headings throughout assembled reports.
    """
    stripped = content.lstrip()
    first_line, _, rest = stripped.partition("\n")
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", first_line)
    if match and _norm_heading(match.group(1)) == _norm_heading(title):
        return rest.lstrip("\n")
    return stripped


def assemble_document(rows: list[sqlite3.Row]) -> tuple[str, int]:
    """Build the final markdown document and report its body size.

    ``section_index`` 0 is the outline: it passes through unwrapped, so its own
    leading heading is the document title and must be kept. Every other
    section is preceded by one ``## <title>`` heading, and the section's own
    duplicate opening heading is removed first.
    """
    parts: list[str] = []
    total_chars = 0
    for row in rows:
        title = row["title"].strip()
        if row["section_index"] == 0:
            body = row["content"].lstrip()
        else:
            body = strip_duplicate_title_heading(row["content"], title)
        total_chars += len(body)
        if row["section_index"] == 0:
            parts.append(body)
        else:
            parts.append(f"\n\n## {title}\n\n{body}")
    return "".join(parts).strip() + "\n", total_chars


def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip())[:limit].strip("-")
    return slug or "report"


class SectionStore:
    """Plugin-owned per-user section data in a deployment-local SQLite file."""

    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be an absolute deployment-owned path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute(_DDL)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save(self, owner: str, thread_id: str, section_index: int, title: str, content: str) -> None:
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO report_sections (owner, thread_id, section_index, title, content)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (owner, thread_id, section_index)"
                " DO UPDATE SET title=excluded.title, content=excluded.content,"
                " created_at=CURRENT_TIMESTAMP",
                (owner, thread_id, section_index, title, content),
            )

    def load_sections(self, owner: str, thread_id: str) -> list[sqlite3.Row]:
        with closing(self.connect()) as db:
            return db.execute(
                "SELECT section_index, title, content FROM report_sections WHERE owner=? AND thread_id=? AND section_index<>? ORDER BY section_index",
                (owner, thread_id, ASSEMBLE_INDEX),
            ).fetchall()

    def assemble(self, owner: str, thread_id: str) -> tuple[str, str, int, int] | None:
        """Return ``(filename, document, section_count, total_chars)`` or None when empty."""
        rows = self.load_sections(owner, thread_id)
        if not rows:
            return None
        document, total_chars = assemble_document(rows)
        first = rows[0]
        topic = _slug(first["title"]) if first["section_index"] == 0 else "report"
        filename = f"report-{topic}.md"
        return filename, document, len(rows), total_chars
