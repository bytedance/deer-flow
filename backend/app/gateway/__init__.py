from .config import GatewayConfig, get_gateway_config

__all__ = ["app", "create_app", "GatewayConfig", "get_gateway_config"]


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from .app import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
