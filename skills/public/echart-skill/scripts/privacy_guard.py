"""
Privacy Guard — Enterprise data privacy & security for Agent BI.

Provides automatic PII detection, column-level data masking, read-only
query enforcement, and audit logging. All data processing is local —
no data ever leaves the machine.

Capabilities:
    Column Classification — Auto-detect sensitive columns (phone, email, ID, etc.)
    Value Masking         — Partial redaction preserving data structure
    Read-Only Enforcement — Block DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE
    Audit Trail           — JSON-lines log of every query (logs/audit.log)
    HTML Data Protection  — Strip raw datasets from chart output when sensitive

Architecture:
    SensitivePatterns → PrivacyGuard → database.execute_query() interceptor

Usage:
    from scripts.privacy_guard import PrivacyGuard

    guard = PrivacyGuard()
    guard.enforce_read_only("DROP TABLE users")  # raises ValueError
    result = guard.classify_columns("orders", ["phone", "name", "salary"])
    masked = guard.mask_rows(rows, result)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Classification levels (ordered: public < internal < sensitive < restricted)
# ---------------------------------------------------------------------------

CLASSIFICATION_LEVELS = {
    "public":     0,
    "internal":   1,
    "sensitive":  2,
    "restricted": 3,
}

def _max_level(a: str, b: str) -> str:
    """Return the higher of two classification levels."""
    return a if CLASSIFICATION_LEVELS.get(a, 0) >= CLASSIFICATION_LEVELS.get(b, 0) else b


# ---------------------------------------------------------------------------
# Sensitive column detection patterns (Chinese + English)
# ---------------------------------------------------------------------------

@dataclass
class ClassificationRule:
    """A single sensitive column detection rule."""
    name: str
    pattern: re.Pattern
    classification: str       # "sensitive" | "restricted"
    mask_key: str             # Key into MASK_FUNCTIONS


# Ordered list — first match wins
SENSITIVE_PATTERNS: list[ClassificationRule] = [
    # === Restricted ===
    ClassificationRule("id_card",   re.compile(r"身份证|身份号|id_card|id_number|idcard",   re.I), "restricted", "mask_id_card"),
    ClassificationRule("bank_card", re.compile(r"银行卡|卡号|bank_card|bankcard|card_number|信用卡|credit_card|cc_number", re.I), "restricted", "mask_bank_card"),
    ClassificationRule("password",  re.compile(r"密码|口令|password|pwd|passwd|secret",       re.I), "restricted", "mask_password"),
    ClassificationRule("salary",    re.compile(r"工资|薪资|收入|年薪|月薪|salary|wage|income|奖金|bonus", re.I), "restricted", "mask_salary"),
    ClassificationRule("api_key",   re.compile(r"密钥|token|secret_key|api_key|private_key|access_key", re.I), "restricted", "mask_password"),
    ClassificationRule("ssn",       re.compile(r"社保|社保号|ssn|social_security|公积金",        re.I), "restricted", "mask_id_card"),

    # === Sensitive ===
    ClassificationRule("phone",     re.compile(r"手机|电话|联系电话|联系方式|phone|mobile|tel|cell", re.I), "sensitive", "mask_phone"),
    ClassificationRule("email",     re.compile(r"邮箱|电子邮件|邮件|email|e.mail|mailbox",        re.I), "sensitive", "mask_email"),
    ClassificationRule("address",   re.compile(r"地址|家庭住?址|详细地址|收货地址|address|addr|住址",  re.I), "sensitive", "mask_address"),
    ClassificationRule("real_name", re.compile(r"姓名|real_name|full_name|真实姓名|联系人|contact_name|客户名称", re.I), "sensitive", "mask_real_name"),
]


# ---------------------------------------------------------------------------
# Masking functions
# ---------------------------------------------------------------------------

def mask_phone(val: Any) -> str:
    """13812341234 → 138****1234"""
    s = str(val).strip()
    if len(s) >= 7:
        return s[:3] + "****" + s[-4:]
    return s[:3] + "****" if len(s) > 3 else "****"


def mask_email(val: Any) -> str:
    """user@domain.com → u***@domain.com"""
    s = str(val).strip()
    if "@" in s:
        local, domain = s.split("@", 1)
        masked_local = local[0] + "***" if local else "***"
        return f"{masked_local}@{domain}"
    return "***"


def mask_id_card(val: Any) -> str:
    """320106199001011234 → 3201**********1234"""
    s = str(val).strip()
    if len(s) >= 8:
        return s[:4] + "*" * (len(s) - 8) + s[-4:]
    return "*" * len(s) if s else "****"


def mask_bank_card(val: Any) -> str:
    """6222021234561234 → 6222********1234"""
    s = str(val).strip()
    if len(s) >= 8:
        return s[:4] + "*" * (len(s) - 8) + s[-4:]
    return "*" * len(s) if s else "****"


def mask_salary(val: Any) -> str:
    """Any salary value → [REDACTED]"""
    return "[REDACTED]"


def mask_password(val: Any) -> str:
    """Any password → ********"""
    return "********"


def mask_address(val: Any) -> str:
    """北京市海淀区中关村大街1号 → 北京市****"""
    s = str(val).strip()
    if len(s) >= 4:
        return s[:4] + "****"
    return s[:2] + "****" if len(s) > 2 else "****"


def mask_real_name(val: Any) -> str:
    """张三 → 张*"""
    s = str(val).strip()
    if len(s) <= 1:
        return "*"
    return s[0] + "*" + (s[-1] if len(s) > 2 else "")


def mask_generic(val: Any) -> str:
    """Fallback: replace with asterisks."""
    return "****"


# Lookup table
MASK_FUNCTIONS: dict[str, Callable[[Any], str]] = {
    "mask_phone":     mask_phone,
    "mask_email":     mask_email,
    "mask_id_card":   mask_id_card,
    "mask_bank_card": mask_bank_card,
    "mask_salary":    mask_salary,
    "mask_password":  mask_password,
    "mask_address":   mask_address,
    "mask_real_name": mask_real_name,
    "mask_generic":   mask_generic,
}


# ---------------------------------------------------------------------------
# Read-only enforcement — DDL/DML tokens to block
# ---------------------------------------------------------------------------

_BLOCKED_TOKENS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
    "CREATE", "REPLACE", "DETACH", "ATTACH", "EXPORT", "IMPORT",
    "COPY", "GRANT", "REVOKE",
}

# These keywords are safe even though they start with a blocked token
_SAFE_PREFIXES = {"CREATE TABLE IF NOT EXISTS", "CREATE VIEW", "CREATE OR REPLACE VIEW"}


def _is_blocked_query(query: str) -> tuple[bool, str]:
    """Check if a query is a DDL/DML that should be blocked.

    Returns (is_blocked, token_that_triggered).
    """
    # Normalize: strip comments, collapse whitespace
    normalized = re.sub(r"--.*?$", "", query, flags=re.MULTILINE)
    normalized = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL)
    normalized = " ".join(normalized.split()).strip().upper()

    if not normalized:
        return False, ""

    first_token = normalized.split()[0]

    if first_token not in _BLOCKED_TOKENS:
        return False, ""

    # Check safe prefixes
    for safe in _SAFE_PREFIXES:
        if normalized.startswith(safe.upper()):
            return False, ""

    return True, first_token


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ColumnClassification:
    """Classification result for one column."""
    name: str
    rule_name: str           # Which rule matched ("" if none)
    classification: str       # "public"|"internal"|"sensitive"|"restricted"
    is_sensitive: bool
    mask_key: str             # Key into MASK_FUNCTIONS ("" if no masking)


@dataclass
class TableClassification:
    """Classification result for a set of columns."""
    table: str
    columns: list[ColumnClassification]
    has_sensitive_data: bool
    max_classification: str

    @property
    def sensitive_columns(self) -> list[ColumnClassification]:
        return [c for c in self.columns if c.is_sensitive]


@dataclass
class AuditRecord:
    """Single audit log entry."""
    timestamp: str
    table: str
    columns_accessed: list[str]
    query_hash: str           # SHA-256 prefix, 16 hex chars
    row_count: int
    masked: bool
    max_classification: str
    is_mutation: bool
    blocked_token: str         # Non-empty if mutation was blocked


# ---------------------------------------------------------------------------
# PrivacyGuard
# ---------------------------------------------------------------------------

class PrivacyGuard:
    """Enterprise privacy guard — classify, mask, audit, enforce.

    Defaults are sensible for most enterprise scenarios. Disable features
    via echart_config.json's privacy section.
    """

    AUDIT_LOG = "logs/audit.log"
    MAX_AUDIT_SIZE = 100 * 1024 * 1024  # 100 MB rotation

    def __init__(self, enabled: bool = True, read_only: bool = True,
                 audit_enabled: bool = True, mask_pii: bool = True,
                 html_redact_threshold: str = "sensitive",
                 audit_log_path: str = ""):
        """Initialize the privacy guard.

        Args:
            enabled: Master switch. When False, all checks are no-ops.
            read_only: Block DDL/DML queries.
            audit_enabled: Write audit log entries.
            mask_pii: Apply column-level masking.
            html_redact_threshold: Classification level at which HTML data is stripped.
            audit_log_path: Custom audit log path (default: logs/audit.log).
        """
        self.enabled = enabled
        self.read_only = read_only
        self.audit_enabled = audit_enabled
        self.mask_pii = mask_pii
        self.html_redact_threshold = html_redact_threshold
        self._audit_log_path = audit_log_path or self.AUDIT_LOG

    # ------------------------------------------------------------------
    # Read-Only Enforcement
    # ------------------------------------------------------------------

    def enforce_read_only(self, query: str) -> None:
        """Raise ValueError if query contains blocked DDL/DML operations.

        Args:
            query: SQL query string to check.

        Raises:
            ValueError: If query contains a blocked operation.
        """
        if not self.enabled or not self.read_only:
            return

        is_blocked, token = _is_blocked_query(query)
        if is_blocked:
            msg = (
                f"❌ 数据库处于只读模式，禁止执行 {token} 操作。\n"
                f"   如需修改数据，请在 echart_config.json 中设置 "
                f"privacy.read_only = false"
            )
            logger.warning("只读模式拦截", token=token, query=query[:100])
            raise ValueError(msg)

    # ------------------------------------------------------------------
    # Column Classification
    # ------------------------------------------------------------------

    def classify_columns(self, table: str, columns: list[str]) -> TableClassification:
        """Classify each column by sensitivity level.

        Matches column names against SENSITIVE_PATTERNS. First match wins.

        Args:
            table: Table name (for labeling).
            columns: List of column names to classify.

        Returns:
            TableClassification with per-column results.
        """
        if not self.enabled:
            # All columns are "public" when guard is disabled
            pubs = [ColumnClassification(c, "", "public", False, "") for c in columns]
            return TableClassification(table, pubs, False, "public")

        results = []
        max_level = "public"

        for col_name in columns:
            matched = False
            for rule in SENSITIVE_PATTERNS:
                if rule.pattern.search(col_name):
                    cc = ColumnClassification(
                        name=col_name,
                        rule_name=rule.name,
                        classification=rule.classification,
                        is_sensitive=True,
                        mask_key=rule.mask_key,
                    )
                    results.append(cc)
                    max_level = _max_level(max_level, rule.classification)
                    matched = True
                    break

            if not matched:
                results.append(ColumnClassification(
                    name=col_name,
                    rule_name="",
                    classification="internal",
                    is_sensitive=False,
                    mask_key="",
                ))
                max_level = _max_level(max_level, "internal")

        has_sensitive = any(c.is_sensitive for c in results)
        return TableClassification(table, results, has_sensitive, max_level)

    # ------------------------------------------------------------------
    # Value Masking
    # ------------------------------------------------------------------

    def mask_rows(self, rows: list[dict],
                  classification: TableClassification) -> list[dict]:
        """Apply column-level masking to every row.

        Only masks columns where is_sensitive=True and mask_key is set.

        Args:
            rows: Query result rows as list of dicts.
            classification: Column classification from classify_columns().

        Returns:
            New list with masked values (original rows are NOT modified).
        """
        if not self.enabled or not self.mask_pii:
            return rows

        if not classification.has_sensitive_data:
            return rows

        # Build a lookup: column_name → mask_function
        mask_map: dict[str, Callable[[Any], str]] = {}
        for cc in classification.sensitive_columns:
            if cc.mask_key and cc.mask_key in MASK_FUNCTIONS:
                mask_map[cc.name] = MASK_FUNCTIONS[cc.mask_key]

        if not mask_map:
            return rows

        masked_rows = []
        for row in rows:
            masked = dict(row)
            for col_name, mask_func in mask_map.items():
                if col_name in masked and masked[col_name] is not None:
                    masked[col_name] = mask_func(masked[col_name])
            masked_rows.append(masked)

        return masked_rows

    # ------------------------------------------------------------------
    # Audit Logging
    # ------------------------------------------------------------------

    def audit(self, record: AuditRecord) -> None:
        """Write an audit record to the audit log.

        Rotates the log file if it exceeds MAX_AUDIT_SIZE.

        Args:
            record: AuditRecord to write.
        """
        if not self.enabled or not self.audit_enabled:
            return

        try:
            self._ensure_audit_log_dir()
            self._rotate_if_needed()

            entry = json.dumps({
                "ts":   record.timestamp,
                "tbl":  record.table,
                "cols": record.columns_accessed,
                "q":    record.query_hash,
                "n":    record.row_count,
                "mask": record.masked,
                "lv":   record.max_classification,
                "mut":  record.is_mutation,
                "blk":  record.blocked_token or "",
            }, ensure_ascii=False)

            with open(self._audit_log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception as e:
            logger.warning("审计日志写入失败", error=str(e))

    # ------------------------------------------------------------------
    # High-Level Guard Pipeline
    # ------------------------------------------------------------------

    def guard_query(self, query: str, table: str,
                    columns: list[str], rows: list[dict]) -> list[dict]:
        """Run the full privacy pipeline on query results.

        enforce_read_only → classify → mask → audit.

        Call this AFTER executing the query but BEFORE returning results.

        Args:
            query: The SQL query string.
            table: Table name (inferred or explicit).
            columns: Column names from the result set.
            rows: Query result rows.

        Returns:
            Masked rows (or original rows if no masking needed).
        """
        # Step 1: Read-only check (raises ValueError if blocked)
        self.enforce_read_only(query)

        # Step 2: Classify columns
        classification = self.classify_columns(table, columns)

        # Step 3: Mask sensitive values
        masked_rows = self.mask_rows(rows, classification)

        # Step 4: Audit
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        is_blocked, blocked_token = _is_blocked_query(query)
        self.audit(AuditRecord(
            timestamp=datetime.now().isoformat(),
            table=table,
            columns_accessed=columns,
            query_hash=query_hash,
            row_count=len(rows),
            masked=classification.has_sensitive_data,
            max_classification=classification.max_classification,
            is_mutation=is_blocked,
            blocked_token=blocked_token if is_blocked else "",
        ))

        return masked_rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_audit_log_dir(self) -> None:
        os.makedirs(os.path.dirname(self._audit_log_path), exist_ok=True)

    def _rotate_if_needed(self) -> None:
        """Rotate audit log if it exceeds MAX_AUDIT_SIZE."""
        try:
            if os.path.getsize(self._audit_log_path) > self.MAX_AUDIT_SIZE:
                backup = f"{self._audit_log_path}.{int(time.time())}"
                os.rename(self._audit_log_path, backup)
                logger.info("审计日志已轮转", backup=backup)
        except (OSError, FileNotFoundError):
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Privacy Guard — Data classification, masking & audit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Classify columns in a table
  python scripts/privacy_guard.py classify --table orders

  # Scan all tables for sensitive data
  python scripts/privacy_guard.py scan --db workspace.duckdb

  # View recent audit log
  python scripts/privacy_guard.py audit --lines 20

  # Mask a table and export
  python scripts/privacy_guard.py mask --table users --output users_safe.csv
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- classify ---
    classify_parser = subparsers.add_parser("classify", help="Classify columns in a table")
    classify_parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    classify_parser.add_argument("--table", required=True, help="Table name")

    # --- scan ---
    scan_parser = subparsers.add_parser("scan", help="Scan all tables for sensitive data")
    scan_parser.add_argument("--db", default="workspace.duckdb", help="Database path")

    # --- mask ---
    mask_parser = subparsers.add_parser("mask", help="Mask sensitive data and export")
    mask_parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    mask_parser.add_argument("--table", required=True, help="Table name")
    mask_parser.add_argument("--output", required=True, help="Output file path (.csv)")

    # --- audit ---
    audit_parser = subparsers.add_parser("audit", help="View audit log")
    audit_parser.add_argument("--lines", type=int, default=50, help="Number of lines to show")
    audit_parser.add_argument("--table", help="Filter by table name")

    args = parser.parse_args()

    if args.command == "classify":
        from database import get_repository
        repo = get_repository(args.db)
        guard = PrivacyGuard()

        # Get columns via DESCRIBE
        cols_info = repo.execute_query(f'DESCRIBE "{args.table}"')
        columns = [r["column_name"] for r in cols_info]
        result = guard.classify_columns(args.table, columns)

        print(f"\n📊 表 '{args.table}' 列分类结果:\n")
        print(f"{'列名':<25} {'分级':<12} {'敏感':<6} {'规则'}")
        print("-" * 65)
        for cc in result.columns:
            flag = "⚠️" if cc.is_sensitive else "✅"
            print(f"{cc.name:<25} {cc.classification:<12} {flag:<6} {cc.rule_name}")
        print(f"\n最高分级: {result.max_classification}")
        if result.sensitive_columns:
            print(f"敏感列: {', '.join(c.name for c in result.sensitive_columns)}")

    elif args.command == "scan":
        from database import get_repository
        repo = get_repository(args.db)
        guard = PrivacyGuard()

        tables_info = repo.execute_query("SELECT table_name FROM information_schema.tables WHERE table_schema='main'")
        tables = [r["table_name"] for r in tables_info]

        print(f"\n🔍 扫描 {len(tables)} 个表...\n")
        found_any = False
        for tbl in tables:
            cols_info = repo.execute_query(f'DESCRIBE "{tbl}"')
            columns = [r["column_name"] for r in cols_info]
            result = guard.classify_columns(tbl, columns)
            if result.has_sensitive_data:
                found_any = True
                sensitive = [c.name for c in result.sensitive_columns]
                print(f"  ⚠️  {tbl}: {result.max_classification} — {', '.join(sensitive)}")

        if not found_any:
            print("  ✅ 未发现敏感数据列")

    elif args.command == "mask":
        from database import get_repository
        repo = get_repository(args.db)
        guard = PrivacyGuard()

        cols_info = repo.execute_query(f'DESCRIBE "{args.table}"')
        columns = [r["column_name"] for r in cols_info]
        classification = guard.classify_columns(args.table, columns)

        if not classification.has_sensitive_data:
            print(f"✅ 表 '{args.table}' 无敏感列，无需脱敏")
            return

        rows = repo.execute_query(f'SELECT * FROM "{args.table}"')
        masked_rows = guard.mask_rows(rows, classification)

        import csv
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(masked_rows)

        print(f"✅ 已脱敏导出到: {args.output}")
        print(f"   敏感列: {', '.join(c.name for c in classification.sensitive_columns)}")

    elif args.command == "audit":
        guard = PrivacyGuard()
        log_path = guard._audit_log_path

        if not os.path.exists(log_path):
            print("📭 暂无审计日志")
            return

        lines = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if args.table and entry.get("tbl") != args.table:
                        continue
                    lines.append(entry)
                except json.JSONDecodeError:
                    continue

        lines = lines[-args.lines:]
        print(f"\n📜 审计日志 (最近 {len(lines)} 条):\n")
        print(f"{'时间':<22} {'表':<15} {'行数':<8} {'脱敏':<5} {'分级':<12} {'变更'}")
        print("-" * 80)
        for e in lines:
            ts = e.get("ts", "")[:19]
            tbl = e.get("tbl", "")[:14]
            n = str(e.get("n", ""))
            mask = "✅" if e.get("mask") else "—"
            lv = e.get("lv", "")
            mut = "🔴" if e.get("blk") else ("🟡" if e.get("mut") else "—")
            print(f"{ts:<22} {tbl:<15} {n:<8} {mask:<5} {lv:<12} {mut}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
