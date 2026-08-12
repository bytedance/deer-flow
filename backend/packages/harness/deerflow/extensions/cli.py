"""Command-line interface for installing and managing trusted extensions."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from deerflow.extensions.manager import ExtensionManager

_NAME_ENV = "DEER_FLOW_EXTENSION_NAME"
_SOURCE_ENV = "DEER_FLOW_EXTENSION_SOURCE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deerflow extensions",
        description="Install and manage trusted Python extensions for this DeerFlow checkout.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="install an extension and enable it in config.yaml")
    install.add_argument("--source-env", action="store_true", help=argparse.SUPPRESS)
    install.add_argument("source", help="local directory, Python package requirement, or Git URL")
    install.add_argument(
        "--yes",
        action="store_true",
        help="acknowledge that installing an extension executes trusted third-party code",
    )
    install.add_argument(
        "--required",
        action="store_true",
        help="abort Gateway startup when this extension fails to load (default: report and skip)",
    )
    disable = commands.add_parser("disable", help="disable an extension without uninstalling it")
    disable.add_argument("--name-env", action="store_true", help=argparse.SUPPRESS)
    disable.add_argument("name", help="extension name, distribution, or module:install entry point")
    enable = commands.add_parser("enable", help="enable an installed extension")
    enable.add_argument("--name-env", action="store_true", help=argparse.SUPPRESS)
    enable.add_argument("name", help="extension name, distribution, or module:install entry point")
    commands.add_parser("list", help="list configured extensions")
    remove = commands.add_parser("remove", help="uninstall an extension and remove its config entry")
    remove.add_argument("--name-env", action="store_true", help=argparse.SUPPRESS)
    remove.add_argument("name", help="extension name, distribution, or module:install entry point")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        root = find_project_root()
        configured_path = os.environ.get("DEER_FLOW_CONFIG_PATH")
        manager = ExtensionManager(root, config_path=configured_path)
        if args.command == "install":
            source = _source_argument(args)
            trusted = args.yes
            if not trusted:
                print("Warning: a Python extension executes code with Gateway privileges.")
                try:
                    trusted = input("Install this trusted source? [y/N] ").strip().lower() in {"y", "yes"}
                except EOFError:
                    trusted = False
                if not trusted:
                    print("Extension installation cancelled.", file=sys.stderr)
                    return 2
            installed = manager.install(source, yes=trusted, required=args.required)
            print(f"Installed and enabled {installed.name} ({installed.distribution}). Restart DeerFlow to load it.")
            return 0
        if args.command == "disable":
            name = manager.set_enabled(_name_argument(args), enabled=False)
            print(f"Disabled {name}. Restart DeerFlow to apply the change.")
            return 0
        if args.command == "enable":
            name = manager.set_enabled(_name_argument(args), enabled=True)
            print(f"Enabled {name}. Restart DeerFlow to apply the change.")
            return 0
        if args.command == "list":
            configured = manager.list_configured()
            print("NAME\tSTATE\tPACKAGE\tENTRY POINT")
            for extension in configured:
                state = "enabled" if extension.enabled else "disabled"
                print(f"{extension.name}\t{state}\t{extension.distribution}\t{extension.use}")
            return 0
        if args.command == "remove":
            name = manager.remove(_name_argument(args))
            print(f"Removed {name}. Restart DeerFlow to apply the change.")
            return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"extension command failed: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled extension command: {args.command}")


def _name_argument(args: argparse.Namespace) -> str:
    if not args.name_env:
        return args.name
    name = os.environ.get(_NAME_ENV)
    if name is None or not name.strip():
        raise ValueError(f"{_NAME_ENV} must contain an extension name")
    return name


def _source_argument(args: argparse.Namespace) -> str:
    if not args.source_env:
        return args.source
    source = os.environ.get(_SOURCE_ENV)
    if source is None or not source.strip():
        raise ValueError(f"{_SOURCE_ENV} must contain an extension source")
    return source


def find_project_root() -> Path:
    configured = os.environ.get("DEER_FLOW_PROJECT_ROOT")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if (candidate / "backend" / "pyproject.toml").is_file():
            return candidate
        raise FileNotFoundError(f"DEER_FLOW_PROJECT_ROOT is not a DeerFlow checkout: {candidate}")

    candidates = (Path.cwd(), *Path.cwd().parents)
    for candidate in candidates:
        candidate = candidate.resolve()
        if (candidate / "backend" / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("could not find a DeerFlow checkout; set DEER_FLOW_PROJECT_ROOT")
