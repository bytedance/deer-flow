#!/usr/bin/env python3
"""Simple MCP server for Python code execution."""

import sys
import json
import io
import contextlib
import traceback


class MCPServer:
    def __init__(self):
        self.tools = {
            "python_exec": {
                "description": "Execute Python code and return output. Use for data analysis, calculations, and processing tasks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"}
                    },
                    "required": ["code"]
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
                    "serverInfo": {"name": "python-exec", "version": "1.0.0"}
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

            if tool_name == "python_exec":
                result = self.execute_python(arguments.get("code", ""))
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

    def execute_python(self, code):
        """Execute Python code and capture output."""
        output = io.StringIO()
        error_output = io.StringIO()

        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
                exec(code, {"__builtins__": __builtins__})

            result = output.getvalue()
            err = error_output.getvalue()

            if err:
                result = result + "\n[STDERR]: " + err if result else err

            return result if result else "(No output)"
        except Exception:
            return f"Error: {traceback.format_exc()}"

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
    MCPServer().run()
