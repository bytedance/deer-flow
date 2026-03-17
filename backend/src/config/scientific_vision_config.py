"""Configuration for scientific vision pre-analysis (ImageReport injection)."""

from typing import Literal

from pydantic import BaseModel, Field


class ScientificVisionConfig(BaseModel):
    """Configuration for scientific vision pre-analysis."""

    inject_mode: Literal["index", "full"] = Field(
        default="index",
        description=("How to inject ImageReport into the main conversation. 'index' injects references + summaries (audit-friendly, token-efficient). 'full' injects full JSON content (token-heavy)."),
    )
    enabled: bool = Field(
        default=False,
        description="Whether to enable scientific vision pre-analysis (generates ImageReport from viewed images).",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for scientific image pre-analysis (None = use the current runtime model).",
    )
    artifact_subdir: str = Field(
        default="scientific-vision/image-reports",
        description="Subdirectory under `/mnt/user-data/outputs/` where ImageReport artifacts are stored.",
    )
    cache_enabled: bool = Field(
        default=True,
        description="Whether to reuse existing ImageReport artifacts when available (cache hit = skip vision model call).",
    )
    max_images: int = Field(
        default=4,
        ge=1,
        le=12,
        description="Maximum number of images to include per ImageReport generation.",
    )
    prompt_template: str | None = Field(
        default=None,
        description="Optional custom prompt template for ImageReport generation. If not provided, a default scientific-image analysis prompt is used.",
    )
    write_batch_artifact: bool = Field(
        default=True,
        description="If true, write a batch-level artifact that stores the parsed output and provenance for audit.",
    )
    include_raw_model_output_in_batch: bool = Field(
        default=True,
        description="If true, include raw model output text in the batch artifact for audit/debugging.",
    )
    write_index_artifact: bool = Field(
        default=True,
        description="If true, write an index artifact for the current injection (references per-image report artifacts).",
    )
    evidence_enabled: bool = Field(
        default=False,
        description=(
            "Whether to run type-specific evidence parsers (Western Blot/FACS/t-SNE/Spectrum) "
            "to generate audit-friendly evidence tables and ROI overlays from ImageReport."
        ),
    )
    evidence_parsers: list[str] = Field(
        default_factory=lambda: ["western_blot", "facs", "tsne", "spectrum"],
        description="Enabled evidence parsers (by ImageReport image_type).",
    )
    evidence_write_csv: bool = Field(
        default=True,
        description="If true, write evidence tables as CSV in addition to JSON.",
    )
    evidence_write_overlay: bool = Field(
        default=True,
        description="If true, write ROI overlay PNGs for visual auditing.",
    )
    clear_viewed_images_after_report: bool = Field(
        default=False,
        description="If true, clear viewed_images state after generating an ImageReport to reduce context size.",
    )


_scientific_vision_config: ScientificVisionConfig = ScientificVisionConfig()


def get_scientific_vision_config() -> ScientificVisionConfig:
    """Get the current scientific vision configuration."""
    return _scientific_vision_config


def set_scientific_vision_config(config: ScientificVisionConfig) -> None:
    """Set the scientific vision configuration."""
    global _scientific_vision_config
    _scientific_vision_config = config


def load_scientific_vision_config_from_dict(config_dict: dict) -> None:
    """Load scientific vision configuration from a dictionary."""
    global _scientific_vision_config
    _scientific_vision_config = ScientificVisionConfig(**config_dict)
