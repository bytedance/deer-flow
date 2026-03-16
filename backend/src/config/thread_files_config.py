from pydantic import BaseModel, Field


class ThreadFilesFeatureConfig(BaseModel):
    """Backend selection for a thread-files feature area."""

    backend: str = Field(default="local", description="Thread-files backend: 'local' or 'r2'.")


class ThreadFilesFeaturesConfig(BaseModel):
    """Feature-scoped thread-files backend selection."""

    uploads: ThreadFilesFeatureConfig = Field(default_factory=ThreadFilesFeatureConfig)
    upload_markdown_sidecars: ThreadFilesFeatureConfig = Field(default_factory=ThreadFilesFeatureConfig)
    workspace: ThreadFilesFeatureConfig = Field(default_factory=ThreadFilesFeatureConfig)
    outputs: ThreadFilesFeatureConfig = Field(default_factory=ThreadFilesFeatureConfig)
    artifact_reads: ThreadFilesFeatureConfig = Field(default_factory=ThreadFilesFeatureConfig)


class ThreadFilesR2Config(BaseModel):
    """Cloudflare R2 configuration for thread-files storage."""

    bucket: str = Field(default="")
    endpoint: str = Field(default="")
    access_key_id: str = Field(default="")
    secret_access_key: str = Field(default="")
    region: str = Field(default="auto")
    key_prefix: str = Field(default="thread-files")


class ThreadFilesConfig(BaseModel):
    """Top-level thread-files storage configuration."""

    features: ThreadFilesFeaturesConfig = Field(default_factory=ThreadFilesFeaturesConfig)
    r2: ThreadFilesR2Config = Field(default_factory=ThreadFilesR2Config)

    def backend_for_feature(self, feature: str) -> str:
        mapping = {
            "uploads": self.features.uploads.backend,
            "upload_markdown_sidecars": self.features.upload_markdown_sidecars.backend,
            "workspace": self.features.workspace.backend,
            "outputs": self.features.outputs.backend,
            "artifact_reads": self.features.artifact_reads.backend,
        }
        backend = (mapping.get(feature) or "local").strip().lower()
        if backend not in {"local", "r2"}:
            raise ValueError(f"Unsupported thread_files backend '{backend}' for feature '{feature}'")
        return backend
