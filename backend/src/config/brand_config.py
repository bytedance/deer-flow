"""Configuration for frontend brand settings."""

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


def _derive_domain(name: str) -> str:
    normalized = name.strip().lower()
    if "://" in normalized:
        parsed = urlparse(normalized)
        if parsed.netloc:
            return parsed.netloc
    if "." in normalized:
        return normalized.replace(" ", "")

    slug = re.sub(r"[^a-z0-9-]+", "-", normalized).strip("-")
    return f"{slug or 'thinktank'}.ai"


def _derive_repo_slug(domain: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", domain.replace(".", "-")).strip("-") or "thinktank-ai"


class BrandConfig(BaseModel):
    """Configuration for brand display and links in the frontend."""

    name: str = Field(default="Dominium AI", min_length=1, description="Display brand name")
    website_url: str | None = Field(default=None, description="Official website URL")
    github_url: str | None = Field(default=None, description="GitHub repository URL")
    support_email: str | None = Field(default=None, description="Support contact email")

    @model_validator(mode="after")
    def apply_derived_defaults(self) -> "BrandConfig":
        domain = _derive_domain(self.name)
        repo_slug = _derive_repo_slug(domain)

        if not self.website_url:
            self.website_url = f"https://{domain}"
        if not self.github_url:
            self.github_url = f"https://github.com/{repo_slug}/{repo_slug}"
        if not self.support_email:
            self.support_email = f"support@{domain}"
        return self


_brand_config: BrandConfig = BrandConfig()


def get_brand_config() -> BrandConfig:
    """Get the current brand configuration."""
    return _brand_config


def set_brand_config(config: BrandConfig) -> None:
    """Set the brand configuration."""
    global _brand_config
    _brand_config = config


def load_brand_config_from_dict(config_dict: dict) -> None:
    """Load brand configuration from a dictionary."""
    global _brand_config
    _brand_config = BrandConfig(**config_dict)
