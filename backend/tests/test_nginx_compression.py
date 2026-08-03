from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = (
    REPO_ROOT / "docker/nginx/nginx.conf",
    REPO_ROOT / "docker/nginx/nginx.local.conf",
)


@pytest.mark.parametrize("config_path", CONFIGS, ids=lambda path: path.name)
def test_nginx_compresses_only_safe_textual_responses(config_path: Path) -> None:
    config = config_path.read_text(encoding="utf-8")

    assert "gzip on;" in config
    assert "gzip_vary on;" in config
    assert "gzip_proxied any;" in config
    assert "gzip_min_length 1024;" in config
    assert "gzip_comp_level 5;" in config

    gzip_types = config.split("gzip_types", 1)[1].split(";", 1)[0].split()
    assert gzip_types == [
        "text/css",
        "text/javascript",
        "application/javascript",
        "application/json",
        "application/xml",
        "image/svg+xml",
    ]
    assert "text/event-stream" not in gzip_types
    assert not any(content_type.startswith(("font/", "audio/", "video/")) for content_type in gzip_types)
