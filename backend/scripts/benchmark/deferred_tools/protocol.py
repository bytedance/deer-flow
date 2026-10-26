"""Strict synthetic fixture loading and adapter-independent grading."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"Expected exactly these keys: {sorted(expected)}")


def _strings(values):
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) != len(values):
        raise ValueError("Expected a list of distinct nonempty strings")


def load_dataset(path: Path):
    raw = path.read_bytes()
    data = json.loads(raw)
    _keys(data, {"version", "kind", "tools", "cases"})
    if type(data["version"]) is not int or data["version"] != 1 or data["kind"] != "synthetic":
        raise ValueError("Only version 1 explicitly synthetic fixtures are supported")
    if not isinstance(data["tools"], list) or not data["tools"] or not isinstance(data["cases"], list) or not data["cases"]:
        raise ValueError("Nonempty tools and cases are required")
    tools = {}
    for tool in data["tools"]:
        _keys(tool, {"name", "description", "parameters", "routing_keywords"})
        name = tool["name"]
        if not isinstance(name, str) or not name or name in tools or not isinstance(tool["description"], str):
            raise ValueError("Tool names must be unique nonempty strings")
        _strings(tool["routing_keywords"])
        schema = tool["parameters"]
        Draft202012Validator.check_schema(schema)
        if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            raise ValueError("Tool parameters must declare object properties")
        tools[name] = tool
    ids = set()
    for case in data["cases"]:
        _keys(case, {"id", "query", "allowed_tools", "expected_tools", "required_fields"})
        if not isinstance(case["id"], str) or not case["id"] or case["id"] in ids:
            raise ValueError("Case IDs must be unique nonempty strings")
        ids.add(case["id"])
        if not isinstance(case["query"], str) or not case["query"].strip():
            raise ValueError("A query is required")
        _strings(case["allowed_tools"])
        _strings(case["expected_tools"])
        if not set(case["expected_tools"]) <= set(case["allowed_tools"]) <= set(tools):
            raise ValueError("Expected tools must belong to the post-policy catalog")
        if not isinstance(case["required_fields"], dict) or not set(case["required_fields"]) <= set(case["expected_tools"]):
            raise ValueError("Fields must belong to expected tools")
        for name, fields in case["required_fields"].items():
            _strings(fields)
            if not set(fields) <= set(tools[name]["parameters"]["properties"]):
                raise ValueError("Required input fields must exist in the catalog")
    return {**data, "sha256": hashlib.sha256(raw).hexdigest()}


def score(case, schemas):
    expected = set(case["expected_tools"])
    required = {(name, field) for name, fields in case["required_fields"].items() for field in fields}
    available = {(name, field) for name, schema in schemas.items() for field in schema.get("properties", {})}
    return {
        "tool_recall": len(expected & schemas.keys()) / len(expected) if expected else None,
        "field_recall": len(required & available) / len(required) if required else None,
        "false_positive_tools": sorted(schemas.keys() - expected),
        "unsupported_rejected": not schemas if not expected else None,
    }
