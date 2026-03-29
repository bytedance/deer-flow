"""PostgreSQL query tool."""

import os
import traceback

from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv()


@tool("pgsql_query", parse_docstring=True)
def pgsql_query_tool(query: str) -> str:
    """Execute SQL query on PostgreSQL database.

    Args:
        query: SQL query to execute
    """
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            dbname=os.getenv("DB_DATABASE", "sim_data_agent"),
            connect_timeout=10,
        )
        conn.autocommit = False
        cursor = conn.cursor()
        cursor.execute(query)

        if cursor.description:
            rows = cursor.fetchall()
            if not rows:
                conn.close()
                return "Query returned no results"

            columns = [desc[0] for desc in cursor.description]
            result = " | ".join(columns) + "\n" + "-" * 40 + "\n"

            for row in rows[:100]:
                result += " | ".join(str(v) for v in row) + "\n"

            if len(rows) > 100:
                result += f"\n... Total {len(rows)} rows, showing first 100"

            conn.close()
            return result
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return f"Query executed successfully. {affected} row(s) affected."

    except Exception:
        return f"Error: {traceback.format_exc()}"
