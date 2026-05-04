"""PostgreSQL storage backend for token usage records.

Provides an alternative to JSON-file storage when PostgreSQL is available.
Falls back gracefully to JSON storage when the driver is not installed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from deerflow.config.paths import get_paths
from deerflow.cost.storage import UsageRecord, UsageStorage

logger = logging.getLogger(__name__)


class PgUsageStorage:
    """PostgreSQL-backed usage storage with the same interface as UsageStorage.

    Requires ``psycopg[binary]`` or ``asyncpg`` to be installed.
    Falls back to JSON-file storage when PostgreSQL is unavailable.
    """

    def __init__(
        self,
        dsn: str = "",
        *,
        base_dir: Path | None = None,
    ) -> None:
        self._dsn = dsn
        self._fallback = UsageStorage(base_dir=base_dir)
        self._pool: object | None = None
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._check_connection()
        return self._available

    def _check_connection(self) -> bool:
        if not self._dsn:
            return False
        try:
            import psycopg

            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            logger.info("PostgreSQL storage backend connected")
            return True
        except ImportError:
            logger.warning("psycopg not installed — falling back to JSON storage")
            return False
        except Exception:
            logger.warning("PostgreSQL connection failed — falling back to JSON storage", exc_info=True)
            return False

    def _ensure_tables(self) -> None:
        try:
            import psycopg

            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS token_usage (
                            id BIGSERIAL PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            thread_id TEXT,
                            model_name TEXT NOT NULL,
                            input_tokens INTEGER NOT NULL DEFAULT 0,
                            output_tokens INTEGER NOT NULL DEFAULT 0,
                            total_tokens INTEGER NOT NULL DEFAULT 0,
                            cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0,
                            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_usage_tenant_ts
                        ON token_usage (tenant_id, timestamp DESC)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_usage_tenant_date
                        ON token_usage (tenant_id, (timestamp::DATE))
                    """)
                    conn.commit()
        except Exception:
            logger.exception("Failed to ensure PostgreSQL tables")

    def add_record(self, record: UsageRecord) -> None:
        if not self.available:
            self._fallback.add_record(record)
            return

        self._ensure_tables()
        try:
            import psycopg

            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO token_usage
                            (tenant_id, thread_id, model_name, input_tokens,
                             output_tokens, total_tokens, cost_usd, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            record.tenant_id,
                            record.thread_id,
                            record.model_name,
                            record.input_tokens,
                            record.output_tokens,
                            record.total_tokens,
                            record.cost_usd,
                            record.timestamp,
                        ),
                    )
                    conn.commit()
        except Exception:
            logger.exception("Failed to write usage record to PostgreSQL — falling back to JSON")
            self._fallback.add_record(record)

    def query(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        model_name: str | None = None,
    ) -> list[UsageRecord]:
        if not self.available:
            return self._fallback.query(start_date=start_date, end_date=end_date, model_name=model_name)

        try:
            import psycopg

            conditions: list[str] = []
            params: list = []

            if start_date:
                conditions.append("timestamp >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("timestamp <= %s")
                params.append(end_date)
            if model_name:
                conditions.append("model_name = %s")
                params.append(model_name)

            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            query = f"SELECT tenant_id, thread_id, model_name, input_tokens, output_tokens, total_tokens, cost_usd, timestamp::TEXT FROM token_usage{where} ORDER BY timestamp DESC"

            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

            return [
                UsageRecord(
                    timestamp=row[7],
                    tenant_id=row[0],
                    thread_id=row[1],
                    model_name=row[2],
                    input_tokens=row[3],
                    output_tokens=row[4],
                    total_tokens=row[5],
                    cost_usd=float(row[6]),
                )
                for row in rows
            ]
        except Exception:
            logger.exception("Failed to query PostgreSQL — falling back to JSON")
            return self._fallback.query(start_date=start_date, end_date=end_date, model_name=model_name)

    def get_daily_total(self, date_str: str) -> float:
        if not self.available:
            return self._fallback.get_daily_total(date_str)
        records = self.query(start_date=date_str, end_date=date_str + "T23:59:59")
        return sum(r.cost_usd for r in records)

    def get_monthly_total(self, year_month: str) -> float:
        if not self.available:
            return self._fallback.get_monthly_total(year_month)
        start = f"{year_month}-01"
        end = f"{year_month}-31"
        records = self.query(start_date=start, end_date=end)
        return sum(r.cost_usd for r in records)

    def get_today_total(self) -> float:
        if not self.available:
            return self._fallback.get_today_total()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.get_daily_total(today)

    def get_current_month_total(self) -> float:
        if not self.available:
            return self._fallback.get_current_month_total()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self.get_monthly_total(month)

    def get_total_tokens_today(self) -> int:
        if not self.available:
            return self._fallback.get_total_tokens_today()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        records = self.query(start_date=today)
        return sum(r.total_tokens for r in records)

    def get_total_tokens_month(self) -> int:
        if not self.available:
            return self._fallback.get_total_tokens_month()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        records = self.query(start_date=f"{month}-01")
        return sum(r.total_tokens for r in records)
