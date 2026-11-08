"""Validate package documentation and regenerate the frontend's discovery copy."""

import argparse
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = runpy.run_path(
    str(ROOT / "backend/packages/harness/deerflow/extensions/documentation.py")
)["validate_documentation"]
DESTINATION = ROOT / "frontend/src/core/extensions/bundled-documentation.json"


def render():
    pages = {}
    for path in sorted(
        (ROOT / "examples").glob("deerflow-extension-*/*/deerflow-extension.json")
    ):
        page = VALIDATE(json.loads(path.read_text(encoding="utf-8")))
        if len(path.read_bytes()) > 65536:
            raise ValueError(f"Documentation is too large: {path}")
        if any(existing["id"] == page["id"] for existing in pages.values()):
            raise ValueError(f"Duplicate extension documentation id: {page['id']}")
        pages[path.parent.parent.name] = page
    return json.dumps(pages, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if DESTINATION.read_text(encoding="utf-8") != content:
            parser.exit(
                1,
                "Extension copy is stale; run python scripts/sync_extension_documentation.py\n",
            )
    else:
        DESTINATION.write_text(content, encoding="utf-8")
