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
    elide_blocked_payloads: bool = Field(
        default=True,
        description=(
            "Replace the payload arguments of gate-blocked calls (write_file content, str_replace old_str/new_str) "
            "with a short placeholder in model-bound requests. A blocked call never ran and must be re-issued after a "
            "re-read, so its payload is dead weight in every later model call. Only the request copy changes: stored "
            "message history, receipts, and the run journal keep the original arguments."
        ),
    )
    elide_min_chars: int = Field(
        default=2000,
        ge=0,
        description=("Elide only payload fields at least this many characters long; shorter payloads stay visible so the model can reuse them after re-reading. 0 elides every non-empty payload."),
    )
