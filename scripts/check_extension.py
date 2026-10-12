"""Build and inspect a trusted extension wheel without installing its code.

Run from the checkout root with the backend environment:
uv run --project backend --no-sync python scripts/check_extension.py PACKAGE
"""

from __future__ import annotations

import argparse
import ast
import configparser
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from email.parser import Parser
from pathlib import Path, PurePosixPath, PureWindowsPath
from zipfile import BadZipFile, ZipFile

from deerflow_extension_api import API_VERSION, BrowserAssets
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from deerflow.extensions.browser_assets import load_browser_assets
from deerflow.extensions.manager import _validate_entry_point


def check_wheel(source: Path, wheel: Path, *, manifests: Sequence[str] = ()) -> None:
    with (
        ZipFile(wheel) as archive,
        tempfile.TemporaryDirectory(prefix="deerflow-extension-wheel-") as temporary,
    ):
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate wheel paths")
        for name in names:
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or PureWindowsPath(name).drive
                or ".." in path.parts
                or "\\" in name
            ):
                raise ValueError("Invalid wheel path")

        metadata_paths = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_paths) != 1:
            raise ValueError("Expected one wheel distribution")
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
        requirements = [
            Requirement(value) for value in metadata.get_all("Requires-Dist", [])
        ]
        api = [
            requirement
            for requirement in requirements
            if canonicalize_name(requirement.name) == "deerflow-extension-api"
            and (
                requirement.marker is None or requirement.marker.evaluate({"extra": ""})
            )
        ]
        if not api or any(
            API_VERSION not in requirement.specifier for requirement in api
        ):
            raise ValueError(
                f"Declare a deerflow-extension-api dependency compatible with this checkout ({API_VERSION})"
            )

        entry_path = str(PurePosixPath(metadata_paths[0]).parent / "entry_points.txt")
        entries = configparser.ConfigParser(interpolation=None)
        entries.optionxform = str
        if entry_path in names:
            entries.read_string(archive.read(entry_path).decode("utf-8"))
        if (
            not entries.has_section("deerflow.extensions")
            or len(entries["deerflow.extensions"]) != 1
        ):
            raise ValueError("Declare exactly one deerflow.extensions entry point")
        entry_name, target = next(iter(entries["deerflow.extensions"].items()))
        _validate_entry_point(entry_name, target)
        module, _ = target.rsplit(":", 1)
        module_path = module.replace(".", "/")
        if not any(
            name in names
            for name in (f"{module_path}.py", f"{module_path}/__init__.py")
        ):
            raise ValueError("Extension entry module is not packaged")
        for name in names:
            if name.endswith(".py"):
                ast.parse(archive.read(name), filename=name)

        # Existing examples use flat or src-layout packages and ui_manifest.json.
        # Custom manifest names are explicit rather than guessing from plugin code.
        manifest_paths = set(manifests)
        top_module = module.split(".")[0]
        for import_root in (source, source / "src"):
            package = import_root / top_module
            if package.is_dir():
                manifest_paths.update(
                    path.relative_to(import_root).as_posix()
                    for path in package.rglob("ui_manifest.json")
                )
            elif (
                package.with_suffix(".py").is_file()
                and (import_root / "ui_manifest.json").is_file()
            ):
                manifest_paths.add("ui_manifest.json")
        manifest_paths.update(
            name for name in names if PurePosixPath(name).name == "ui_manifest.json"
        )
        for manifest in manifest_paths:
            if manifest not in names:
                raise ValueError(f"Browser manifest is not packaged: {manifest}")
        if manifest_paths:
            archive.extractall(temporary)
        for manifest in sorted(manifest_paths):
            path = Path(temporary) / manifest
            load_browser_assets(BrowserAssets("check", path.parent, manifest=path.name))

        print(f"Entry point: {entry_name} = {target}")
        print(f"API dependency: compatible with {API_VERSION}")
        print(f"Browser manifests: {len(manifest_paths)} checked")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and check a trusted Python extension package using the current DeerFlow contract."
    )
    parser.add_argument(
        "package", type=Path, help="directory containing pyproject.toml"
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="custom browser manifest path inside the wheel (repeatable)",
    )
    args = parser.parse_args()
    try:
        source = args.package.resolve()
        if not (source / "pyproject.toml").is_file():
            raise ValueError("Package directory must contain pyproject.toml")
        with tempfile.TemporaryDirectory(
            prefix="deerflow-extension-check-"
        ) as temporary:
            result = subprocess.run(
                ["uv", "build", str(source), "--wheel", "--out-dir", temporary],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            if result.returncode:
                raise ValueError(f"Wheel build failed:\n{result.stderr}")
            wheels = list(Path(temporary).glob("*.whl"))
            if len(wheels) != 1:
                raise ValueError("Build must produce one wheel")
            check_wheel(source, wheels[0], manifests=args.manifest)
            print(f"Packaging checks passed: {wheels[0].name}")
        return 0
    except (
        OSError,
        ValueError,
        SyntaxError,
        BadZipFile,
        configparser.Error,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"Extension check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
