"""
Polling Manager Module.

Provides scheduled polling for HTTP and database data sources:
- PollingConfig: Configuration for a polling job
- PollingManager: APScheduler-based polling orchestrator
- Automatic DuckDB import on each poll

Usage:
    from scripts.polling_manager import PollingManager, PollingConfig
    
    manager = PollingManager()
    manager.start()
    
    config = PollingConfig(
        source_type="http",
        source_name="api_data",
        interval_seconds=300,
        table_name="api_data",
        http_config={"url": "https://api.example.com/data", "format": "json"}
    )
    
    job_id = manager.add_job(config)
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from scripts.data_importer import init_meta_table
from scripts.text_config import parse_txt_config
from validators import quote_identifier, validate_table_name

logger = get_logger(__name__)


class PollingConfig(BaseModel):
    """Configuration for polling data sources."""
    source_type: Literal["http", "database"]
    source_name: str
    interval_seconds: int = Field(default=300, ge=10, le=86400)
    enabled: bool = Field(default=True)
    
    http_config: Optional[dict] = None
    db_profile: Optional[str] = None
    query: Optional[str] = None
    collection: Optional[str] = None
    table_name: str
    duckdb_path: str = Field(default="workspace.duckdb")

    @field_validator("table_name")
    @classmethod
    def validate_target_table(cls, value: str) -> str:
        return validate_table_name(value)


class PollingJob:
    """Single polling job with state tracking."""
    
    def __init__(self, config: PollingConfig, job_id: str):
        self.config = config
        self.job_id = job_id
        self.last_run: Optional[datetime] = None
        self.last_status: str = "pending"
        self.last_row_count: int = 0
        self.error_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "source_name": self.config.source_name,
            "source_type": self.config.source_type,
            "interval_seconds": self.config.interval_seconds,
            "enabled": self.config.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_status": self.last_status,
            "last_row_count": self.last_row_count,
            "error_count": self.error_count
        }


class PollingManager:
    """Manages scheduled polling for HTTP and database sources."""
    
    def __init__(self, db_path: str = "workspace.duckdb"):
        self.db_path = db_path
        self._jobs: Dict[str, PollingJob] = {}
        self._scheduler = None
        self._running = False
    
    def start(self) -> None:
        if self._running:
            return
        
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError as e:
            raise ImportError("Polling requires apscheduler. Install requirements-optional.txt.") from e

        self._scheduler = BackgroundScheduler()
        self._scheduler.start()
        self._running = True
        logger.info("Polling manager started")
    
    def stop(self) -> None:
        if not self._running or self._scheduler is None:
            return
        
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Polling manager stopped")
    
    def add_job(self, config: PollingConfig) -> str:
        import uuid
        job_id = str(uuid.uuid4())[:8]
        
        job = PollingJob(config, job_id)
        self._jobs[job_id] = job
        
        if config.enabled and self._running and self._scheduler:
            self._scheduler.add_job(
                self._run_poll,
                'interval',
                seconds=config.interval_seconds,
                id=job_id,
                args=[job_id],
                replace_existing=True
            )
            logger.info("Added polling job", job_id=job_id, source=config.source_name)
        
        return job_id
    
    def remove_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        
        if self._running and self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        
        del self._jobs[job_id]
        logger.info("Removed polling job", job_id=job_id)
        return True
    
    def get_job(self, job_id: str) -> Optional[PollingJob]:
        return self._jobs.get(job_id)
    
    def list_jobs(self) -> List[dict]:
        return [job.to_dict() for job in self._jobs.values()]
    
    def _run_poll(self, job_id: str) -> None:
        import asyncio
        
        job = self._jobs.get(job_id)
        if job is None:
            return
        
        try:
            if job.config.source_type == "http":
                row_count = asyncio.run(self._poll_http(job.config))
            else:
                row_count = asyncio.run(self._poll_database(job.config))
            
            job.last_run = datetime.now()
            job.last_status = "success"
            job.last_row_count = row_count
            job.error_count = 0
            
            logger.info(
                "Poll completed",
                job_id=job_id,
                source=job.config.source_name,
                row_count=row_count
            )
            
        except Exception as e:
            job.last_run = datetime.now()
            job.last_status = "error"
            job.error_count += 1
            
            logger.error(
                "Poll failed",
                job_id=job_id,
                source=job.config.source_name,
                error=str(e)
            )
    
    async def _poll_http(self, config: PollingConfig) -> int:
        from scripts.url_data_source import URLDataSource, URLDataSourceConfig
        
        http_cfg = config.http_config or {}
        
        url_config = URLDataSourceConfig(
            url=http_cfg.get("url", ""),
            format=http_cfg.get("format", "json"),
            table_name=config.table_name,
            auth=http_cfg.get("auth")
        )
        
        source = URLDataSource(url_config)
        records = await source.fetch_and_parse()
        
        return self._import_to_duckdb(records, config.table_name, config.duckdb_path)
    
    async def _poll_database(self, config: PollingConfig) -> int:
        from scripts.db_config import load_config
        from scripts.db_connector import create_connector
        
        db_config = load_config()
        
        if config.db_profile not in db_config.connections:
            raise ValueError(f"Database profile '{config.db_profile}' not found")
        
        profile = db_config.connections[config.db_profile]
        connector = create_connector(profile)
        
        try:
            if profile.type == "mongodb":
                if not config.collection:
                    raise ValueError("Collection required for MongoDB")
                return connector.execute_query_to_duckdb(
                    config.query or {},
                    table_name=config.table_name,
                    collection=config.collection,
                    db_path=config.duckdb_path
                )
            else:
                return connector.execute_query_to_duckdb(
                    config.query or "SELECT 1",
                    table_name=config.table_name,
                    db_path=config.duckdb_path
                )
        finally:
            connector.close()
    
    def _import_to_duckdb(self, records: List[dict], table_name: str, db_path: str) -> int:
        import duckdb
        
        if not records:
            return 0
        
        import pandas as pd
        df = pd.DataFrame(records)
        table_name = validate_table_name(table_name)
        table = quote_identifier(table_name)
        
        conn = duckdb.connect(db_path)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
            init_meta_table(conn)
            
            conn.execute("""
                INSERT OR REPLACE INTO _data_skill_meta 
                (file_name, table_name, import_time, last_used_time, source_type, source_path, row_count, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'polling', ?, ?, CURRENT_TIMESTAMP)
            """, [table_name, table_name, "polling", len(records)])
            
            return len(records)
        finally:
            conn.close()
    
    def refresh_now(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        
        self._run_poll(job_id)
        return True


def load_polling_config(config_path: str = "polling_config.txt") -> List[PollingConfig]:
    """Load polling configuration from txt file."""
    if not Path(config_path).exists():
        return []
    
    data = parse_txt_config(config_path)
    
    jobs = data.get("jobs", [])
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    return [PollingConfig(**item) for item in jobs]
