"""
Database Connector Module.

Provides database connection and query execution for external databases:
- DatabaseConnector: Abstract base class for database connections
- SQLConnector: SQLAlchemy-based connector for MySQL and PostgreSQL

Usage:
    from scripts.db_connector import SQLConnector
    from scripts.db_config import load_config

    config = load_config()
    connector = SQLConnector(config.connections["my_mysql"])
    
    # Execute query
    results = connector.execute_query("SELECT * FROM users LIMIT 10")
    
    # Import to DuckDB
    row_count = connector.execute_query_to_duckdb(
        "SELECT * FROM orders WHERE date > '2024-01-01'",
        table_name="recent_orders"
    )
    
    connector.close()
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Union
import json
import re

import duckdb
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from scripts.db_config import ConnectionProfile
from scripts.data_importer import init_meta_table
from validators import quote_identifier, validate_table_name

logger = get_logger(__name__)

# Constants
DEFAULT_CHUNK_SIZE = 10000
DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_OVERFLOW = 10


class DatabaseConnector(ABC):
    """Abstract base class for database connectors.
    
    Defines the interface for database connection and query execution.
    All concrete connectors must implement these methods.
    """
    
    def __init__(self, config: ConnectionProfile):
        """Initialize connector with configuration.
        
        Args:
            config: Connection profile with database credentials
        """
        self.config = config
        self._connected = False
    
    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the database.
        
        Raises:
            ConnectionError: If connection fails
        """
        pass
    
    @abstractmethod
    def execute_query(
        self, 
        query: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results.
        
        Args:
            query: SQL query string
            params: Optional query parameters
            
        Returns:
            List of dictionaries, each representing a row
            
        Raises:
            QueryError: If query execution fails
        """
        pass
    
    @abstractmethod
    def execute_query_to_duckdb(
        self,
        query: str,
        table_name: str,
        db_path: str = "workspace.duckdb",
        chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> int:
        """Execute query and import results to DuckDB.
        
        Args:
            query: SQL query string
            table_name: Target table name in DuckDB
            db_path: Path to DuckDB database file
            chunk_size: Number of rows per chunk for streaming
            
        Returns:
            Number of rows imported
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""
        pass
    
    @abstractmethod
    def test_connection(self) -> bool:
        """Test if connection is valid.
        
        Returns:
            True if connection works, False otherwise
        """
        pass


class SQLConnector(DatabaseConnector):
    """SQLAlchemy-based connector for SQL databases.
    
    Supports MySQL and PostgreSQL via SQLAlchemy Core.
    Uses connection pooling for efficient query execution.
    """
    
    def __init__(self, config: ConnectionProfile):
        """Initialize SQL connector.
        
        Args:
            config: Connection profile with database credentials
        """
        super().__init__(config)
        self._engine: Optional[Any] = None
        self._connection: Optional[Any] = None
        self._connection_string = self._build_connection_string()
    
    def _build_connection_string(self) -> str:
        """Build SQLAlchemy connection string from config.
        
        Returns:
            SQLAlchemy-compatible connection string
        """
        return self.config.get_connection_string()
    
    def connect(self) -> None:
        """Establish connection to the database.
        
        Creates SQLAlchemy engine with connection pooling.
        
        Raises:
            ConnectionError: If connection fails
        """
        if self._connected and self._engine is not None:
            return
        
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.exc import SQLAlchemyError
            from sqlalchemy.pool import QueuePool

            logger.info(
                "Connecting to database",
                db_type=self.config.type,
                timeout=self.config.timeout
            )
            
            # Create engine with connection pooling
            self._engine = create_engine(
                self._connection_string,
                poolclass=QueuePool,
                pool_size=DEFAULT_POOL_SIZE,
                max_overflow=DEFAULT_MAX_OVERFLOW,
                pool_timeout=self.config.timeout,
                pool_pre_ping=True,  # Verify connections before use
                echo=False  # Set True for SQL debugging
            )
            
            # Test connection
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self._connected = True
            logger.info("Database connection established", db_type=self.config.type)
            
        except ImportError as e:
            raise ImportError("External SQL connections require SQLAlchemy and a database driver. Install requirements-optional.txt.") from e
        except ImportError as e:
            raise ImportError("External SQL connections require SQLAlchemy and a database driver. Install requirements-optional.txt.") from e
        except SQLAlchemyError as e:
            error_msg = str(e)
            # Mask any credentials in error message
            if "@" in error_msg and "://" in error_msg:
                error_msg = error_msg.split("://")[0] + "://***@***"
            logger.error("Database connection failed", error=error_msg)
            raise ConnectionError(f"Failed to connect to database: {error_msg}") from e
    
    def execute_query(
        self, 
        query: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results.
        
        Args:
            query: SQL query string
            params: Optional query parameters for parameterized queries
            
        Returns:
            List of dictionaries, each representing a row with column names as keys
            
        Raises:
            RuntimeError: If not connected
            ValueError: If query execution fails
        """
        if not self._connected or self._engine is None:
            self.connect()
        
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import SQLAlchemyError

            logger.debug("Executing query", query_preview=query[:100] + "..." if len(query) > 100 else query)
            
            with self._engine.connect() as conn:
                # Use server-side cursor for large results
                result = conn.execute(text(query), params or {})
                
                # Get column names
                columns = list(result.keys()) if result.returns_rows else []
                
                # Fetch all rows and convert to dicts
                rows = []
                for row in result:
                    row_dict = dict(zip(columns, row))
                    rows.append(row_dict)
                
                logger.info("Query executed", row_count=len(rows))
                return rows
                
        except ImportError as e:
            raise ImportError("External SQL connections require SQLAlchemy and a database driver. Install requirements-optional.txt.") from e
        except SQLAlchemyError as e:
            error_msg = str(e)
            logger.error("Query execution failed", error=error_msg, query=query[:200])
            raise ValueError(f"Query execution failed: {error_msg}") from e
    
    def execute_query_stream(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> Iterator[List[Dict[str, Any]]]:
        """Execute query and yield results in chunks.
        
        Uses server-side cursor for memory-efficient streaming.
        
        Args:
            query: SQL query string
            params: Optional query parameters
            chunk_size: Number of rows per chunk
            
        Yields:
            Lists of dictionaries, each representing a chunk of rows
        """
        if not self._connected or self._engine is None:
            self.connect()
        
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import SQLAlchemyError

            with self._engine.connect() as conn:
                # Enable streaming results
                conn = conn.execution_options(stream_results=True)
                result = conn.execute(text(query), params or {})
                
                columns = list(result.keys()) if result.returns_rows else []
                
                chunk = []
                for row in result:
                    row_dict = dict(zip(columns, row))
                    chunk.append(row_dict)
                    
                    if len(chunk) >= chunk_size:
                        yield chunk
                        chunk = []
                
                if chunk:
                    yield chunk
                    
        except SQLAlchemyError as e:
            error_msg = str(e)
            logger.error("Stream query failed", error=error_msg)
            raise ValueError(f"Stream query failed: {error_msg}") from e
    
    def execute_query_to_duckdb(
        self,
        query: str,
        table_name: str,
        db_path: str = "workspace.duckdb",
        chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> int:
        """Execute query and import results to DuckDB.
        
        Streams results to avoid memory issues with large datasets.
        Tracks import metadata in _data_skill_meta table.
        
        Args:
            query: SQL query string
            table_name: Target table name in DuckDB
            db_path: Path to DuckDB database file
            chunk_size: Number of rows per chunk for streaming
            
        Returns:
            Total number of rows imported
        """
        logger.info(
            "Starting DuckDB import",
            table_name=table_name,
            source_db=self.config.type
        )
        table_name = validate_table_name(table_name)
        table = quote_identifier(table_name)
        
        total_rows = 0
        first_chunk = True
        
        # Connect to DuckDB
        duck_conn = duckdb.connect(db_path)
        
        try:
            for chunk in self.execute_query_stream(query, chunk_size=chunk_size):
                if not chunk:
                    continue
                
                # Convert to list of tuples for DuckDB
                columns = list(chunk[0].keys())
                values = [tuple(row[col] for col in columns) for row in chunk]
                
                if first_chunk:
                    # Drop existing table
                    duck_conn.execute(f"DROP TABLE IF EXISTS {table}")
                    
                    # Create table from first chunk
                    # Infer schema from first row
                    import pandas as pd
                    df = pd.DataFrame(chunk)
                    duck_conn.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
                    first_chunk = False
                    logger.info("Created DuckDB table", table_name=table_name, columns=len(columns))
                else:
                    # Insert subsequent chunks
                    placeholders = ", ".join(["?" for _ in columns])
                    duck_conn.executemany(
                        f"INSERT INTO {table} VALUES ({placeholders})",
                        values
                    )
                
                total_rows += len(chunk)
                
                if total_rows % 50000 == 0:
                    logger.info("Import progress", rows_imported=total_rows)
            
            init_meta_table(duck_conn)
            # Track metadata
            duck_conn.execute("""
                INSERT OR REPLACE INTO _data_skill_meta 
                (file_name, table_name, import_time, last_used_time, source_type, source_path, row_count, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'database', ?, ?, CURRENT_TIMESTAMP)
            """, [table_name, table_name, self._connection_string.split("@")[-1] if "@" in self._connection_string else self.config.type, total_rows])
            
            logger.info("DuckDB import complete", table_name=table_name, total_rows=total_rows)
            return total_rows
            
        except Exception as e:
            logger.error("DuckDB import failed", error=str(e))
            raise
        finally:
            duck_conn.close()
    
    def close(self) -> None:
        """Close the database connection and dispose of engine."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        
        self._connected = False
        logger.info("Database connection closed", db_type=self.config.type)
    
    def test_connection(self) -> bool:
        """Test if connection is valid.
        
        Returns:
            True if connection works, False otherwise
        """
        try:
            if not self._connected or self._engine is None:
                self.connect()
            
            from sqlalchemy import text
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            return True
            
        except Exception as e:
            logger.warning("Connection test failed", error=str(e))
            return False
    
    def get_engine(self) -> Any:
        """Get the SQLAlchemy engine.
        
        Creates connection if not already connected.
        
        Returns:
            SQLAlchemy Engine instance
        """
        if not self._connected or self._engine is None:
            self.connect()
        return self._engine
    
    def get_inspector(self):
        """Get SQLAlchemy inspector for schema discovery.
        
        Returns:
            SQLAlchemy Inspector instance
        """
        engine = self.get_engine()
        from sqlalchemy import inspect
        return inspect(engine)


class MongoDBConnector(DatabaseConnector):
    """MongoDB connector using PyMongo.
    
    Supports connection via URI, query execution with MongoDB filter syntax,
    and automatic document flattening for nested structures.
    """
    
    SYSTEM_DATABASES = {"admin", "local", "config"}
    
    def __init__(self, config: ConnectionProfile):
        """Initialize MongoDB connector.
        
        Args:
            config: Connection profile with MongoDB URI
        """
        super().__init__(config)
        self._client: Optional[Any] = None
        self._database_name = self._extract_database_name()
    
    def _extract_database_name(self) -> str:
        """Extract database name from URI or config.
        
        Returns:
            Database name string
        """
        if self.config.database:
            return self.config.database
        
        conn_str = self.config.get_connection_string()
        
        match = re.search(r'/([^/?]+)(\?|$)', conn_str)
        if match:
            return match.group(1)
        
        return "test"
    
    def connect(self) -> None:
        """Establish MongoDB connection.
        
        Raises:
            ConnectionError: If connection fails
        """
        if self._connected and self._client is not None:
            return
        
        try:
            from pymongo import MongoClient
            from pymongo.errors import PyMongoError

            conn_str = self.config.get_connection_string()
            
            timeout_ms = int(self.config.timeout * 1000)
            
            logger.info(
                "Connecting to MongoDB",
                database=self._database_name,
                timeout=self.config.timeout
            )
            
            self._client = MongoClient(
                conn_str,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=timeout_ms,
                serverSelectionTimeoutMS=timeout_ms
            )
            
            self._client.admin.command('ping')
            
            self._connected = True
            logger.info("MongoDB connection established", database=self._database_name)
            
        except ImportError as e:
            raise ImportError("MongoDB connections require pymongo. Install requirements-optional.txt.") from e
        except PyMongoError as e:
            error_msg = str(e)
            logger.error("MongoDB connection failed", error=error_msg)
            raise ConnectionError(f"Failed to connect to MongoDB: {error_msg}") from e
    
    def execute_query(
        self,
        query: Union[str, Dict[str, Any]],
        collection: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute MongoDB query.
        
        Args:
            query: MongoDB filter as dict or JSON string
            collection: Collection name to query
            params: Ignored for MongoDB (for interface compatibility)
            
        Returns:
            List of documents as dicts (ObjectId converted to string)
        """
        if not self._connected or self._client is None:
            self.connect()
        
        if collection is None:
            raise ValueError("Collection name required for MongoDB query")
        
        if isinstance(query, str):
            filter_dict = json.loads(query)
        else:
            filter_dict = query
        
        try:
            from pymongo.errors import PyMongoError

            db = self._client[self._database_name]
            coll = db[collection]
            
            logger.debug("Executing MongoDB query", collection=collection, filter=str(filter_dict)[:100])
            
            cursor = coll.find(filter_dict)
            results = []
            
            for doc in cursor:
                doc_dict = self._convert_document(doc)
                results.append(doc_dict)
            
            logger.info("MongoDB query executed", collection=collection, count=len(results))
            return results
            
        except PyMongoError as e:
            error_msg = str(e)
            logger.error("MongoDB query failed", error=error_msg)
            raise ValueError(f"MongoDB query failed: {error_msg}") from e
    
    def _convert_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MongoDB document to JSON-serializable dict.
        
        Handles ObjectId and other BSON types.
        
        Args:
            doc: MongoDB document
            
        Returns:
            Converted dictionary
        """
        result = {}
        for key, value in doc.items():
            from bson import ObjectId

            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = self._convert_document(value)
            elif isinstance(value, list):
                result[key] = [
                    str(item) if isinstance(item, ObjectId) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
    
    def _flatten_document(self, doc: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        """Flatten nested document for tabular storage.
        
        Args:
            doc: Document to flatten
            parent_key: Parent key prefix
            sep: Separator for nested keys
            
        Returns:
            Flattened dictionary
        """
        items = []
        for key, value in doc.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            
            if isinstance(value, dict):
                items.extend(self._flatten_document(value, new_key, sep).items())
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        items.extend(self._flatten_document(item, f"{new_key}_{i}", sep).items())
                    else:
                        items.append((f"{new_key}_{i}", item))
            else:
                items.append((new_key, value))
        
        return dict(items)
    
    def execute_query_to_duckdb(
        self,
        query: Union[str, Dict[str, Any]],
        table_name: str,
        collection: Optional[str] = None,
        db_path: str = "workspace.duckdb",
        chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> int:
        """Execute MongoDB query and import to DuckDB.
        
        Flattens nested documents for tabular storage.
        
        Args:
            query: MongoDB filter
            table_name: Target table name in DuckDB
            collection: Collection name
            db_path: Path to DuckDB database
            chunk_size: Rows per chunk
            
        Returns:
            Number of documents imported
        """
        if collection is None:
            raise ValueError("Collection name required for MongoDB query")
        
        logger.info(
            "Starting MongoDB to DuckDB import",
            collection=collection,
            table_name=table_name
        )
        table_name = validate_table_name(table_name)
        table = quote_identifier(table_name)
        
        documents = self.execute_query(query, collection=collection)
        
        if not documents:
            logger.warning("No documents found for query")
            return 0
        
        flattened = []
        for doc in documents:
            flat = self._flatten_document(doc)
            flattened.append(flat)
        
        df = pd.DataFrame(flattened)
        
        duck_conn = duckdb.connect(db_path)
        
        try:
            duck_conn.execute(f"DROP TABLE IF EXISTS {table}")
            duck_conn.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
            
            source_path = f"mongodb://{self._database_name}/{collection}"
            init_meta_table(duck_conn)
            duck_conn.execute("""
                INSERT OR REPLACE INTO _data_skill_meta 
                (file_name, table_name, import_time, last_used_time, source_type, source_path, row_count, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'database', ?, ?, CURRENT_TIMESTAMP)
            """, [table_name, table_name, source_path, len(flattened)])
            
            logger.info("MongoDB import complete", table_name=table_name, rows=len(flattened))
            return len(flattened)
            
        except Exception as e:
            logger.error("MongoDB to DuckDB import failed", error=str(e))
            raise
        finally:
            duck_conn.close()
    
    def close(self) -> None:
        """Close MongoDB connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
        
        self._connected = False
        logger.info("MongoDB connection closed")
    
    def test_connection(self) -> bool:
        """Test MongoDB connection with ping command.
        
        Returns:
            True if connection works, False otherwise
        """
        try:
            if not self._connected or self._client is None:
                self.connect()
            
            self._client.admin.command('ping')
            return True
            
        except Exception as e:
            logger.warning("MongoDB connection test failed", error=str(e))
            return False
    
    def get_client(self) -> Any:
        """Get the MongoClient instance.
        
        Creates connection if not already connected.
        
        Returns:
            MongoClient instance
        """
        if not self._connected or self._client is None:
            self.connect()
        return self._client
    
    def list_databases(self) -> List[str]:
        """List all non-system databases.
        
        Returns:
            Sorted list of database names
        """
        client = self.get_client()
        databases = client.list_database_names()
        return sorted([db for db in databases if db not in self.SYSTEM_DATABASES])
    
    def list_collections(self, database: Optional[str] = None) -> List[str]:
        """List all collections in a database.
        
        Args:
            database: Database name (uses default if not specified)
            
        Returns:
            Sorted list of collection names
        """
        client = self.get_client()
        db_name = database or self._database_name
        db = client[db_name]
        return sorted(db.list_collection_names())


def create_connector(config: ConnectionProfile) -> DatabaseConnector:
    """Factory function to create appropriate connector.
    
    Args:
        config: Connection profile
        
    Returns:
        DatabaseConnector instance
        
    Raises:
        ValueError: If database type is not supported
    """
    if config.type in ("mysql", "postgresql"):
        return SQLConnector(config)
    elif config.type == "mongodb":
        return MongoDBConnector(config)
    else:
        raise ValueError(f"Unsupported database type: {config.type}")


# Convenience function for quick queries
def execute_query(
    profile_name: str,
    query: str,
    config_path: Optional[str] = None,
    audit: bool = True,
) -> List[Dict[str, Any]]:
    """Execute a query against a named connection profile.

    Convenience function that loads config, creates connector,
    executes query, and closes connection.

    When ``audit=True`` (default), results are passed through the
    PrivacyGuard pipeline (PII classification + masking) and logged
    to the audit trail — the same as DuckDB queries.

    Args:
        profile_name: Name of connection profile in config
        query: SQL query string
        config_path: Optional path to config file
        audit: Enable privacy masking and audit logging (default True)

    Returns:
        List of dictionaries representing query results
    """
    from scripts.db_config import load_effective_config, load_config

    config = load_config(config_path) if config_path else load_effective_config()
    profile = config.connections.get(profile_name)

    if profile is None:
        raise KeyError(f"Connection profile '{profile_name}' not found")

    connector = create_connector(profile)
    try:
        results = connector.execute_query(query)

        # Apply privacy + audit pipeline (same as DuckDB queries)
        if audit and results:
            from scripts.config_manager import get_config
            from scripts.privacy_guard import PrivacyGuard
            from scripts.audit_report import log_external_query

            cfg = get_config()
            guard = PrivacyGuard(
                enabled=cfg.privacy.enabled,
                read_only=cfg.privacy.read_only,
                audit_enabled=cfg.privacy.audit_enabled,
                mask_pii=cfg.privacy.mask_pii,
                audit_log_path=cfg.privacy.audit_log_path,
            )

            columns = list(results[0].keys())
            table = _infer_table_name(query)

            # Classify + mask
            classification = guard.classify_columns(table, columns)
            masked_results = guard.mask_rows(results, classification)

            # Determine if masking actually changed anything
            was_masked = cfg.privacy.mask_pii and any(
                classification.get(col, {}).get("classification", "public") != "public"
                for col in columns
            )
            max_level = max(
                (classification.get(col, {}).get("classification", "public") for col in columns),
                key=lambda x: ({"public": 0, "internal": 1, "sensitive": 2, "restricted": 3}.get(x, 0)),
                default="public",
            )

            # Audit log
            log_external_query(
                query=query,
                connection_name=profile_name,
                db_type=profile.type,
                table=table,
                columns=columns,
                row_count=len(masked_results),
                masked=was_masked,
                classification=max_level,
                log_path=cfg.privacy.audit_log_path,
            )

            return masked_results

        return results
    finally:
        connector.close()
