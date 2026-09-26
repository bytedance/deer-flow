"""Bounded, immutable startup snapshots for manifest-listed browser resources."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from deerflow_extension_api.plugins import BrowserAssets

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_FILES = 256
MIME_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".wasm": "application/wasm",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}


def valid_asset_path(path: object) -> bool:
    return isinstance(path, str) and len(path) <= 512 and all(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part) is not None for part in path.split("/"))


@dataclass(frozen=True)
class Asset:
    content: bytes
    media_type: str


@dataclass(frozen=True, kw_only=True)
class LoadedBrowserAssets(BrowserAssets):
    entry: str
    revision: str
    files: Mapping[str, Asset]


def _read(root: Path, path: str, limit: int) -> bytes:
    if not valid_asset_path(path):
        raise ValueError("Invalid browser asset path")
    target = root / path
    # Reject symlinks at every component rather than following an escaping link.
    cursor = root
    for part in path.split("/"):
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Browser assets must not contain symlinks")
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("Browser asset must be a regular file inside its package")
    with resolved.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Browser asset size limit exceeded")
    return content


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate browser manifest key")
        result[key] = value
    return result


def load_browser_assets(declaration: BrowserAssets) -> LoadedBrowserAssets:
    declared_root = Path(declaration.root)
    if declared_root.is_symlink():
        raise ValueError("Browser asset root must not be a symlink")
    # Parent path aliases (for example /var on macOS) remain supported.
    root = declared_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Browser asset root must be a directory")
    manifest = json.loads(_read(root, declaration.manifest, 64 * 1024), object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "entry", "files"} or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported browser asset manifest; expected schema_version 1")
    entry, paths = manifest["entry"], manifest["files"]
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_FILES or not all(valid_asset_path(path) for path in paths) or len(set(paths)) != len(paths):
        raise ValueError("Browser manifest must list unique asset paths")
    if not valid_asset_path(entry) or entry not in paths or Path(entry).suffix not in (".js", ".mjs"):
        raise ValueError("Browser manifest entry must be a listed JavaScript module")
    assets = {}
    total = 0
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    for path in sorted(paths):
        mime = MIME_TYPES.get(Path(path).suffix)
        if mime is None:
            raise ValueError("Unsupported browser asset file type")
        content = _read(root, path, min(MAX_FILE_BYTES, MAX_PACKAGE_BYTES - total))
        total += len(content)
        digest.update(path.encode() + b"\0" + hashlib.sha256(content).digest())
        assets[path] = Asset(content, mime)
    return LoadedBrowserAssets(module=declaration.module, root=root, manifest=declaration.manifest, public_fields=declaration.public_fields, entry=entry, revision=digest.hexdigest(), files=MappingProxyType(assets))
