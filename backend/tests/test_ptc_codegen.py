"""Unit tests for PTC client code generation."""

from __future__ import annotations

from src.ptc.client_codegen import (
    _sanitize_identifier,
    generate_base_client,
    generate_init_module,
    generate_server_module,
)
from src.tools.catalog import ToolEntry, ToolParameterSchema

# ---------------------------------------------------------------------------
# _sanitize_identifier
# ---------------------------------------------------------------------------


class TestSanitizeIdentifier:
    def test_simple_name(self):
        assert _sanitize_identifier("query") == "query"

    def test_hyphens_replaced(self):
        assert _sanitize_identifier("web-search") == "web_search"

    def test_dots_replaced(self):
        assert _sanitize_identifier("org.tool") == "org_tool"

    def test_leading_digit(self):
        assert _sanitize_identifier("3d_model") == "_3d_model"

    def test_python_keyword(self):
        assert _sanitize_identifier("class") == "class_"
        assert _sanitize_identifier("import") == "import_"

    def test_empty_string(self):
        result = _sanitize_identifier("")
        assert result.isidentifier()

    def test_special_chars(self):
        result = _sanitize_identifier("tool@v2!")
        assert result.isidentifier()


# ---------------------------------------------------------------------------
# generate_base_client
# ---------------------------------------------------------------------------


class TestGenerateBaseClient:
    def test_compiles(self):
        """Generated base client should be valid Python."""
        code = generate_base_client()
        compiled = compile(code, "mcp_client.py", "exec")
        assert compiled is not None

    def test_contains_call_tool(self):
        code = generate_base_client()
        assert "def call_tool(" in code

    def test_contains_error_class(self):
        code = generate_base_client()
        assert "class ToolCallError" in code

    def test_uses_stdlib_only(self):
        """Should not import any third-party libraries."""
        code = generate_base_client()
        assert "import requests" not in code
        assert "import httpx" not in code
        assert "urllib.request" in code

    def test_reads_env_vars(self):
        code = generate_base_client()
        assert "PTC_TOKEN" in code
        assert "PTC_GATEWAY_URL" in code


# ---------------------------------------------------------------------------
# generate_server_module
# ---------------------------------------------------------------------------


class TestGenerateServerModule:
    def _make_entry(
        self,
        name: str = "query",
        description: str = "Execute a query",
        params: list[ToolParameterSchema] | None = None,
    ) -> ToolEntry:
        if params is None:
            params = [
                ToolParameterSchema(name="sql", type_hint="str", description="SQL query", required=True),
                ToolParameterSchema(name="database", type_hint="str", description="Database name", required=False, default="'default'"),
            ]
        return ToolEntry(
            name=name,
            description=description,
            parameter_names=[p.name for p in params],
            parameters=params,
            server_name="postgres",
            is_core=False,
        )

    def test_compiles(self):
        """Generated server module should be valid Python (ignoring imports)."""
        entry = self._make_entry()
        code = generate_server_module("postgres", [entry])
        # Replace the import that would fail outside sandbox
        code = code.replace("from mcp_client import call_tool", "def call_tool(*a, **kw): pass")
        compiled = compile(code, "tools/postgres.py", "exec")
        assert compiled is not None

    def test_function_generated(self):
        entry = self._make_entry()
        code = generate_server_module("postgres", [entry])
        assert "def query(" in code

    def test_required_params_first(self):
        entry = self._make_entry()
        code = generate_server_module("postgres", [entry])
        # 'sql' (required) should come before 'database' (optional)
        assert code.index("sql: str") < code.index("database: str")

    def test_default_values(self):
        entry = self._make_entry()
        code = generate_server_module("postgres", [entry])
        assert "= 'default'" in code

    def test_docstring_included(self):
        entry = self._make_entry()
        code = generate_server_module("postgres", [entry])
        assert "Execute a query" in code
        assert "sql:" in code

    def test_calls_call_tool(self):
        entry = self._make_entry()
        code = generate_server_module("postgres", [entry])
        assert 'call_tool("postgres", "query"' in code

    def test_multiple_tools(self):
        entries = [
            self._make_entry(name="query", description="Run query"),
            self._make_entry(
                name="list_schemas",
                description="List schemas",
                params=[],
            ),
        ]
        code = generate_server_module("postgres", entries)
        assert "def query(" in code
        assert "def list_schemas(" in code

    def test_hyphenated_server_name(self):
        """Server names with hyphens should not break imports."""
        entry = self._make_entry(name="search")
        code = generate_server_module("my-server", [entry])
        assert 'call_tool("my-server"' in code
        assert compile(
            code.replace("from mcp_client import call_tool", "def call_tool(*a, **kw): pass"),
            "tools/my_server.py",
            "exec",
        )

    def test_no_params(self):
        """Tools with no parameters should still compile."""
        entry = self._make_entry(name="status", description="Get status", params=[])
        code = generate_server_module("server", [entry])
        assert "def status() -> str:" in code
        compiled = compile(
            code.replace("from mcp_client import call_tool", "def call_tool(*a, **kw): pass"),
            "tools/server.py",
            "exec",
        )
        assert compiled is not None


# ---------------------------------------------------------------------------
# generate_init_module
# ---------------------------------------------------------------------------


class TestGenerateInitModule:
    def test_compiles(self):
        """Generated __init__.py should be valid Python (ignoring imports)."""
        code = generate_init_module(["postgres", "ncbi"])
        # Replace imports that would fail
        code = code.replace("from tools import", "# from tools import")
        compiled = compile(code, "tools/__init__.py", "exec")
        assert compiled is not None

    def test_imports_servers(self):
        code = generate_init_module(["postgres", "ncbi"])
        assert "from tools import postgres" in code
        assert "from tools import ncbi" in code

    def test_sorted_imports(self):
        code = generate_init_module(["z_server", "a_server"])
        assert code.index("a_server") < code.index("z_server")

    def test_empty_servers(self):
        code = generate_init_module([])
        compiled = compile(code, "tools/__init__.py", "exec")
        assert compiled is not None

    def test_sanitizes_names(self):
        code = generate_init_module(["my-server"])
        assert "my_server" in code
