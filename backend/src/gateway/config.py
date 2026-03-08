import os

from pydantic import BaseModel, Field

DEFAULT_CORS_ORIGINS = ["http://localhost:3000"]
DEFAULT_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


class GatewayConfig(BaseModel):
    """Configuration for the API Gateway."""

    host: str = Field(default="0.0.0.0", description="Host to bind the gateway server")
    port: int = Field(default=8001, description="Port to bind the gateway server")
    cors_origins: list[str] = Field(default_factory=lambda: DEFAULT_CORS_ORIGINS.copy(), description="Allowed CORS origins")
    cors_origin_regex: str = Field(
        default=DEFAULT_CORS_ORIGIN_REGEX,
        description="Regex fallback for localhost/127.0.0.1 origins on arbitrary ports",
    )


_gateway_config: GatewayConfig | None = None


def get_gateway_config() -> GatewayConfig:
    """Get gateway config, loading from environment if available."""
    global _gateway_config
    if _gateway_config is None:
        cors_origins_str = os.getenv("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS))
        cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]
        _gateway_config = GatewayConfig(
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("GATEWAY_PORT", "8001")),
            cors_origins=cors_origins or DEFAULT_CORS_ORIGINS.copy(),
            cors_origin_regex=os.getenv("CORS_ORIGIN_REGEX", DEFAULT_CORS_ORIGIN_REGEX),
        )
    return _gateway_config
