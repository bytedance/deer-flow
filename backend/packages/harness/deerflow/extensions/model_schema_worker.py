"""One-call schema worker, launched by file path in an isolated Python process.

Only bounded JSON input and fixed status words cross the pipes. Expensive schema
checking and regex validation must never execute on the Gateway loop or its GIL.
"""

import json
import sys

from jsonschema import Draft202012Validator


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _check_inline(value):
    if isinstance(value, dict):
        if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
            raise ValueError("References are unsupported")
        if "$schema" in value and value["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("Unsupported dialect")
        for child in value.values():
            _check_inline(child)
    elif isinstance(value, list):
        for child in value:
            _check_inline(child)


def main():
    try:
        schema = json.loads(sys.stdin.buffer.readline())
        if schema.get("type") != "object":
            raise ValueError("Expected object schema")
        _check_inline(schema)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except Exception:
        print("invalid_schema", flush=True)
        return
    print("ready", flush=True)
    response = sys.stdin.buffer.readline()
    if not response:
        return
    try:
        content = json.loads(response)
        structured = json.loads(content, parse_constant=_reject_constant)
        json.dumps(structured, allow_nan=False)
        validator.validate(structured)
    except Exception:
        print("invalid_output", flush=True)
        return
    print("valid", flush=True)


if __name__ == "__main__":
    main()
