"""Application configuration endpoints for frontend consumption."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.config.app_config import get_app_config

router = APIRouter(prefix="/api", tags=["config"])


class BrandConfigResponse(BaseModel):
    """Brand settings exposed to the frontend."""

    name: str = Field(..., description="Display brand name")
    website_url: str | None = Field(default=None, description="Official website URL")
    github_url: str | None = Field(default=None, description="GitHub repository URL")
    support_email: str | None = Field(default=None, description="Support email address")


class AppConfigResponse(BaseModel):
    """Frontend-safe subset of application configuration."""

    brand: BrandConfigResponse


@router.get(
    "/config",
    response_model=AppConfigResponse,
    summary="Get Application Configuration",
    description="Retrieve frontend-safe runtime configuration values.",
)
async def get_application_config() -> AppConfigResponse:
    """Return public app configuration required by the frontend."""
    config = get_app_config()
    return AppConfigResponse(brand=BrandConfigResponse(**config.brand.model_dump()))
