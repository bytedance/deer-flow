"""Safe publication of Markdown generated from primary uploads."""

from pathlib import Path

from deerflow.uploads.layout import (
    UnsafeConversionPathError,
    conversion_path_for_upload,
    ensure_conversion_dir,
)
from deerflow.uploads.manager import (
    abort_staged_upload,
    create_upload_staging_file,
    replace_system_owned_staged_file,
)
from deerflow.utils.file_conversion import convert_file_to_markdown


async def convert_uploaded_file_to_markdown(upload_path: Path) -> Path | None:
    """Convert one primary upload and atomically publish its owned Markdown."""
    conversion_dir = ensure_conversion_dir(upload_path.parent)
    target = conversion_path_for_upload(upload_path)
    staged = create_upload_staging_file(conversion_dir)
    staged.handle.close()
    try:
        result = await convert_file_to_markdown(upload_path, output_path=staged.path)
        if result is None:
            abort_staged_upload(staged)
            return None
        if Path(result) != staged.path:
            raise UnsafeConversionPathError("Converter returned an unexpected output path")
        return replace_system_owned_staged_file(staged, target.name)
    except Exception:
        abort_staged_upload(staged)
        raise
