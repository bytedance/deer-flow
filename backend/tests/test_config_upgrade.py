import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_v26_config_upgrades_with_context_usage_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "config_version: 26\ntoken_usage:\n  enabled: true\nmodels: []\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "config-upgrade.sh")],
        cwd=REPO_ROOT,
        env={**os.environ, "DEER_FLOW_CONFIG_PATH": str(config_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    upgraded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert upgraded["config_version"] > 26
    assert upgraded["token_usage"]["counting"] == "approximate"
    assert config_path.with_suffix(".yaml.bak").is_file()
