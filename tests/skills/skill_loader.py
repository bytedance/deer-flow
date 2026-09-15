"""Load a skill's scripts/generate.py as an importable module, by file path.

Skills live in skills/public/<name>/scripts/generate.py and are NOT a package,
so tests load them via importlib. Tests then mock the module's `requests`.
"""
import importlib.util
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]


def load(skill_name: str):
    """Return the generate.py module for skills/public/<skill_name>."""
    path = REPO_ROOT / "skills" / "public" / skill_name / "scripts" / "generate.py"
    mod_name = skill_name.replace("-", "_") + "_generate"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module  # standard pattern; lets the module resolve itself
    spec.loader.exec_module(module)
    return module


class FakeResp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json
