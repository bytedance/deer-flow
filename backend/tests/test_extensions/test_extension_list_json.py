from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from deerflow.tui.cli import main as deerflow_main


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "deer-flow"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "pyproject.toml").write_text('[project]\nname = "inventory-test"\n', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    return root


def test_json_inventory_preserves_order_defaults_and_only_public_fields(checkout: Path, capsys) -> None:
    plugins = [
        {
            "name": '演示 "extension"\nsecond line',
            "package": "deerflow-extension-demo",
            "use": "not_installed_demo:install",
            "enabled": "false",
            "required": "true",
            "config": {"token": "private-test-value", "nested": {"path": "/private/source"}},
        },
        {"use": "not_installed_other:install"},
    ]
    (checkout / "config.yaml").write_text(yaml.safe_dump({"plugins": plugins}), encoding="utf-8")

    assert deerflow_main(["extensions", "list", "--json"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    inventory = json.loads(captured.out)
    assert inventory == [
        {
            "name": plugins[0]["name"],
            "package": "deerflow-extension-demo",
            "entry_point": "not_installed_demo:install",
            "enabled": False,
            "required": True,
        },
        {"name": "not_installed_other:install", "package": "-", "entry_point": "not_installed_other:install", "enabled": True, "required": False},
    ]
    for extension in inventory:
        assert isinstance(extension["enabled"], bool)
        assert isinstance(extension["required"], bool)


@pytest.mark.parametrize("config", ["plugins: []\n", "plugins:\n", "config_version: 1\n"])
def test_json_empty_inventory(checkout: Path, capsys, config: str) -> None:
    (checkout / "config.yaml").write_text(config, encoding="utf-8")

    assert deerflow_main(["extensions", "list", "--json"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert captured.err == ""


@pytest.mark.parametrize("args", [[], ["--json"]], ids=["table", "json"])
@pytest.mark.parametrize(
    "config",
    [
        None,
        "plugins: [\n",
        "- not-a-mapping\n",
        "plugins: {}\n",
        "plugins: []\nplugins: []\n",
        "plugins:\n  - use: valid:install\n  - name: missing-use\n",
    ],
    ids=["missing-file", "invalid-yaml", "invalid-root", "invalid-plugins", "duplicate-key", "invalid-later-entry"],
)
def test_list_config_errors_have_no_partial_stdout(checkout: Path, capsys, args: list[str], config: str | None) -> None:
    if config is not None:
        (checkout / "config.yaml").write_text(config, encoding="utf-8")

    assert deerflow_main(["extensions", "list", *args]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "extension command failed:" in captured.err
    assert "Traceback" not in captured.err


def test_default_table_output_is_unchanged(checkout: Path, capsys) -> None:
    (checkout / "config.yaml").write_text(
        "plugins:\n  - name: demo\n    package: demo-package\n    use: demo:install\n    required: true\n  - use: other:install\n    enabled: false\n",
        encoding="utf-8",
    )

    assert deerflow_main(["extensions", "list"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "NAME\tSTATE\tPACKAGE\tENTRY POINT\ndemo\tenabled\tdemo-package\tdemo:install\nother:install\tdisabled\t-\tother:install\n"
    assert captured.err == ""


def test_console_json_uses_selected_config_without_executing_plugins_or_writing_files(checkout: Path) -> None:
    (checkout / "config.yaml").write_text("plugins: []\n", encoding="utf-8")
    selected = checkout / "deployment.yaml"
    selected.write_text("plugins:\n  - use: must_not_import:install\n    required: true\n", encoding="utf-8")
    # Importing this configured entry point would fail the command and leave evidence.
    (checkout / "must_not_import.py").write_text(
        "from pathlib import Path\nPath('plugin-executed').touch()\nraise RuntimeError('plugin must not run')\n",
        encoding="utf-8",
    )
    before = {path.relative_to(checkout): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}
    env = {**os.environ, "DEER_FLOW_CONFIG_PATH": str(selected), "PYTHONPATH": str(checkout)}
    console = Path(sys.executable).parent / ("deerflow.exe" if os.name == "nt" else "deerflow")

    result = subprocess.run([str(console), "extensions", "list", "--json"], cwd=checkout, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == [{"name": "must_not_import:install", "package": "-", "entry_point": "must_not_import:install", "enabled": True, "required": True}]
    assert {path.relative_to(checkout): path.read_bytes() for path in checkout.rglob("*") if path.is_file()} == before
