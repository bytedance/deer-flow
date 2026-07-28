"""Plugin-manifest loader + on-demand dependency installer for memory backends.

Each drop-in backend may ship a ``plugin.yaml`` next to its ``__init__.py``
declaring its external pip dependencies. The memory factory calls
:func:`ensure_backend_deps` (between resolving the backend class and calling
its ``from_config``) so that selecting a backend whose deps are missing either
(a) auto-installs them (when ``memory.allow_lazy_installs`` is true) or
(b) raises a clear :class:`MemoryManagerError` with the exact install command.

Install target is ``<runtime_home>/memory_deps/<backend>/`` (outside the venv),
so ``uv sync`` never wipes it -- mirrors the hermes ``pip install --target``
pattern (``agent/lsp/install.py``). The directory is prepended to ``sys.path``
so the installed packages import normally.

This module is dependency-light on purpose: ``read_manifest`` is pure file
parse (no backend import), so it runs during ``_scan_backends`` without needing
the backend's deps installed. ``MemoryManagerError`` is imported lazily inside
:func:`ensure_backend_deps` to avoid a circular import with ``manager.py``.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Strip a PEP 508 version specifier tail: "openviking>=0.4[all]" -> "openviking".
# Used only to guess the import name when ``import_names`` is omitted.
_VERSION_SPEC_RE = re.compile(r"\s*(?:\[.*?\])?\s*[=<>!~;@].*$")


@dataclass
class BackendManifest:
    """A backend's ``plugin.yaml`` declaration.

    ``dependencies`` are pip specs (PEP 508, may pin versions); ``import_names``
    are the module names used to detect whether the deps are already importable.
    """

    name: str
    dependencies: list[str] = field(default_factory=list)
    import_names: list[str] = field(default_factory=list)


def _strip_version(dep: str) -> str:
    """``openviking>=0.4[all]`` -> ``openviking`` (import-name guess)."""
    return _VERSION_SPEC_RE.sub("", dep).strip().split(";")[0].strip()


def read_manifest(backend_dir: Path) -> BackendManifest | None:
    """Parse ``<backend_dir>/plugin.yaml``; ``None`` if absent or malformed.

    Pure file parse -- no import of the backend or its deps. ``import_names``
    defaults to the dependency names with version specifiers stripped.
    """
    manifest_path = Path(backend_dir) / "plugin.yaml"
    if not manifest_path.is_file():
        return None
    try:
        import yaml  # PyYAML is a harness dependency

        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - a malformed manifest must not crash the scan
        logger.warning("Failed to read memory backend manifest %s: %s", manifest_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    deps = [str(d) for d in data.get("dependencies", []) if str(d).strip()]
    raw_imports = [str(n) for n in data.get("import_names", []) if str(n).strip()]
    imports = raw_imports or [_strip_version(d) for d in deps]
    return BackendManifest(
        name=str(data.get("name") or Path(backend_dir).name),
        dependencies=deps,
        import_names=imports,
    )


def _add_to_sys_path(p: str) -> None:
    """Insert ``p`` on ``sys.path`` AFTER the venv's site-packages.

    ``uv pip install --target`` installs the full dependency tree (not just the
    requested package).  Prepending the target dir can shadow venv packages with
    incompatible versions (e.g. ``pydantic_core``).  Inserting after the last
    venv site-packages entry lets the venv win on conflicts while still
    exposing the missing package.
    """
    last_sp = len(sys.path)
    for i, entry in enumerate(sys.path):
        if "site-packages" in entry or "dist-packages" in entry:
            # Insert after the LAST site/dist-packages entry so a
            # package already in the venv resolves first.
            last_sp = i + 1
    sys.path.insert(last_sp, p)


def _find_spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _build_install_cmd(target: Path, deps: list[str]) -> list[str]:
    """Build the install command, preferring ``uv`` (deerflow venvs ship no pip).

    ``uv pip install --target`` is supported (verified); falls back to
    ``python -m pip install --target`` (bootstrapping pip via ensurepip first).
    """
    uv = shutil.which("uv")
    if uv:
        # --python ensures wheels match the venv's version (not uv's default)
        return [uv, "pip", "install", "--python", sys.executable, "--target", str(target), "--quiet", *deps]
    py = sys.executable
    try:
        subprocess.run(
            [py, "-m", "ensurepip", "--default-pip"],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception:  # noqa: BLE001 - best-effort bootstrap; pip may already exist
        pass
    return [py, "-m", "pip", "install", "--target", str(target), "--quiet", *deps]


def ensure_backend_deps(
    name: str,
    manifest: BackendManifest | None,
    *,
    allow_lazy: bool,
    runtime_home: Path,
) -> None:
    """Ensure a backend's declared deps are importable; auto-install if allowed.

    No-op when the backend has no manifest (no external deps). If the deps are
    already importable (including from a previously-installed ``--target`` dir),
    also a no-op. Otherwise either auto-install (``allow_lazy=True``) or raise a
    :class:`MemoryManagerError` with the manual install command.
    """
    from deerflow.agents.memory.manager import MemoryManagerError  # local: avoid circular import

    if manifest is None or not manifest.import_names:
        return  # backend declares no external deps

    target = Path(runtime_home) / "memory_deps" / name
    if target.is_dir():
        p = str(target)
        if p not in sys.path:
            _add_to_sys_path(p)

    missing = [n for n in manifest.import_names if not _find_spec(n)]
    if not missing:
        return  # already importable

    deps_str = " ".join(manifest.dependencies)
    if not allow_lazy:
        raise MemoryManagerError(
            f"Memory backend {name!r} requires {missing} which are not installed. Either run:  uv pip install {deps_str}  (or pip install {deps_str}), or set  memory.allow_lazy_installs: true  in config.yaml to auto-install on first use."
        )

    # Auto-install into <runtime_home>/memory_deps/<name>/ (outside the venv,
    # so `uv sync` never wipes it).
    target.mkdir(parents=True, exist_ok=True)
    cmd = _build_install_cmd(target, manifest.dependencies)
    logger.info("Auto-installing memory backend %r deps %s -> %s", name, manifest.dependencies, target)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise MemoryManagerError(f"Auto-install failed: neither 'uv' nor 'pip' found on PATH. Install {manifest.dependencies} manually. ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise MemoryManagerError(f"Auto-install of {manifest.dependencies} timed out (>600s).") from exc

    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-8:])
        raise MemoryManagerError(f"Auto-install of {manifest.dependencies} failed (rc={result.returncode}):\n{tail}")

    p = str(target)
    if p not in sys.path:
        sys.path.insert(0, p)
    still_missing = [n for n in manifest.import_names if not _find_spec(n)]
    if still_missing:
        raise MemoryManagerError(f"Auto-install of {manifest.dependencies} completed but {still_missing} still not importable (target={target}). Check the install output / sys.path.")
    logger.info("Auto-installed memory backend %r deps into %s", name, target)
