# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, Any, Optional
import psycopg

class PostgreSQLMockInstance:
    """Utility class for managing PostgreSQL mock instances."""
    
    def __init__(self, database_name: str = "test_db"):
        self.database_name = database_name
        self.temp_dir: Optional[Path] = None
        self.mock_connection: Optional[MagicMock] = None
        self.mock_data: Dict[str, Any] = {}
        self._setup_mock_data()
    
    def _setup_mock_data(self):
        """Initialize mock data storage."""
        self.mock_data = {
            "chat_streams": {},  # thread_id -> record
            "table_exists": False,
            "connection_active": True
        }
    
    def connect(self) -> MagicMock:
        """Create a mock PostgreSQL connection."""
        self.mock_connection = MagicMock()
        self._setup_mock_methods()
        return self.mock_connection
    
    def _setup_mock_methods(self):
        """Setup mock methods for PostgreSQL operations."""
        if not self.mock_connection:
            return
            
        # Mock cursor context manager
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        
        # Setup cursor operations
        mock_cursor.execute = MagicMock(side_effect=self._mock_execute)
        mock_cursor.fetchone = MagicMock(side_effect=self._mock_fetchone)
        mock_cursor.rowcount = 0
        
        # Setup connection operations
        self.mock_connection.cursor = MagicMock(return_value=mock_cursor)
        self.mock_connection.commit = MagicMock()
        self.mock_connection.rollback = MagicMock()
        self.mock_connection.close = MagicMock()
        
        # Store cursor for external access
        self._mock_cursor = mock_cursor
    
    def _mock_execute(self, sql: str, params=None):
        """Mock SQL execution."""
        sql_upper = sql.upper().strip()
        
        if "CREATE TABLE" in sql_upper:
            self.mock_data["table_exists"] = True
            self._mock_cursor.rowcount = 0
            
        elif "SELECT" in sql_upper and "chat_streams" in sql_upper:
            # Mock SELECT query
            if params and len(params) > 0:
                thread_id = params[0]
                if thread_id in self.mock_data["chat_streams"]:
                    self._mock_cursor._fetch_result = self.mock_data["chat_streams"][thread_id]
                else:
                    self._mock_cursor._fetch_result = None
            else:
                self._mock_cursor._fetch_result = None
                
        elif "UPDATE" in sql_upper and "chat_streams" in sql_upper:
            # Mock UPDATE query
            if params and len(params) >= 2:
                messages, thread_id = params[0], params[1]
                if thread_id in self.mock_data["chat_streams"]:
                    self.mock_data["chat_streams"][thread_id] = {
                        "id": thread_id,
                        "thread_id": thread_id,
                        "messages": messages
                    }
                    self._mock_cursor.rowcount = 1
                else:
                    self._mock_cursor.rowcount = 0
                    
        elif "INSERT" in sql_upper and "chat_streams" in sql_upper:
            # Mock INSERT query
            if params and len(params) >= 2:
                thread_id, messages = params[0], params[1]
                self.mock_data["chat_streams"][thread_id] = {
                    "id": thread_id,
                    "thread_id": thread_id,
                    "messages": messages
                }
                self._mock_cursor.rowcount = 1
    
    def _mock_fetchone(self):
        """Mock fetchone operation."""
        return getattr(self._mock_cursor, '_fetch_result', None)
    
    def disconnect(self):
        """Cleanup mock connection."""
        if self.mock_connection:
            self.mock_connection.close()
        self._setup_mock_data()  # Reset data
    
    def reset_data(self):
        """Reset all mock data."""
        self._setup_mock_data()
    
    def get_table_count(self, table_name: str) -> int:
        """Get record count in a table."""
        if table_name == "chat_streams":
            return len(self.mock_data["chat_streams"])
        return 0
    
    def create_test_data(self, table_name: str, records: list):
        """Insert test data into a table."""
        if table_name == "chat_streams":
            for record in records:
                thread_id = record.get("thread_id")
                if thread_id:
                    self.mock_data["chat_streams"][thread_id] = record

@pytest.fixture
def mock_postgresql():
    """Create a PostgreSQL mock instance."""
    instance = PostgreSQLMockInstance()
    instance.connect()
    yield instance
    instance.disconnect()

@pytest.fixture
def clean_mock_postgresql():
    """Create a clean PostgreSQL mock instance that resets between tests."""
    instance = PostgreSQLMockInstance()
    instance.connect()
    instance.reset_data()
    yield instance
    instance.disconnect()