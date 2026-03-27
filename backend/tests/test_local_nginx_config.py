from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_LOCAL_CONF = REPO_ROOT / "docker" / "nginx" / "nginx.local.conf"
SERVE_SCRIPT = REPO_ROOT / "scripts" / "serve.sh"
START_DAEMON_SCRIPT = REPO_ROOT / "scripts" / "start-daemon.sh"


def test_local_nginx_uses_repo_body_temp_path():
    config = NGINX_LOCAL_CONF.read_text(encoding="utf-8")

    assert "client_body_temp_path logs/client_body_temp;" in config
    assert "proxy_request_buffering off;" in config


def test_local_start_scripts_create_nginx_body_temp_dir():
    expected = "mkdir -p logs logs/client_body_temp"

    assert expected in SERVE_SCRIPT.read_text(encoding="utf-8")
    assert expected in START_DAEMON_SCRIPT.read_text(encoding="utf-8")
