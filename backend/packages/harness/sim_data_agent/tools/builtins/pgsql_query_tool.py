"""PostgreSQL query tool."""

import traceback

from langchain.tools import tool


@tool("pgsql_query", parse_docstring=True)
def pgsql_query_tool(query: str) -> str:
    """Execute SQL query on PostgreSQL database.

    Args:
        query: SQL query to execute
    """
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="120.26.208.161",
            port=35432,
            user="postgres",
            password="8ajFSypp7KCfZL2c",
            dbname="sim_data_agent",
            connect_timeout=10
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
