from __future__ import annotations

from pathlib import Path


def _nginx_config() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "docker" / "nginx" / "nginx.conf").read_text(encoding="utf-8")


def test_nginx_does_not_route_public_sandboxes_to_provisioner():
    config = _nginx_config()

    assert "location /api/sandboxes" not in config
    assert "provisioner:8002" not in config
    assert "$provisioner_upstream" not in config


def test_nginx_still_routes_gateway_thread_endpoints():
    config = _nginx_config()

    assert "location ~ ^/api/threads" in config
    assert "proxy_pass http://gateway;" in config
