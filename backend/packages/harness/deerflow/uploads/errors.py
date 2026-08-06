"""Shared upload validation and publication errors."""


class PathTraversalError(ValueError):
    """Raised when a path escapes its allowed base directory."""


class UnsafeUploadPathError(ValueError):
    """Raised when an upload destination is not a safe regular file path."""


class AtomicUploadPublishError(UnsafeUploadPathError):
    """Raised when storage cannot honor atomic no-replace publication."""
