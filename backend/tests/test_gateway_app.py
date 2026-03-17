import importlib

from app.gateway.config import GatewayConfig

gateway_app_module = importlib.import_module("app.gateway.app")


def _get_cors_middleware_kwargs(app):
    middleware = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    return middleware.kwargs


def test_create_app_disables_credentialed_cors_for_wildcard(monkeypatch):
    monkeypatch.setattr(gateway_app_module, "get_gateway_config", lambda: GatewayConfig(cors_origins=["*"]))

    app = gateway_app_module.create_app()

    assert _get_cors_middleware_kwargs(app)["allow_credentials"] is False


def test_create_app_keeps_credentialed_cors_for_explicit_origins(monkeypatch):
    monkeypatch.setattr(
        gateway_app_module,
        "get_gateway_config",
        lambda: GatewayConfig(cors_origins=["http://localhost:3000"]),
    )

    app = gateway_app_module.create_app()

    assert _get_cors_middleware_kwargs(app)["allow_credentials"] is True
