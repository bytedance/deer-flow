#!/usr/bin/env python3
"""Simple MCP server for PostgreSQL queries."""

import sys
import json
import psycopg2
import traceback


class PostgresMCPServer:
    def __init__(self, connection_string=None):
        self.default_conn_str = connection_string or "postgresql://postgres:8ajFSypp7KCfZL2c@120.26.208.161:35432/sim_data_agent"
        self.connection_string = self.default_conn_str
        self.tools = {
            "pgsql_query": {
                "description": "Execute SQL query on PostgreSQL database. Supports SELECT/INSERT/UPDATE/DELETE/CREATE etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SQL query to execute"},
                        "connection_string": {"type": "string", "description": "PostgreSQL connection string (optional, uses default if not provided)"}
                    },
                    "required": ["query"]
                }
            },
            "pgsql_list_tables": {
                "description": "List all tables in the PostgreSQL database",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "schema": {"type": "string", "description": "Schema name (default: public)"}
                    },
                    "required": []
                }
            },
            "pgsql_describe_table": {
                "description": "Get column info for a table",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "table": {"type": "string", "description": "Table name"},
                        "schema": {"type": "string", "description": "Schema name (default: public)"}
                    },
                    "required": ["table"]
                }
            }
        }

    def handle_request(self, request):
        method = request.get("method")
        req_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "postgres", "version": "1.0.0"}
                }
            }
        elif method == "tools/list":
            tools_list = [
                {"name": name, "description": info["description"], "inputSchema": info["input_schema"]}
                for name, info in self.tools.items()
            ]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}
        elif method == "tools/call":
            tool_name = request["params"]["name"]
            arguments = request["params"].get("arguments", {})

            if tool_name == "pgsql_query":
                result = self.execute_query(
                    arguments.get("query", ""),
                    arguments.get("connection_string")
                )
            elif tool_name == "pgsql_list_tables":
                result = self.list_tables(arguments.get("schema", "public"))
            elif tool_name == "pgsql_describe_table":
                result = self.describe_table(
                    arguments.get("table", ""),
                    arguments.get("schema", "public")
                )
            else:
                result = f"Unknown tool: {tool_name}"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(result)}]
                }
            }
        elif method.startswith("notifications/"):
            # MCP notifications - no response needed, just skip
            return None
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    def get_connection(self, connection_string=None):
        conn_str = connection_string or self.connection_string
        return psycopg2.connect(conn_str, connect_timeout=10)

    def execute_query(self, query, connection_string=None):
        """Execute SQL query and return results."""
        if not query:
            return "Error: No query provided"

        try:
            conn = self.get_connection(connection_string)
            conn.autocommit = False
            cursor = conn.cursor()

            cursor.execute(query)

            if cursor.description:  # SELECT/SHOW/DESC etc
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
            else:  # INSERT/UPDATE/DELETE etc
                conn.commit()
                affected = cursor.rowcount
                conn.close()
                return f"Query executed successfully. {affected} row(s) affected."

        except Exception:
            return f"Error: {traceback.format_exc()}"

    def list_tables(self, schema="public"):
        """List all tables in schema."""
        query = f"""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = '{schema}'
        ORDER BY table_name;
        """
        return self.execute_query(query)

    def describe_table(self, table, schema="public"):
        """Get column info for a table."""
        query = f"""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{table}'
        ORDER BY ordinal_position;
        """
        return self.execute_query(query)

    def run(self):
        """Main loop - read JSON-RPC requests from stdin."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = self.handle_request(request)

                if response:
                    print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}), flush=True)
            except Exception as e:
                print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}), flush=True)


if __name__ == "__main__":
    conn_str = sys.argv[2] if len(sys.argv) > 2 else "postgresql://postgres:8ajFSypp7KCfZL2c@120.26.208.161:35432/sim_data_agent"
    PostgresMCPServer(conn_str).run()
