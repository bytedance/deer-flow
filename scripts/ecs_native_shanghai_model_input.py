"""Provision only the trusted original DeepSeek selection via SSH stdin."""

import io
import json
import re
import subprocess
from pathlib import Path
import yaml
from dotenv import dotenv_values

CONFIG = Path("/Users/wenbinwang/Documents/git/deerflow2/config.yaml")
ENV = CONFIG.with_name(".env")
KEY = Path("/Users/wenbinwang/Documents/docs/genbalde/key/genbalde-drama-keypair.pem")
FIELDS = {
    "api_key",
    "display_name",
    "max_tokens",
    "model",
    "name",
    "supports_thinking",
    "supports_vision",
    "use",
}


def main():
    assert not CONFIG.is_symlink() and not ENV.is_symlink()
    selected = next(
        model.copy()
        for model in yaml.safe_load(CONFIG.read_text())["models"]
        if model["name"] == "deepseek-chat"
    )
    assert set(selected) == FIELDS
    assert selected["use"] == "deerflow.models.patched_deepseek:PatchedChatDeepSeek"
    assert (
        selected["api_key"] == "$DEEPSEEK_API_KEY"
        and selected["model"] == "deepseek-chat"
    )
    # Only the selected assignment enters the dotenv parser; no whole env mapping.
    with ENV.open() as stream:
        assignments = [
            line
            for line in stream
            if re.match(r"^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=", line)
        ]
    assert len(assignments) == 1
    value = dotenv_values(stream=io.StringIO(assignments[0]), interpolate=False)[
        "DEEPSEEK_API_KEY"
    ]
    assert value and re.fullmatch(r"sk-[A-Za-z0-9_-]+", value)
    payload = json.dumps(
        {"model": selected, "environment": {"DEEPSEEK_API_KEY": value}}
    ).encode()
    args = [
        "ssh",
        "-i",
        str(KEY),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "HostKeyAlias=192.168.0.190",
        "-o",
        "UserKnownHostsFile=/private/tmp/deer-native-known-hosts",
        "root@101.133.235.59",
        "python3",
        "/srv/deerflow-native-task6b/56636cebddc6/bootstrap/ecs_native_shanghai_c_config.py",
        "receive",
    ]
    result = subprocess.run(args, input=payload, capture_output=True, timeout=30)
    assert result.returncode == 0
    receipt = json.loads(result.stdout)
    assert receipt == {
        "selected_model_received": True,
        "environment_references": ["DEEPSEEK_API_KEY"],
        "models_called": False,
    }
    print(json.dumps(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Selected DeepSeek provisioning refused; private details withheld"
        ) from None
