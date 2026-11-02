"""User-selectable evolution mode, persisted as JSON beside the install.

``evolution_mode`` selects how annotation feedback evolves a skill:

- ``"model"`` (the default) — a host-granted model reviews the current
  content plus the annotations and produces an evolution draft
  (``evolve.py`` background jobs).
- ``"append"`` — deterministic and offline: the feedback notes are appended
  directly to the skill content (``drafts.py``), no model call.

With storage_path configured, settings live beside the SQLite store, in
``<database-filename>.settings.json``. Legacy installation-local settings
are migrated without overwriting an existing persistent choice. Without a
store, the installation-local file remains a compatibility fallback.
Reads happen per call, so mode changes apply immediately.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

MODE_MODEL = "model"
MODE_APPEND = "append"
MODES = (MODE_MODEL, MODE_APPEND)
DEFAULT_MODE = MODE_MODEL
KEY = "evolution_mode"
_FILE_NAME = "settings.json"


def settings_path() -> Path:
    """The JSON settings file beside the installed package."""
    return Path(__file__).resolve().parent / _FILE_NAME


def read_evolution_mode(*, path: Path | None = None) -> str:
    """The persisted evolution mode, or the default when unset/unreadable."""
    target = path if path is not None else settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_MODE
    if isinstance(data, dict) and data.get(KEY) in MODES:
        return data[KEY]
    return DEFAULT_MODE


def write_evolution_mode(mode: str, *, path: Path | None = None) -> None:
    """Persist the evolution mode, preserving any other JSON keys.

    Raises ``ValueError`` for a value outside the enum; the caller maps that
    to an action error before anything is written.
    """
    if mode not in MODES:
        raise ValueError(f"evolution_mode must be one of {', '.join(MODES)}, got {mode!r}")
    target = path if path is not None else settings_path()
    data: dict[str, object] = {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    data[KEY] = mode
    _write_settings(target, data)


def _write_settings(target: Path, data: dict[str, object], *, replace: bool = True) -> None:
    """Publish a private, unique temporary file; migration never overwrites."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp, target)
        else:
            try:
                os.link(temp, target)
            except FileExistsError:
                pass
    finally:
        temp.unlink(missing_ok=True)


class EvolutionModeSettings:
    """One installation's live settings, bound once to its configured store."""

    def __init__(self, storage_path: str | None = None, *, legacy_path: Path | None = None) -> None:
        if storage_path and not Path(storage_path).is_absolute():
            raise ValueError("storage_path must be an absolute deployment-owned path")
        legacy = legacy_path if legacy_path is not None else settings_path()
        self.path = Path(storage_path).with_name(Path(storage_path).name + ".settings.json") if storage_path else legacy
        self._legacy = legacy
        if self.path != legacy and not self.path.exists():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return  # Legacy settings are optional.
            if isinstance(data, dict) and data.get(KEY) in MODES:
                try:
                    _write_settings(self.path, data, replace=False)
                except OSError:
                    logger.warning("skill-evolution: could not migrate legacy settings; explicit save required before upgrade", exc_info=True)

    def read(self) -> str:
        return read_evolution_mode(path=self.path if self.path.exists() else self._legacy)

    def write(self, mode: str) -> None:
        write_evolution_mode(mode, path=self.path)


def main(argv: list[str] | None = None) -> int:
    """Run from the new source before upgrading an older installed package."""
    import argparse

    parser = argparse.ArgumentParser(description="Preserve legacy evolution settings before replacing the installed extension")
    parser.add_argument("--storage-path", required=True, type=Path)
    parser.add_argument("--legacy-settings", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.storage_path.is_absolute():
        parser.error("--storage-path must be absolute")
    try:
        data = json.loads(args.legacy_settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        parser.error("--legacy-settings must be a readable JSON settings file")
    if not isinstance(data, dict) or data.get(KEY) not in MODES:
        parser.error("legacy settings must contain a valid evolution_mode")
    state = EvolutionModeSettings(str(args.storage_path), legacy_path=args.legacy_settings)
    if not state.path.is_file():
        parser.error("could not persist settings; do not upgrade until migration succeeds")
    print(f"Persistent evolution settings: {state.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
