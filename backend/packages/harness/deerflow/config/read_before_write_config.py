"""Configuration for the read-before-write file gate middleware (issue #3857)."""

from pydantic import BaseModel, Field


class ReadBeforeWriteConfig(BaseModel):
    """Deterministic version gate on file-modifying tools.

    When enabled, ``write_file`` (append or overwrite of an existing file) and
    ``str_replace`` are blocked unless the file was read (``read_file``) after
    its last modification, forcing the agent to see the file's current state
    before changing it.
    """

    enabled: bool = Field(
        default=True,
        description="Whether to block writes to existing files that were not read at their current version",
    )
