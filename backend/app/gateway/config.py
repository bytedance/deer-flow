import os

from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    """Configuration for the API Gateway."""

    host: str = Field(default="0.0.0.0", description="Host to bind the gateway server")
    port: int = Field(default=8001, description="Port to bind the gateway server")
    enable_docs: bool = Field(default=True, description="Enable Swagger/ReDoc/OpenAPI endpoints")


_gateway_config: GatewayConfig | None = None


def get_gateway_config() -> GatewayConfig:
    """Get gateway config, loading from environment if available."""
    global _gateway_config
    if _gateway_config is None:
        _gateway_config = GatewayConfig(
            # A blank means "unset" (`-e GATEWAY_PORT=`, or `${PORT}` with PORT unset); int("") would abort the create_app() import
            host=os.getenv("GATEWAY_HOST") or "0.0.0.0",
            port=int(os.getenv("GATEWAY_PORT") or "8001"),
            enable_docs=os.getenv("GATEWAY_ENABLE_DOCS", "true").lower() == "true",
        )
    return _gateway_config
