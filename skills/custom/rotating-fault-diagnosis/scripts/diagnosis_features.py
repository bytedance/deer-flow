#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from _bridge import load_data_analyst_module

_MODULE = load_data_analyst_module("diagnosis_features.py", "_rotating_diagnosis_features")


def _split_token(argv: list[str]) -> tuple[list[str], str | None]:
    forwarded: list[str] = []
    token: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--access-token":
            if i + 1 >= len(argv):
                raise SystemExit("--access-token requires a value")
            token = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--access-token="):
            token = arg.split("=", 1)[1]
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return forwarded, token


def main() -> int:
    forwarded, token = _split_token(sys.argv[1:])
    if token:
        os.environ["INS_ACCESS_TOKEN"] = token

    original_argv = sys.argv
    sys.argv = [original_argv[0], *forwarded]
    try:
        return int(_MODULE.main())
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
