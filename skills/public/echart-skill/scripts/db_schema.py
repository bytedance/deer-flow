"""
Database Schema Discovery Module.

Provides utilities for discovering database structure:
- discover_tables: List all tables in a database
- describe_table: Get column details for a table
- list_schemas: List schemas (PostgreSQL)
- format_schema_table: Format schema as markdown table

Usage:
    from scripts.db_schema import discover_tables, describe_table
    from scripts.db_connector import SQLConnector

    tables = discover_tables(connector)
    columns = describe_table(connector, "users")
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger
from validators import quote_identifier

if TYPE_CHECKING:
    from scripts.db_connector import SQLConnector
    from scripts.db_connector import MongoDBConnector

logger = get_logger(__name__)


def discover_tables(
    connector: "SQLConnector", 
    schema: Optional[str] = None
) -> List[str]:
    """List all tables in the database.
    
    Uses SQLAlchemy Inspector to get table names without
    executing raw queries.
    
    Args:
        connector: SQLConnector instance (must be connected)
        schema: Schema name for PostgreSQL (optional)
        
    Returns:
        Sorted list of table names
    """
    inspector = connector.get_inspector()
    tables = inspector.get_table_names(schema=schema)
    tables.sort()
    
    schema_info = f" in schema '{schema}'" if schema else ""
    logger.info("Discovered tables", count=len(tables), schema=schema)
    
    return tables


def describe_table(
    connector: "SQLConnector", 
    table_name: str,
    schema: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get column details for a table.
    
    Uses SQLAlchemy Inspector to get column metadata.
    
    Args:
        connector: SQLConnector instance (must be connected)
        table_name: Name of the table to describe
        schema: Schema name for PostgreSQL (optional)
        
    Returns:
        List of dicts with: name, type, nullable, default, primary_key
    """
    inspector = connector.get_inspector()
    columns = inspector.get_columns(table_name, schema=schema)
    
    result = []
    for col in columns:
        result.append({
            "name": col.get("name", ""),
            "type": str(col.get("type", "UNKNOWN")),
            "nullable": col.get("nullable", True),
            "default": col.get("default"),
            "primary_key": col.get("primary_key", False)
        })
    
    logger.info("Described table", table=table_name, columns=len(result))
    return result


def list_schemas(connector: "SQLConnector") -> List[str]:
    """List all schemas in the database.
    
    PostgreSQL and some databases support multiple schemas.
    MySQL returns an empty list (single schema).
    
    Args:
        connector: SQLConnector instance (must be connected)
        
    Returns:
        List of schema names (empty for MySQL)
    """
    inspector = connector.get_inspector()
    
    try:
        schemas = inspector.get_schema_names()
        logger.info("Listed schemas", count=len(schemas))
        return schemas
    except NotImplementedError:
        logger.debug("Schema listing not supported for this database type")
        return []


def format_schema_table(columns: List[Dict[str, Any]]) -> str:
    """Format column info as markdown table.
    
    Args:
        columns: List of column dicts from describe_table
        
    Returns:
        Markdown-formatted table string
    """
    if not columns:
        return "No columns found."
    
    lines = [
        "| Column | Type | Nullable | Primary Key |",
        "|--------|------|----------|-------------|"
    ]
    
    for col in columns:
        name = col.get("name", "")
        col_type = col.get("type", "")
        nullable = "YES" if col.get("nullable", True) else "NO"
        pk = "✓" if col.get("primary_key", False) else ""
        lines.append(f"| {name} | {col_type} | {nullable} | {pk} |")
    
    return "\n".join(lines)


def get_table_row_count(
    connector: "SQLConnector",
    table_name: str,
    schema: Optional[str] = None
) -> int:
    """Get approximate row count for a table.
    
    Uses database-specific methods for efficiency:
    - PostgreSQL: pg_class.reltuples (approximate)
    - MySQL: information_schema.tables.table_rows
    
    Args:
        connector: SQLConnector instance
        table_name: Table name
        schema: Schema name (PostgreSQL)
        
    Returns:
        Approximate row count
    """
    db_type = connector.config.type
    
    try:
        if db_type == "postgresql":
            schema_val = schema or "public"
            query = """
                SELECT reltuples::bigint AS estimate 
                FROM pg_class 
                WHERE relname = :table_name
                AND relnamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = :schema_name
                )
            """
            result = connector.execute_query(query, {"table_name": table_name, "schema_name": schema_val})
            return result[0].get("estimate", 0) if result else 0
            
        elif db_type == "mysql":
            query = """
                SELECT table_rows 
                FROM information_schema.tables 
                WHERE table_name = :table_name
            """
            result = connector.execute_query(query, {"table_name": table_name})
            return result[0].get("table_rows", 0) if result else 0
            
        else:
            query = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)}"
            result = connector.execute_query(query)
            return result[0].get("count", 0) if result else 0
            
    except Exception as e:
        logger.warning("Could not get row count", error=str(e))
        return -1


def get_table_indexes(
    connector: "SQLConnector",
    table_name: str,
    schema: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get index information for a table.
    
    Args:
        connector: SQLConnector instance
        table_name: Table name
        schema: Schema name (PostgreSQL)
        
    Returns:
        List of index info dicts
    """
    inspector = connector.get_inspector()
    
    try:
        indexes = inspector.get_indexes(table_name, schema=schema)
        logger.info("Retrieved indexes", table=table_name, count=len(indexes))
        return indexes
    except Exception as e:
        logger.warning("Could not get indexes", error=str(e))
        return []


def get_foreign_keys(
    connector: "SQLConnector",
    table_name: str,
    schema: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get foreign key information for a table.
    
    Args:
        connector: SQLConnector instance
        table_name: Table name
        schema: Schema name (PostgreSQL)
        
    Returns:
        List of foreign key info dicts
    """
    inspector = connector.get_inspector()
    
    try:
        fks = inspector.get_foreign_keys(table_name, schema=schema)
        logger.info("Retrieved foreign keys", table=table_name, count=len(fks))
        return fks
    except Exception as e:
        logger.warning("Could not get foreign keys", error=str(e))
        return []


def list_mongo_databases(connector: "MongoDBConnector") -> List[str]:
    """List all non-system MongoDB databases.
    
    Excludes admin, local, config system databases.
    
    Args:
        connector: MongoDBConnector instance
        
    Returns:
        Sorted list of database names
    """
    databases = connector.list_databases()
    logger.info("Listed MongoDB databases", count=len(databases))
    return databases


def list_mongo_collections(
    connector: "MongoDBConnector",
    database: Optional[str] = None
) -> List[str]:
    """List all collections in a MongoDB database.
    
    Args:
        connector: MongoDBConnector instance
        database: Database name (uses connector's default if not specified)
        
    Returns:
        Sorted list of collection names
    """
    collections = connector.list_collections(database)
    logger.info("Listed MongoDB collections", database=database or connector._database_name, count=len(collections))
    return collections


def infer_mongo_schema(
    connector: "MongoDBConnector",
    collection: str,
    sample_size: int = 100
) -> Dict[str, str]:
    """Infer field types from MongoDB collection documents.
    
    Samples documents to determine field types, handling
    varying schemas across documents.
    
    Args:
        connector: MongoDBConnector instance
        collection: Collection name to sample
        sample_size: Number of documents to sample
        
    Returns:
        Mapping of field_name -> inferred type
    """
    client = connector.get_client()
    db_name = connector._database_name
    db = client[db_name]
    coll = db[collection]
    
    type_map: Dict[str, set] = {}
    
    try:
        for doc in coll.find().limit(sample_size):
            for key, value in doc.items():
                if key == "_id":
                    continue
                
                inferred_type = _infer_value_type(value)
                
                if key not in type_map:
                    type_map[key] = set()
                type_map[key].add(inferred_type)
        
        result = {}
        for key, types in type_map.items():
            if len(types) == 1:
                result[key] = list(types)[0]
            else:
                result[key] = "mixed"
        
        logger.info("Inferred MongoDB schema", collection=collection, fields=len(result))
        return result
        
    except Exception as e:
        logger.warning("Could not infer MongoDB schema", error=str(e))
        return {}


def _infer_value_type(value: Any) -> str:
    """Infer type string from a value.
    
    Args:
        value: Any Python value
        
    Returns:
        Type string (string, number, boolean, array, object, null)
    """
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "boolean"
    elif isinstance(value, (int, float)):
        return "number"
    elif isinstance(value, str):
        return "string"
    elif isinstance(value, list):
        return "array"
    elif isinstance(value, dict):
        return "object"
    else:
        return "unknown"


def format_mongo_schema(fields: Dict[str, str]) -> str:
    """Format MongoDB inferred schema as markdown table.
    
    Args:
        fields: Mapping of field_name -> type
        
    Returns:
        Markdown-formatted table string
    """
    if not fields:
        return "No fields found."
    
    lines = [
        "| Field | Type |",
        "|-------|------|"
    ]
    
    for name, typ in sorted(fields.items()):
        lines.append(f"| {name} | {typ} |")
    
    return "\n".join(lines)
