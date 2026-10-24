"""Middleware to inject current-run uploaded files into the agent context.

Historical uploads are no longer injected every turn — the agent discovers them
on demand via the ``list_uploaded_files`` tool.
"""

import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.runnables import run_in_executor
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.uploads.manager import is_upload_staging_file
from deerflow.utils.file_outline import extract_outline_for_file
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, message_content_to_text, restore_original_human_message
from deerflow.utils.upload_context import UPLOAD_CONTEXT_KEY, UPLOAD_CONTEXT_VERSION, upload_context_text

logger = logging.getLogger(__name__)

_MAX_FILES_PER_CONTEXT_SECTION = 10
_MAX_DISPLAY_FILE_SIZE_BYTES = 1024**4
_INLINE_UPLOAD_CONTEXT_RE = re.compile(r"<(?P<tag>current_uploads|uploaded_files)>(?P<body>.*?)</(?P=tag)>", re.DOTALL | re.IGNORECASE)


def _has_ambiguous_inline_upload_context(content: object) -> bool:
    """Decline pristine-content claims for legacy-shaped file descriptions.

    This only selects the legacy compatibility path; it never removes text or
    infers which substring belongs to the user. Bare literal tag examples do
    not resemble file context and remain eligible for structured capture.
    """
    return any("/mnt/user-data/uploads/" in match["body"] or "The following files were uploaded" in match["body"] for match in _INLINE_UPLOAD_CONTEXT_RE.finditer(message_content_to_text(content)))


def _extension_label(file: dict) -> str:
    extension = str(file.get("extension") or Path(str(file.get("filename") or "")).suffix).lower()
    return neutralize_untrusted_tags(extension) or "(no extension)"


def _format_omitted_file_types(files: list[dict]) -> str:
    counts = Counter(_extension_label(file) for file in files)
    parts = [f"{count} {extension}" for extension, count in sorted(counts.items())]
    return neutralize_untrusted_tags(", ".join(parts))


class UploadsMiddlewareState(AgentState):
    """State schema for uploads middleware."""

    uploaded_files: NotRequired[list[dict] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """Middleware to inject current-run uploaded files into the agent context.

    Reads file metadata from the current message's additional_kwargs.files
    (set by the frontend after upload) and records a structured context envelope
    on the last human message. Model/summary projections render its
    <current_uploads> block; persisted user content stays unchanged.

    Historical uploads are NOT injected — the agent discovers them on demand
    via the ``list_uploaded_files`` tool.
    """

    state_schema = UploadsMiddlewareState

    def __init__(
        self,
        base_dir: str | None = None,
        *,
        max_files_per_context_section: int = _MAX_FILES_PER_CONTEXT_SECTION,
    ):
        """Initialize the middleware.

        Args:
            base_dir: Base directory for thread data. Defaults to Paths resolution.
            max_files_per_context_section: Maximum number of files listed in
                each uploaded-files prompt section.
        """
        super().__init__()
        if max_files_per_context_section < 1:
            raise ValueError("max_files_per_context_section must be at least 1")
        self._paths = Paths(base_dir) if base_dir else get_paths()
        self._max_files_per_context_section = max_files_per_context_section

    def _format_file_entry(self, file: dict, lines: list[str]) -> None:
        """Append a single file entry (name, size, path, optional outline) to lines.

        User-derived values (filename, path, outline titles, preview text) are
        neutralized via ``neutralize_untrusted_tags`` so a crafted filename or
        document cannot embed blocked authority tags inside the trusted
        ``<current_uploads>`` wrapper.
        """
        if file["size"] >= _MAX_DISPLAY_FILE_SIZE_BYTES:
            size_str = ">= 1 TB"
        else:
            size_kb = file["size"] / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        lines.append(f"- {neutralize_untrusted_tags(file['filename'])} ({size_str})")
        lines.append(f"  Path: {neutralize_untrusted_tags(file['path'])}")
        if file.get("selection_reason") == "query_match":
            lines.append("  Selected because: matched the current query.")
        outline = file.get("outline") or []
        if outline:
            truncated = outline[-1].get("truncated", False)
            visible = [e for e in outline if not e.get("truncated")]
            lines.append("  Document outline (use `read_file` with line ranges to read sections):")
            for entry in visible:
                lines.append(f"    L{entry['line']}: {neutralize_untrusted_tags(entry['title'])}")
            if truncated:
                lines.append(f"    ... (showing first {len(visible)} headings; use `read_file` to explore further)")
        else:
            preview = file.get("outline_preview") or []
            if preview:
                lines.append("  No structural headings detected. Document begins with:")
                for text in preview:
                    lines.append(f"    > {neutralize_untrusted_tags(text)}")
            lines.append("  Use `grep` to search for keywords (e.g. `grep(pattern='keyword', path='/mnt/user-data/uploads/')`).")
        lines.append("")

    def _select_files_for_context(
        self,
        files: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """Return bounded context files in upload order."""
        selected = [dict(f) for f in files[: self._max_files_per_context_section]]
        omitted = [dict(f) for f in files[self._max_files_per_context_section :]]
        return selected, omitted

    def _create_files_message(
        self,
        files: list[dict],
        *,
        omitted_files: list[dict] | None = None,
    ) -> str:
        """Create a formatted message listing current-run uploaded files.

        Args:
            files: Files uploaded in the current message.
            omitted_files: Files omitted from the prompt context (over cap).

        Returns:
            Formatted string inside <current_uploads> tags.
        """
        lines = ["<current_uploads>"]

        lines.append("The following files were uploaded in this message:")
        lines.append("")
        if files:
            for file in files:
                self._format_file_entry(file, lines)
            if omitted_files:
                lines.append(f"... ({len(omitted_files)} more file(s) from this message omitted from this context.)")
                lines.append(f"  Omitted file types: {_format_omitted_file_types(omitted_files)}")
                lines.append("  Use `glob(pattern='**/*', path='/mnt/user-data/uploads/')` to list all uploads.")
                lines.append("  Use `grep(pattern='keyword', path='/mnt/user-data/uploads/')` to search across uploads.")
                lines.append("")
        else:
            lines.append("(empty)")
            lines.append("")

        lines.append("To work with these files:")
        lines.append("- Read from the file first — use the outline line numbers and `read_file` to locate relevant sections.")
        lines.append("- Use `grep` to search for keywords when you are not sure which section to look at")
        lines.append("  (e.g. `grep(pattern='revenue', path='/mnt/user-data/uploads/')`).")
        lines.append("- Use `glob` to find files by name pattern")
        lines.append("  (e.g. `glob(pattern='**/*.md', path='/mnt/user-data/uploads/')`).")
        lines.append("- Only fall back to web search if the file content is clearly insufficient to answer the question.")
        lines.append("</current_uploads>")

        return "\n".join(lines)

    @staticmethod
    def _coerce_file_size(value: object) -> int:
        """Best-effort byte count from a client-supplied ``files[*].size``.

        The value only feeds the human-readable size in ``<current_uploads>``,
        and every other field in ``_files_from_kwargs`` is validated fail-soft,
        so an unusable size must never abort the run: anything that is not a
        non-negative finite number (``"abc"``, a list, a bool, ``-5``, ``inf``)
        falls back to ``0``, the same value a missing size gets. Values that
        parse as integers but overflow the floating-point KB display also use
        that fallback. Numeric strings such as ``"2048"`` keep working.
        """
        if value is None or isinstance(value, bool):
            return 0
        try:
            size = int(value)
            if size < 0 or not math.isfinite(size / 1024):
                return 0
        except (TypeError, ValueError, OverflowError):
            # Both int(value) and the subsequent KB division can overflow.
            return 0
        return size

    def _files_from_kwargs(self, message: HumanMessage, uploads_dir: Path | None = None) -> list[dict] | None:
        """Extract file info from message additional_kwargs.files.

        The frontend sends uploaded file metadata in additional_kwargs.files
        after a successful upload. Each entry has: filename, size (bytes),
        path (virtual path), status.

        Args:
            message: The human message to inspect.
            uploads_dir: Physical uploads directory used to verify file existence.
                         When provided, entries whose files no longer exist are skipped.

        Returns:
            List of file dicts with virtual paths, or None if the field is absent or empty.
        """
        kwargs_files = (message.additional_kwargs or {}).get("files")
        if not isinstance(kwargs_files, list) or not kwargs_files:
            return None

        files = []
        for f in kwargs_files:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename")
            if not isinstance(filename, str) or not filename or "\x00" in filename:
                continue
            try:
                file_path = Path(filename)
                if file_path.name != filename or is_upload_staging_file(filename):
                    continue
                if uploads_dir is not None and not (uploads_dir / filename).is_file():
                    continue
            except (OSError, ValueError) as error:
                # Invalid references and unavailable entries are per-file
                # failures; they must not suppress valid sibling uploads.
                logger.debug("Skipping uploaded file %r after %s during its filesystem probe: %s", filename, type(error).__name__, error)
                continue
            files.append(
                {
                    "filename": filename,
                    "size": self._coerce_file_size(f.get("size")),
                    "path": f"/mnt/user-data/uploads/{filename}",
                    "extension": file_path.suffix,
                }
            )
        return files if files else None

    @override
    def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject current-run uploads before agent execution.

        Only files from the current message's additional_kwargs.files are listed.
        Historical uploads are discovered on demand via ``list_uploaded_files``.

        Stores <current_uploads> separately from the user's content.
        """
        messages = list(state.get("messages", []))
        if not messages:
            return {"uploaded_files": []}

        last_message_index = len(messages) - 1
        last_message = messages[last_message_index]

        if not isinstance(last_message, HumanMessage):
            return {"uploaded_files": []}

        # Resolve uploads directory for existence checks
        thread_id = (runtime.context or {}).get("thread_id")
        if thread_id is None:
            try:
                from langgraph.config import get_config

                thread_id = get_config().get("configurable", {}).get("thread_id")
            except RuntimeError:
                pass
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id, user_id=resolve_runtime_user_id(runtime)) if thread_id else None

        # Get newly uploaded files from the current message's additional_kwargs.files
        new_files = self._files_from_kwargs(last_message, uploads_dir) or []
        if not new_files:
            if (last_message.additional_kwargs or {}).get("files"):
                logger.info(
                    "UploadsMiddleware: files metadata was present but no files were found on disk (thread_id=%s, uploads_dir=%s)",
                    thread_id,
                    uploads_dir,
                )
            # Clear stale uploaded_files so list_uploaded_files doesn't
            # exclude files that became historical after the previous turn.
            if UPLOAD_CONTEXT_KEY in last_message.additional_kwargs:
                kwargs = dict(last_message.additional_kwargs)
                kwargs.pop(UPLOAD_CONTEXT_KEY)
                messages[last_message_index] = last_message.model_copy(update={"additional_kwargs": kwargs})
                return {"uploaded_files": [], "messages": messages}
            return {"uploaded_files": []}

        context_files, omitted_files = self._select_files_for_context(new_files)

        # Attach outlines to context files
        if uploads_dir:
            for file in context_files:
                phys_path = uploads_dir / file["filename"]
                outline, preview = extract_outline_for_file(phys_path)
                file["outline"] = outline
                file["outline_preview"] = preview

        logger.debug(f"Current uploads: {[f['filename'] for f in new_files]}")

        # Capture validated descriptions separately, except on the legacy
        # compatibility path that cannot establish pristine user content.
        files_message = self._create_files_message(
            context_files,
            omitted_files=omitted_files if omitted_files else None,
        )

        original_content = last_message.content
        additional_kwargs = dict(last_message.additional_kwargs or {})
        original_user_content = additional_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
        if not isinstance(original_user_content, str) and upload_context_text(last_message) is None and _has_ambiguous_inline_upload_context(original_content):
            # Old inline turns without provenance cannot truthfully declare
            # their whole content to be pristine user prose. Keep legacy
            # display containment and do not manufacture original provenance.
            additional_kwargs.pop(ORIGINAL_USER_CONTENT_KEY, None)
            additional_kwargs.pop(UPLOAD_CONTEXT_KEY, None)
            prefix = f"{files_message}\n\n"
            if isinstance(original_content, str):
                content = original_content if original_content.startswith(prefix) else prefix + original_content
            else:
                block = {"type": "text", "text": prefix}
                content = original_content if original_content and original_content[0] == block else [block, *original_content]
            messages[last_message_index] = last_message.model_copy(update={"content": content, "additional_kwargs": additional_kwargs})
            return {"uploaded_files": new_files, "messages": messages}
        if isinstance(original_user_content, str) and UPLOAD_CONTEXT_KEY not in additional_kwargs:
            # Upgrade a legacy inline/transport-decorated turn only when an
            # explicit original is available. Never regex-strip user content.
            original_content = restore_original_human_message(last_message).content
        if not isinstance(original_user_content, str):
            if ORIGINAL_USER_CONTENT_KEY in additional_kwargs:
                logger.warning(
                    "UploadsMiddleware replaced non-string %s metadata: type=%s",
                    ORIGINAL_USER_CONTENT_KEY,
                    type(original_user_content).__name__,
                )
            additional_kwargs[ORIGINAL_USER_CONTENT_KEY] = message_content_to_text(original_content)
        additional_kwargs[UPLOAD_CONTEXT_KEY] = {"version": UPLOAD_CONTEXT_VERSION, "text": files_message}

        updated_message = last_message.model_copy(
            update={"content": original_content, "additional_kwargs": additional_kwargs},
        )

        messages[last_message_index] = updated_message

        return {
            "uploaded_files": new_files,
            "messages": messages,
        }

    @override
    async def abefore_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Async hook that offloads the synchronous uploads scan off the event loop.

        ``before_agent`` performs blocking filesystem IO (directory enumeration,
        ``stat``, reading sibling ``.md`` outlines). When the graph runs async,
        langgraph would otherwise execute the sync hook directly on the event
        loop, so it is dispatched to a worker thread via ``run_in_executor``.
        ``run_in_executor`` copies the current context, preserving both
        LangGraph's runnable config and DeerFlow's request ContextVar fallback.
        The runtime itself is also passed explicitly for the authoritative
        ``runtime.context["user_id"]`` channel.
        """
        return await run_in_executor(None, self.before_agent, state, runtime)
