"""Local nginx must use the writable directories prepared by its launchers."""

import re

import pytest
from support.nginx_conf import REPO_ROOT, read_config


@pytest.mark.parametrize("kind", ["client_body", "proxy", "fastcgi", "uwsgi", "scgi"])
def test_local_nginx_temp_path_matches_launchers(kind: str) -> None:
    directory = f"temp/{kind}_temp"
    config = read_config("docker/nginx/nginx.local.conf")
    paths = re.findall(rf"^[ \t]*{kind}_temp_path[ \t]+([^;\n]+);", config, re.M)
    assert paths == [directory]

    for launcher in ("scripts/serve.sh", "scripts/nginx.sh"):
        lines = (REPO_ROOT / launcher).read_text(encoding="utf-8").splitlines()
        assert any(line.startswith("mkdir -p ") and directory in line.split()[2:] for line in lines), f"{launcher} must create {directory} before starting nginx"
