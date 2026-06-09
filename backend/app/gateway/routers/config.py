"""App configuration endpoint for frontend UI settings."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig

router = APIRouter(prefix="/api", tags=["config"])


class UIConfigResponse(BaseModel):
    """UI configuration response model."""

    show_bash_script: bool = Field(default=True, description="Whether to show bash command scripts in frontend chat UI")


class AppConfigResponse(BaseModel):
    """App configuration response model."""

    ui: UIConfigResponse


@router.get(
    "/config",
    response_model=AppConfigResponse,
    summary="Get App Configuration",
    description="Retrieve application configuration settings for the frontend.",
)
async def get_app_config(config: AppConfig = Depends(get_config)) -> AppConfigResponse:
    """Get application configuration for frontend.

    Returns UI-related configuration settings that control frontend behavior.

    Returns:
        App configuration including UI settings.

    Example Response:
        ```json
        {
            "ui": {
                "show_bash_script": true
            }
        }
        ```
    """
    return AppConfigResponse(
        ui=UIConfigResponse(show_bash_script=config.ui.show_bash_script),
    )
