"""Middleware to inject uploaded files information into agent context."""

import logging
import re
from collections import Counter
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.runnables import run_in_executor
from langgraph.runtime import Runtime

from deerflow.config.paths import Paths, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import is_upload_staging_file
from deerflow.utils.file_conversion import extract_outline
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, get_original_user_content_text, message_content_to_text

logger = logging.getLogger(__name__)


_OUTLINE_PREVIEW_LINES = 5
_MAX_FILES_PER_CONTEXT_SECTION = 10
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _extension_label(file: dict) -> str:
    extension = str(file.get("extension") or Path(str(file.get("filename") or "")).suffix).lower()
    return extension or "(no extension)"


def _format_omitted_file_types(files: list[dict]) -> str:
    counts = Counter(_extension_label(file) for file in files)
    parts = [f"{count} {extension}" for extension, count in sorted(counts.items())]
    return ", ".join(parts)


def _query_match_strength(file: dict, query_text: str) -> int:
    query = query_text.lower()
    if not query:
        return 0

    filename = str(file.get("filename") or "").lower()
    stem = Path(filename).stem
    extension_label = _extension_label(file)
    extension = extension_label[1:] if extension_label.startswith(".") else ""

    if filename and filename in query:
        return 3
    if len(stem) >= 3 and stem in query:
        return 3

    token_match = False
    for token in _QUERY_TOKEN_RE.findall(stem):
        if len(token) >= 3 and token in query:
            token_match = True
            break
    if token_match:
        return 2

    if extension and re.search(rf"\b{re.escape(extension)}s?\b", query):
        return 1
    return 0


def _extract_outline_for_file(file_path: Path) -> tuple[list[dict], list[str]]:
    """Return the document outline and fallback preview for *file_path*.

    Looks for a sibling ``<stem>.md`` file produced by the upload conversion
    pipeline.

    Returns:
        (outline, preview) where:
        - outline: list of ``{title, line}`` dicts (plus optional sentinel).
          Empty when no headings are found or no .md exists.
        - preview: first few non-empty lines of the .md, used as a content
          anchor when outline is empty so the agent has some context.
          Empty when outline is non-empty (no fallback needed).
    """
    md_path = file_path.with_suffix(".md")
    if not md_path.is_file():
        return [], []

    outline = extract_outline(md_path)
    if outline:
        logger.debug("Extracted %d outline entries from %s", len(outline), file_path.name)
        return outline, []

    # outline is empty — read the first few non-empty lines as a content preview
    preview: list[str] = []
    try:
        with md_path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    preview.append(stripped)
                if len(preview) >= _OUTLINE_PREVIEW_LINES:
                    break
    except Exception:
        logger.debug("Failed to read preview lines from %s", md_path, exc_info=True)
    return [], preview


class UploadsMiddlewareState(AgentState):
    """State schema for uploads middleware."""

    uploaded_files: NotRequired[list[dict] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """Middleware to inject uploaded files information into the agent context.

    Reads file metadata from the current message's additional_kwargs.files
    (set by the frontend after upload) and prepends an <uploaded_files> block
    to the last human message so the model knows which files are available.
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
        """Append a single file entry (name, size, path, optional outline) to lines."""
        size_kb = file["size"] / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        lines.append(f"- {file['filename']} ({size_str})")
        lines.append(f"  Path: {file['path']}")
        if file.get("selection_reason") == "query_match":
            lines.append("  Selected because: matched the current query.")
        outline = file.get("outline") or []
        if outline:
            truncated = outline[-1].get("truncated", False)
            visible = [e for e in outline if not e.get("truncated")]
            lines.append("  Document outline (use `read_file` with line ranges to read sections):")
            for entry in visible:
                lines.append(f"    L{entry['line']}: {entry['title']}")
            if truncated:
                lines.append(f"    ... (showing first {len(visible)} headings; use `read_file` to explore further)")
        else:
            preview = file.get("outline_preview") or []
            if preview:
                lines.append("  No structural headings detected. Document begins with:")
                for text in preview:
                    lines.append(f"    > {text}")
            lines.append("  Use `grep` to search for keywords (e.g. `grep(pattern='keyword', path='/mnt/user-data/uploads/')`).")
        lines.append("")

    def _select_files_for_context(
        self,
        files: list[dict],
        query_text: str,
        *,
        recency_key: str | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Return bounded context files, prioritizing current-query matches."""
        ranked: list[tuple[tuple, dict]] = []
        for index, file in enumerate(files):
            selected_file = dict(file)
            match_strength = _query_match_strength(selected_file, query_text)
            query_match = match_strength > 0
            if query_match:
                selected_file["selection_reason"] = "query_match"

            if recency_key:
                sort_key = (-match_strength, -float(selected_file.get(recency_key) or 0), selected_file["filename"])
            else:
                sort_key = (-match_strength, index)
            ranked.append((sort_key, selected_file))

        ranked.sort(key=lambda item: item[0])
        selected = [file for _, file in ranked[: self._max_files_per_context_section]]
        omitted = [file for _, file in ranked[self._max_files_per_context_section :]]
        return selected, omitted

    def _create_files_message(
        self,
        new_files: list[dict],
        historical_files: list[dict],
        *,
        omitted_new_files: list[dict] | None = None,
        omitted_historical_files: list[dict] | None = None,
    ) -> str:
        """Create a formatted message listing uploaded files.

        Args:
            new_files: Files uploaded in the current message.
            historical_files: Files uploaded in previous messages.
                Each file dict may contain an optional ``outline`` key — a list of
                ``{title, line}`` dicts extracted from the converted Markdown file.
            omitted_new_files: Current-message files omitted from the prompt context.
            omitted_historical_files: Older historical files omitted from the prompt context.

        Returns:
            Formatted string inside <uploaded_files> tags.
        """
        lines = ["<uploaded_files>"]

        lines.append("The following files were uploaded in this message:")
        lines.append("")
        if new_files:
            for file in new_files:
                self._format_file_entry(file, lines)
            if omitted_new_files:
                lines.append(f"... ({len(omitted_new_files)} more file(s) from this message omitted from this context.)")
                lines.append(f"  Omitted file types: {_format_omitted_file_types(omitted_new_files)}")
                lines.append("  Use `glob(pattern='**/*', path='/mnt/user-data/uploads/')` to list all uploads.")
                lines.append("  Use `grep(pattern='keyword', path='/mnt/user-data/uploads/')` to search across uploads.")
                lines.append("")
        else:
            lines.append("(empty)")
            lines.append("")

        if historical_files:
            lines.append("The following files were uploaded in previous messages and are still available:")
            lines.append("")
            for file in historical_files:
                self._format_file_entry(file, lines)
            if omitted_historical_files:
                lines.append(f"... ({len(omitted_historical_files)} more historical file(s) omitted from this context.)")
                lines.append(f"  Omitted file types: {_format_omitted_file_types(omitted_historical_files)}")
                lines.append("  Use `glob(pattern='**/*', path='/mnt/user-data/uploads/')` to list all uploads.")
                lines.append("  Use `grep(pattern='keyword', path='/mnt/user-data/uploads/')` to search across uploads.")
                lines.append("")

        lines.append("To work with these files:")
        lines.append("- Read from the file first — use the outline line numbers and `read_file` to locate relevant sections.")
        lines.append("- Use `grep` to search for keywords when you are not sure which section to look at")
        lines.append("  (e.g. `grep(pattern='revenue', path='/mnt/user-data/uploads/')`).")
        lines.append("- Use `glob` to find files by name pattern")
        lines.append("  (e.g. `glob(pattern='**/*.md', path='/mnt/user-data/uploads/')`).")
        lines.append("- Only fall back to web search if the file content is clearly insufficient to answer the question.")
        lines.append("</uploaded_files>")

        return "\n".join(lines)

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
            filename = f.get("filename") or ""
            if not filename or Path(filename).name != filename or is_upload_staging_file(filename):
                continue
            if uploads_dir is not None and not (uploads_dir / filename).is_file():
                continue
            files.append(
                {
                    "filename": filename,
                    "size": int(f.get("size") or 0),
                    "path": f"/mnt/user-data/uploads/{filename}",
                    "extension": Path(filename).suffix,
                }
            )
        return files if files else None

    @override
    def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject uploaded files information before agent execution.

        New files come from the current message's additional_kwargs.files.
        Historical files are scanned from the thread's uploads directory,
        excluding the new ones.

        Prepends <uploaded_files> context to the last human message content.
        The original additional_kwargs (including files metadata) is preserved
        on the updated message so the frontend can read it from the stream.

        Args:
            state: Current agent state.
            runtime: Runtime context containing thread_id.

        Returns:
            State updates including uploaded files list.
        """
        messages = list(state.get("messages", []))
        if not messages:
            return None

        last_message_index = len(messages) - 1
        last_message = messages[last_message_index]

        if not isinstance(last_message, HumanMessage):
            return None

        # Resolve uploads directory for existence checks
        thread_id = (runtime.context or {}).get("thread_id")
        if thread_id is None:
            try:
                from langgraph.config import get_config

                thread_id = get_config().get("configurable", {}).get("thread_id")
            except RuntimeError:
                pass  # get_config() raises outside a runnable context (e.g. unit tests)
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id, user_id=get_effective_user_id()) if thread_id else None

        query_text = get_original_user_content_text(last_message.content, last_message.additional_kwargs)

        # Get newly uploaded files from the current message's additional_kwargs.files
        new_files = self._files_from_kwargs(last_message, uploads_dir) or []
        context_new_files, omitted_new_files = self._select_files_for_context(new_files, query_text)

        # Collect historical files from the uploads directory (all except the new ones)
        new_filenames = {f["filename"] for f in new_files}
        historical_candidates: list[dict] = []
        if uploads_dir and uploads_dir.exists():
            for file_path in sorted(uploads_dir.iterdir()):
                if is_upload_staging_file(file_path.name):
                    continue
                if file_path.is_file() and file_path.name not in new_filenames:
                    stat = file_path.stat()
                    historical_candidates.append(
                        {
                            "filename": file_path.name,
                            "size": stat.st_size,
                            "path": f"/mnt/user-data/uploads/{file_path.name}",
                            "extension": file_path.suffix,
                            "_mtime": stat.st_mtime,
                            "_host_path": file_path,
                        }
                    )

        historical_files, omitted_historical_files = self._select_files_for_context(
            historical_candidates,
            query_text,
            recency_key="_mtime",
        )
        for file in historical_files:
            file_path = file.pop("_host_path")
            file.pop("_mtime", None)
            outline, preview = _extract_outline_for_file(file_path)
            file["outline"] = outline
            file["outline_preview"] = preview

        # Attach outlines to new files as well
        if uploads_dir:
            new_files_by_name = {file["filename"]: file for file in new_files}
            for file in context_new_files:
                phys_path = uploads_dir / file["filename"]
                outline, preview = _extract_outline_for_file(phys_path)
                file["outline"] = outline
                file["outline_preview"] = preview
                if original_file := new_files_by_name.get(file["filename"]):
                    original_file["outline"] = outline
                    original_file["outline_preview"] = preview

        if not context_new_files and not historical_files:
            return None

        logger.debug(f"New files: {[f['filename'] for f in new_files]}, historical: {[f['filename'] for f in historical_files]}")

        # Create files message and prepend to the last human message content
        files_message = self._create_files_message(
            context_new_files,
            historical_files,
            omitted_new_files=omitted_new_files,
            omitted_historical_files=omitted_historical_files,
        )

        # Extract original content - handle both string and list formats
        original_content = last_message.content
        additional_kwargs = dict(last_message.additional_kwargs or {})
        original_user_content = additional_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
        if not isinstance(original_user_content, str):
            if ORIGINAL_USER_CONTENT_KEY in additional_kwargs:
                logger.warning(
                    "UploadsMiddleware replaced non-string %s metadata: type=%s",
                    ORIGINAL_USER_CONTENT_KEY,
                    type(original_user_content).__name__,
                )
            additional_kwargs[ORIGINAL_USER_CONTENT_KEY] = message_content_to_text(original_content)
        if isinstance(original_content, str):
            # Simple case: string content, just prepend files message
            updated_content = f"{files_message}\n\n{original_content}"
        elif isinstance(original_content, list):
            # Complex case: list content (multimodal), preserve all blocks
            # Prepend files message as the first text block
            files_block = {"type": "text", "text": f"{files_message}\n\n"}
            # Keep all original blocks (including images)
            updated_content = [files_block, *original_content]
        else:
            # Other types, preserve as-is
            updated_content = original_content

        # Create new message with combined content.
        # Preserve additional_kwargs (including files metadata) so the frontend
        # can read structured file info from the streamed message.
        updated_message = HumanMessage(
            content=updated_content,
            id=last_message.id,
            name=last_message.name,
            additional_kwargs=additional_kwargs,
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
        ``run_in_executor`` copies the current context, so the ``user_id``
        contextvar read by ``get_effective_user_id()`` is preserved.
        """
        return await run_in_executor(None, self.before_agent, state, runtime)
