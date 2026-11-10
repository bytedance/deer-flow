"""Public, package-owned documentation. Never inspect deployment config."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

FILENAME = "deerflow-extension.json"
MAX_BYTES = 65536


def validate_documentation(value: object) -> dict:
    """Validate v1; requirements and documentation links are optional."""

    def text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip()) and len(value) <= 4000

    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("documentation requires schema_version 1")
    if not isinstance(value.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", value["id"]):
        raise ValueError("documentation requires a stable id")
    locales = value.get("locales")
    if not isinstance(locales, dict) or not locales or len(locales) > 20:
        raise ValueError("documentation requires at least one locale")
    result = {"schema_version": 1, "id": value["id"], "locales": {}}
    for locale, copy in locales.items():
        if not re.fullmatch(r"[a-z]{2}(?:-[A-Za-z]{2,8})?", locale) or not isinstance(copy, dict):
            raise ValueError("invalid documentation locale")
        if not text(copy.get("title")) or not text(copy.get("description")):
            raise ValueError("documentation title and description are required")
        steps = copy.get("usage")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            raise ValueError("documentation requires usage steps")
        if any(not isinstance(step, dict) or not text(step.get("title")) or not text(step.get("description")) for step in steps):
            raise ValueError("usage steps require a title and description")
        public = {"title": copy["title"], "description": copy["description"], "usage": [{"title": s["title"], "description": s["description"]} for s in steps]}
        requirements = copy.get("requirements")
        if requirements is not None:
            if not isinstance(requirements, list) or len(requirements) > 12 or any(not text(item) for item in requirements):
                raise ValueError("requirements must be a list of nonempty descriptions")
            if requirements:
                public["requirements"] = requirements
        result["locales"][locale] = public
    if "docs_url" in value:
        url = value["docs_url"]
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("docs_url must be a public HTTPS URL")
        # urlsplit defers numeric/range validation until port is accessed.
        _ = parsed.port
        result["docs_url"] = url
    # Validate only the public projection; unknown/private package fields are
    # deliberately excluded and must not affect discovery.
    try:
        json.dumps(result, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("documentation must contain valid UTF-8 text") from exc
    return result


def read_documentation(source: str) -> dict | None:
    """Read beside the already imported entrypoint; never import a disabled plugin."""
    module = sys.modules.get(source.partition(":")[0])
    filename = getattr(module, "__file__", None)
    if not filename:
        return None
    path = Path(filename).parent / FILENAME
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(raw) > MAX_BYTES:
        raise ValueError("extension documentation exceeds 64 KiB")
    return validate_documentation(json.loads(raw))
