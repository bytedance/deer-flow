# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from src.tools.python_repl import python_repl_tool


def test_python_repl_tool_success():
    code = "print(1 + 1)"
    result = python_repl_tool(code)
    assert "Successfully executed" in result
    assert "Stdout: 2" in result


def test_python_repl_tool_syntax_error():
    code = "print(1 + )"
    result = python_repl_tool(code)
    assert "Error executing code:" in result
    assert code in result
    assert "SyntaxError" in result


def test_python_repl_tool_runtime_error():
    code = "print(1 / 0)"
    result = python_repl_tool(code)
    assert "Error executing code:" in result
    assert code in result
    assert "ZeroDivisionError" in result


def test_python_repl_tool_name_error():
    code = "print(undefined_variable)"
    result = python_repl_tool(code)
    assert "Error executing code:" in result
    assert code in result
    assert "NameError" in result


def test_python_repl_tool_type_error():
    code = "'2' + 2"
    result = python_repl_tool(code)
    assert "Error executing code:" in result
    assert code in result
    assert "TypeError" in result


def test_python_repl_tool_import_error():
    code = "from nonexistent_module import something"
    result = python_repl_tool(code)
    assert "Error executing code:" in result
    assert code in result
    assert "ModuleNotFoundError" in result


def test_python_repl_tool_exception():
    code = "raise Exception('Test')"
    result = python_repl_tool(code)
    assert "Error executing code:" in result
    assert code in result
    assert "Exception" in result
