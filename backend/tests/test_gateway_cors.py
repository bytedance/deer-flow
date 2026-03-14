from fastapi.middleware.cors import CORSMiddleware

from src.gateway import config as gateway_config
from src.gateway.app import create_app


def _reload_gateway_config() -> None:
    gateway_config._gateway_config = None


def test_gateway_config_defaults_include_localhost_regex(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    _reload_gateway_config()

    cfg = gateway_config.get_gateway_config()

    assert cfg.cors_origins == ["http://localhost:3000"]
    assert cfg.cors_origin_regex == r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def test_gateway_config_parses_trimmed_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:3000, http://localhost:3001 ,,http://127.0.0.1:5173 ")
    _reload_gateway_config()

    cfg = gateway_config.get_gateway_config()

    assert cfg.cors_origins == [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:5173",
    ]


def test_gateway_app_registers_cors_middleware(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
    _reload_gateway_config()

    app = create_app()

    cors_layers = [middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware]
    assert len(cors_layers) == 1

    options = cors_layers[0].options
    assert options["allow_origins"] == ["http://localhost:3000", "http://localhost:3001"]
    assert options["allow_origin_regex"] == r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    assert options["allow_credentials"] is True
    assert options["allow_methods"] == ["*"]
    assert options["allow_headers"] == ["*"]
