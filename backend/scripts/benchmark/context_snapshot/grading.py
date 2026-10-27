"""Offline checks for synthetic artifacts; never imports the agent runtime.

This restricted Python exercise profile is not an operating-system sandbox.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cases import Case


def _same_value(actual, expected):
    """Keep Python value equality, but distinguish booleans from numbers."""
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_same_value(actual[key], expected[key]) for key in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(_same_value(left, right) for left, right in zip(actual, expected))
    return actual == expected


def grade_python(payload):
    """Run only pure Python over synthetic values, inside a timeout subprocess."""
    code = payload["code"]
    try:
        tree = ast.parse(code)
        forbidden = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith)
        bad_names = {"open", "eval", "exec", "compile", "globals", "locals", "getattr", "setattr", "delattr", "object", "input", "help", "breakpoint"}
        for node in ast.walk(tree):
            if isinstance(node, forbidden):
                raise ValueError("Pure-Python artifact may not import or access external resources")
            if isinstance(node, ast.Name) and (node.id in bad_names or ("__" in node.id and node.id != "__name__")):
                raise ValueError("External or reflective operation is not allowed")
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise ValueError("Private attribute access is not allowed")
        safe = {
            name: getattr(__import__("builtins"), name)
            for name in (
                "len",
                "range",
                "enumerate",
                "zip",
                "sorted",
                "reversed",
                "sum",
                "min",
                "max",
                "abs",
                "all",
                "any",
                "round",
                "divmod",
                "int",
                "float",
                "str",
                "bool",
                "bytes",
                "bytearray",
                "list",
                "dict",
                "tuple",
                "set",
                "type",
                "isinstance",
                "ValueError",
                "TypeError",
                "Exception",
                "AssertionError",
                "AttributeError",
                "IndexError",
                "KeyError",
                "LookupError",
                "OverflowError",
            )
        }
        namespace = {"__builtins__": safe, "__name__": "synthetic_artifact"}
        exec(compile(tree, "synthetic-artifact.py", "exec"), namespace)
        fn = namespace[payload["function"]]
        results = []
        for number, check in enumerate(payload["checks"]):
            args = copy.deepcopy(check["args"])
            original = copy.deepcopy(args)
            try:
                actual = fn(*args)
                unchanged = _same_value(args, original)
                ok = "raises" not in check and _same_value(actual, check.get("want")) and unchanged
                results.append({"check": number, "passed": ok, "actual": actual, "mutated_input": not unchanged})
            except Exception as exc:
                results.append({"check": number, "passed": type(exc).__name__ == check.get("raises") and _same_value(args, original), "exception": type(exc).__name__})
        return {"valid": True, "checks": results}
    except Exception as exc:
        return {"valid": False, "error": f"{type(exc).__name__}: {exc}", "checks": []}


def score(case: Case, content: str | None, *, public=False, timeout_seconds=3):
    if not content:
        return {"valid": False, "checks": [], "error": "No artifact was written"}
    if case.kind == "json":
        try:
            value = json.loads(content)
            if not isinstance(value, dict):
                return {"valid": False, "checks": [], "error": "Expected a JSON object"}
            valid = set(value) == set(case.expected)
            if public:
                return {"valid": valid, "checks": [{"check": "JSON shape", "passed": valid}]}
            checks = [{"check": name, "passed": _same_value(value.get(name), target)} for name, target in case.expected.items()]
            return {"valid": valid, "checks": checks}
        except Exception as exc:
            return {"valid": False, "checks": [], "error": type(exc).__name__}
    payload = {"code": content, "function": case.function, "checks": case.checks[:1] if public else case.checks}
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve())],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
            cwd=Path(__file__).resolve().parent,
        )
        return json.loads(result.stdout)
    except Exception as exc:
        return {"valid": False, "checks": [], "error": type(exc).__name__}


def passed(grade):
    return grade.get("valid", False) and bool(grade.get("checks")) and all(row["passed"] for row in grade["checks"])


if __name__ == "__main__":
    print(json.dumps(grade_python(json.load(sys.stdin))))
