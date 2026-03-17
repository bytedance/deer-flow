"""Configuration for manuscript LaTeX generation/compilation pipeline."""

from typing import Literal

from pydantic import BaseModel, Field


class LatexConfig(BaseModel):
    """Configuration for native LaTeX manuscript pipeline."""

    enabled: bool = Field(
        default=True,
        description="Whether LaTeX manuscript build API is enabled.",
    )
    default_engine: Literal["auto", "none", "latexmk", "pdflatex", "xelatex"] = Field(
        default="auto",
        description="Default LaTeX compiler engine used when request does not specify one.",
    )
    compile_pdf_by_default: bool = Field(
        default=True,
        description="Whether to compile PDF by default (if TeX engine exists).",
    )
    compile_timeout_seconds: int = Field(
        default=120,
        ge=30,
        le=900,
        description="Timeout (seconds) for each LaTeX compile run.",
    )
    artifact_subdir: str = Field(
        default="research-writing/latex",
        description="Subdirectory under `/mnt/user-data/outputs/` for generated LaTeX artifacts.",
    )


_latex_config: LatexConfig = LatexConfig()


def get_latex_config() -> LatexConfig:
    """Get current LaTeX pipeline configuration."""
    return _latex_config


def set_latex_config(config: LatexConfig) -> None:
    """Set LaTeX pipeline configuration."""
    global _latex_config
    _latex_config = config


def load_latex_config_from_dict(config_dict: dict) -> None:
    """Load LaTeX pipeline configuration from a dictionary."""
    global _latex_config
    _latex_config = LatexConfig(**config_dict)
