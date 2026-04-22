from __future__ import annotations

__all__ = ["GatewayConfig", "app", "get_gateway_config", "register_app"]


def __getattr__(name: str):
    if name == "app":
        from .app import app

        return app
    if name == "GatewayConfig":
        from .config import GatewayConfig

        return GatewayConfig
    if name == "get_gateway_config":
        from .config import get_gateway_config

        return get_gateway_config
    if name == "register_app":
        from .registrar import register_app

        return register_app
    raise AttributeError(name)
