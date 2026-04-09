"""Middleware to inject uploaded files information into agent context."""

import asyncio
import base64
import json
import logging
import mimetypes
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import UploadedImageDescriptionDocument
from deerflow.config.app_config import get_app_config
from deerflow.config.paths import Paths, get_paths
from deerflow.uploads.manager import enrich_file_listing, list_files_in_dir
from deerflow.utils.file_conversion import extract_outline

logger = logging.getLogger(__name__)


_OUTLINE_PREVIEW_LINES = 5
_VIEW_IMAGE_GUIDANCE = (
    "  This .docx includes extracted images. Before answering questions that depend on screenshots, diagrams, "
    "flowcharts, or other visual details, use `view_image` on those image paths instead of relying on markdown alone."
)
_DESCRIPTION_TAG = "document_image_descriptions"
_DESCRIPTION_BLOCK_RE = re.compile(
    rf"<{_DESCRIPTION_TAG}>\s*(.*?)\s*</{_DESCRIPTION_TAG}>",
    re.DOTALL,
)
_FAILED_DESCRIPTION_TEXT = (
    "Image descriptions unavailable. This document's extracted images were not successfully described during the "
    "automatic vision pass. Use `view_image` on the extracted image paths if visual details matter."
)


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
    uploaded_image_descriptions: NotRequired[dict[str, UploadedImageDescriptionDocument] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """Middleware to inject uploaded files information into the agent context.

    Reads file metadata from the current message's additional_kwargs.files
    (set by the frontend after upload) and prepends an <uploaded_files> block
    to the last human message so the model knows which files are available.
    """

    state_schema = UploadsMiddlewareState

    def __init__(self, base_dir: str | None = None):
        """Initialize the middleware.

        Args:
            base_dir: Base directory for thread data. Defaults to Paths resolution.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()

    def _format_file_entry(self, file: dict, lines: list[str]) -> None:
        """Append a single file entry (name, size, path, optional outline) to lines."""
        size_kb = int(file["size"]) / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        lines.append(f"- {file['filename']} ({size_str})")
        lines.append(f"  Path: {file['path']}")

        if file.get("markdown_file") and file.get("markdown_path"):
            lines.append(f"  Converted Markdown: {file['markdown_file']}")
            lines.append(f"    Path: {file['markdown_path']}")

        image_status = file.get("image_description_status")
        if image_status == "parsed" and file.get("image_descriptions"):
            lines.append("  Persisted image descriptions:")
            for index, image in enumerate(file["image_descriptions"], start=1):
                lines.append(f"    {index}. {image['description']}")
        else:
            if image_status == "failed":
                lines.append(f"  {_FAILED_DESCRIPTION_TEXT}")

            extracted_images = file.get("extracted_images") or []
            if extracted_images:
                lines.append("  Extracted images for vision analysis:")
                for image in extracted_images:
                    lines.append(f"    Image: {image['filename']}")
                    lines.append(f"      Path: {image['path']}")
                lines.append(_VIEW_IMAGE_GUIDANCE)

        outline = file.get("outline") or []
        if outline:
            truncated = outline[-1].get("truncated", False)
            visible = [entry for entry in outline if not entry.get("truncated")]
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

    def _create_files_message(self, new_files: list[dict], historical_files: list[dict]) -> str:
        """Create a formatted message listing uploaded files.

        Args:
            new_files: Files uploaded in the current message.
            historical_files: Files uploaded in previous messages.
                Each file dict may contain an optional ``outline`` key — a list of
                ``{title, line}`` dicts extracted from the converted Markdown file.

        Returns:
            Formatted string inside <uploaded_files> tags.
        """
        lines = ["<uploaded_files>"]

        lines.append("The following files were uploaded in this message:")
        lines.append("")
        if new_files:
            for file in new_files:
                self._format_file_entry(file, lines)
        else:
            lines.append("(empty)")
            lines.append("")

        if historical_files:
            lines.append("The following files were uploaded in previous messages and are still available:")
            lines.append("")
            for file in historical_files:
                self._format_file_entry(file, lines)

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
        path (virtual path), status, plus optional markdown/image metadata.

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
            if not filename or Path(filename).name != filename:
                continue
            if uploads_dir is not None and not (uploads_dir / filename).is_file():
                continue

            file_info = {
                "filename": filename,
                "size": int(f.get("size") or 0),
                "path": f"/mnt/user-data/uploads/{filename}",
                "extension": Path(filename).suffix,
            }

            markdown_filename = f.get("markdown_file") or ""
            if markdown_filename and Path(markdown_filename).name == markdown_filename:
                if uploads_dir is None or (uploads_dir / markdown_filename).is_file():
                    file_info["markdown_file"] = markdown_filename
                    file_info["markdown_path"] = f"/mnt/user-data/uploads/{markdown_filename}"

            extracted_images = []
            for image in f.get("extracted_images") or []:
                if not isinstance(image, dict):
                    continue
                image_filename = image.get("filename") or ""
                if not image_filename or Path(image_filename).name != image_filename:
                    continue
                if uploads_dir is not None and not (uploads_dir / image_filename).is_file():
                    continue
                extracted_images.append(
                    {
                        "filename": image_filename,
                        "size": int(image.get("size") or 0),
                        "path": f"/mnt/user-data/uploads/{image_filename}",
                        "extension": Path(image_filename).suffix,
                        "virtual_path": f"/mnt/user-data/uploads/{image_filename}",
                        "artifact_url": image.get("artifact_url"),
                    }
                )
            if extracted_images:
                file_info["extracted_images"] = extracted_images

            files.append(file_info)
        return files if files else None

    def _collect_related_new_filenames(self, new_files: list[dict]) -> set[str]:
        """Collect filenames that should be excluded from historical listings."""
        related_filenames: set[str] = set()
        for file in new_files:
            related_filenames.add(file["filename"])
            markdown_filename = file.get("markdown_file")
            if markdown_filename:
                related_filenames.add(markdown_filename)
            for image in file.get("extracted_images", []):
                related_filenames.add(image["filename"])
        return related_filenames

    def _load_historical_files(self, uploads_dir: Path, thread_id: str, excluded_filenames: set[str]) -> list[dict]:
        """Load historical files using the shared grouping rules."""
        result = list_files_in_dir(uploads_dir)
        enrich_file_listing(result, thread_id)

        historical_files: list[dict] = []
        for file in result["files"]:
            if file["filename"] in excluded_filenames:
                continue

            historical_file = {
                "filename": file["filename"],
                "size": int(file["size"]),
                "path": file.get("virtual_path", f"/mnt/user-data/uploads/{file['filename']}"),
                "extension": file.get("extension", Path(file["filename"]).suffix),
            }

            md_path = uploads_dir / Path(file["filename"]).with_suffix(".md").name
            if md_path.is_file():
                historical_file["markdown_file"] = md_path.name
                historical_file["markdown_path"] = f"/mnt/user-data/uploads/{md_path.name}"

            outline, preview = _extract_outline_for_file(uploads_dir / file["filename"])
            historical_file["outline"] = outline
            historical_file["outline_preview"] = preview

            extracted_images = []
            for image in file.get("extracted_images", []):
                if image["filename"] in excluded_filenames:
                    continue
                extracted_images.append(
                    {
                        "filename": image["filename"],
                        "size": int(image["size"]),
                        "path": image.get("virtual_path", f"/mnt/user-data/uploads/{image['filename']}"),
                        "extension": image.get("extension", Path(image["filename"]).suffix),
                        "virtual_path": image.get("virtual_path", f"/mnt/user-data/uploads/{image['filename']}"),
                        "artifact_url": image.get("artifact_url"),
                    }
                )
            if extracted_images:
                historical_file["extracted_images"] = extracted_images

            historical_files.append(historical_file)
        return historical_files

    def _attach_image_descriptions(
        self,
        files: list[dict],
        uploaded_image_descriptions: dict[str, UploadedImageDescriptionDocument] | None,
    ) -> list[dict]:
        """Attach persisted image descriptions onto matching document entries."""
        descriptions = uploaded_image_descriptions or {}
        for file in files:
            doc_description = descriptions.get(file["filename"])
            if not doc_description:
                continue
            file["image_description_status"] = doc_description.get("status", "parsed")
            images = doc_description.get("images")
            if isinstance(images, list) and images:
                file["image_descriptions"] = images
        return files

    def _clear_reuploaded_doc_descriptions(
        self,
        uploaded_image_descriptions: dict[str, UploadedImageDescriptionDocument] | None,
        new_files: list[dict],
    ) -> tuple[dict[str, UploadedImageDescriptionDocument], bool]:
        """Drop persisted descriptions for newly uploaded docx files."""
        cleaned = dict(uploaded_image_descriptions or {})
        changed = False
        for file in new_files:
            if Path(file["filename"]).suffix.lower() != ".docx":
                continue
            if file["filename"] in cleaned:
                cleaned.pop(file["filename"], None)
                changed = True
        return cleaned, changed

    def _runtime_supports_vision(self, runtime: Runtime) -> bool:
        """Return whether the active runtime model supports image inputs."""
        app_config = get_app_config()
        runtime_context = runtime.context or {}
        model_name = runtime_context.get("model_name")
        if model_name is None and app_config.models:
            model_name = app_config.models[0].name
        model_config = app_config.get_model_config(model_name) if model_name else None
        return bool(model_config and model_config.supports_vision)

    def _get_pending_docx_files(self, state: UploadsMiddlewareState) -> list[dict]:
        """Return newly uploaded docx files that do not yet have persisted results."""
        uploaded_image_descriptions = state.get("uploaded_image_descriptions") or {}
        pending_files = []
        for file in state.get("uploaded_files") or []:
            if Path(file["filename"]).suffix.lower() != ".docx":
                continue
            if not file.get("extracted_images"):
                continue
            if uploaded_image_descriptions.get(file["filename"]):
                continue
            pending_files.append(file)
        return pending_files

    def _get_visual_context_documents(self, state: UploadsMiddlewareState, runtime: Runtime) -> list[dict]:
        """Return docx files whose extracted images can be injected for vision analysis."""
        thread_id = (runtime.context or {}).get("thread_id")
        if not thread_id:
            return []

        uploads_dir = self._paths.sandbox_uploads_dir(thread_id)
        if not uploads_dir.exists():
            return []

        visual_documents: list[dict] = []
        for file in self._get_pending_docx_files(state):
            validated_images = []
            for image in file.get("extracted_images") or []:
                image_filename = image.get("filename")
                if not image_filename:
                    continue

                actual_path = uploads_dir / image_filename
                if not actual_path.is_file():
                    continue

                mime_type, _ = mimetypes.guess_type(actual_path.name)
                if not mime_type or not mime_type.startswith("image/"):
                    continue

                validated_images.append(
                    {
                        **image,
                        "mime_type": mime_type,
                        "actual_path": actual_path,
                    }
                )
            if validated_images:
                visual_documents.append({**file, "validated_images": validated_images})
        return visual_documents

    def _create_uploaded_visual_context_message(self, state: UploadsMiddlewareState, runtime: Runtime) -> HumanMessage | None:
        """Build a multimodal message for extracted document images."""
        visual_documents = self._get_visual_context_documents(state, runtime)
        if not visual_documents:
            return None

        return self._build_uploaded_visual_context_message(visual_documents)

    async def _acreate_uploaded_visual_context_message(
        self,
        state: UploadsMiddlewareState,
        runtime: Runtime,
    ) -> HumanMessage | None:
        """Build the multimodal visual-context message off the event loop."""
        visual_documents = self._get_visual_context_documents(state, runtime)
        if not visual_documents:
            return None

        return await asyncio.to_thread(self._build_uploaded_visual_context_message, visual_documents)

    def _build_uploaded_visual_context_message(self, visual_documents: list[dict]) -> HumanMessage:
        """Create the multimodal message payload for already-validated images."""

        content_blocks: list[dict] = []
        text_sections = [
            "<document_visual_context>",
            "The following images were extracted from uploaded documents in this turn.",
            "Use direct vision analysis on them.",
            "Summarize the relevant visual information and treat that summary as part of the corresponding document context before answering.",
            "You must include a machine-parseable JSON payload inside the tags below.",
            f"<{_DESCRIPTION_TAG}>",
            '{"documents":[{"document":"<docx filename>","markdown_path":"<optional markdown path>","images":[{"filename":"<image filename>","description":"<short factual description>"}]}]}',
            f"</{_DESCRIPTION_TAG}>",
            "Keep your normal user-facing answer outside those tags.",
            "",
        ]

        for file in visual_documents:
            file_lines = [f"Document: {file['filename']}"]
            markdown_path = file.get("markdown_path")
            if markdown_path:
                file_lines.append(f"Converted markdown: {markdown_path}")

            for image in file["validated_images"]:
                image_base64 = base64.b64encode(image["actual_path"].read_bytes()).decode("utf-8")
                default_image_path = f"/mnt/user-data/uploads/{image['filename']}"
                file_lines.append(f"Image path: {image.get('path', default_image_path)}")
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{image['mime_type']};base64,{image_base64}"},
                    }
                )
            text_sections.extend(file_lines)
            text_sections.append("")

        text_sections.append("</document_visual_context>")
        content_blocks.insert(0, {"type": "text", "text": "\n".join(text_sections)})
        return HumanMessage(content=content_blocks, name="uploaded_document_visual_context")

    def _normalize_content(self, content: object) -> str:
        """Flatten structured model content into plain text for payload parsing."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [self._normalize_content(item) for item in content]
            return "\n".join(part for part in parts if part)
        if isinstance(content, dict):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
            nested_content = content.get("content")
            if nested_content is not None:
                return self._normalize_content(nested_content)
        return ""

    def _strip_description_payload(self, content: object) -> object:
        """Remove the machine payload from visible assistant content."""
        if isinstance(content, str):
            return _DESCRIPTION_BLOCK_RE.sub("", content).strip()
        if isinstance(content, list):
            stripped_blocks: list[object] = []
            for block in content:
                cleaned_block = self._strip_description_payload(block)
                if cleaned_block in ("", None, []):
                    continue
                stripped_blocks.append(cleaned_block)
            return stripped_blocks
        if isinstance(content, dict):
            updated = dict(content)
            text = updated.get("text")
            if isinstance(text, str):
                cleaned_text = _DESCRIPTION_BLOCK_RE.sub("", text).strip()
                if not cleaned_text:
                    return None
                updated["text"] = cleaned_text

            nested_content = updated.get("content")
            if nested_content is not None:
                cleaned_nested = self._strip_description_payload(nested_content)
                if cleaned_nested in ("", None, []):
                    updated.pop("content", None)
                else:
                    updated["content"] = cleaned_nested
            return updated
        return content

    def _build_parsed_uploaded_image_descriptions(
        self,
        parsed_documents: dict[str, UploadedImageDescriptionDocument],
        uploaded_files: list[dict] | None,
    ) -> dict[str, UploadedImageDescriptionDocument]:
        """Attach known extracted-image paths onto parsed descriptions."""
        file_lookup = {file["filename"]: file for file in uploaded_files or []}
        enriched: dict[str, UploadedImageDescriptionDocument] = {}
        for document_name, document in parsed_documents.items():
            file_info = file_lookup.get(document_name) or {}
            image_lookup = {
                image["filename"]: image
                for image in file_info.get("extracted_images", [])
                if isinstance(image, dict) and image.get("filename")
            }

            enriched_images = []
            for image in document["images"]:
                image_info = image_lookup.get(image["filename"], {})
                enriched_image = dict(image)
                if image_info.get("path"):
                    enriched_image["path"] = image_info["path"]
                enriched_images.append(enriched_image)

            enriched[document_name] = {
                "status": "parsed",
                "document": document["document"],
                "markdown_path": document.get("markdown_path"),
                "images": enriched_images,
            }
        return enriched

    def _build_failed_uploaded_image_descriptions(self, state: UploadsMiddlewareState) -> dict[str, UploadedImageDescriptionDocument]:
        """Create placeholder results for docx images whose automatic vision pass failed."""
        failed_documents: dict[str, UploadedImageDescriptionDocument] = {}
        for file in self._get_pending_docx_files(state):
            failed_documents[file["filename"]] = {
                "status": "failed",
                "document": file["filename"],
                "markdown_path": file.get("markdown_path"),
                "images": [
                    {
                        "filename": image["filename"],
                        "path": image.get("path"),
                        "description": _FAILED_DESCRIPTION_TEXT,
                    }
                    for image in file.get("extracted_images", [])
                ],
            }
        return failed_documents

    def _parse_uploaded_image_descriptions(self, content: object) -> dict[str, UploadedImageDescriptionDocument] | None:
        """Parse a deterministic document-image-description payload from assistant output."""
        normalized_content = self._normalize_content(content)
        match = _DESCRIPTION_BLOCK_RE.search(normalized_content)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        documents = payload.get("documents")
        if not isinstance(documents, list):
            return None

        parsed: dict[str, UploadedImageDescriptionDocument] = {}
        for document in documents:
            if not isinstance(document, dict):
                return None
            filename = document.get("document")
            if not isinstance(filename, str) or not filename or Path(filename).name != filename:
                return None
            images = document.get("images")
            if not isinstance(images, list) or not images:
                return None
            parsed_images: list[dict] = []
            for image in images:
                if not isinstance(image, dict):
                    return None
                image_filename = image.get("filename")
                description = image.get("description")
                if (
                    not isinstance(image_filename, str)
                    or not image_filename
                    or Path(image_filename).name != image_filename
                    or not isinstance(description, str)
                    or not description.strip()
                ):
                    return None
                parsed_images.append(
                    {
                        "filename": image_filename,
                        "description": description.strip(),
                    }
                )
            parsed[filename] = {
                "status": "parsed",
                "document": filename,
                "markdown_path": document.get("markdown_path"),
                "images": parsed_images,
            }
        return parsed or None

    @override
    def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject uploaded files information before agent execution.

        New files come from the current message's additional_kwargs.files.
        Historical files are scanned from the thread's uploads directory,
        excluding the new upload group and related sidecars.

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
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id) if thread_id else None

        # Get newly uploaded files from the current message's additional_kwargs.files
        new_files = self._files_from_kwargs(last_message, uploads_dir) or []
        uploaded_image_descriptions, descriptions_changed = self._clear_reuploaded_doc_descriptions(
            state.get("uploaded_image_descriptions"),
            new_files,
        )

        # Attach outlines to new files as well
        if uploads_dir:
            for file in new_files:
                phys_path = uploads_dir / file["filename"]
                outline, preview = _extract_outline_for_file(phys_path)
                file["outline"] = outline
                file["outline_preview"] = preview

        self._attach_image_descriptions(new_files, uploaded_image_descriptions)

        # Collect historical files from the uploads directory (all except the
        # current upload group and its related sidecars/markdown companions).
        historical_files: list[dict] = []
        if uploads_dir and uploads_dir.exists() and thread_id:
            historical_files = self._load_historical_files(
                uploads_dir,
                thread_id,
                self._collect_related_new_filenames(new_files),
            )
        self._attach_image_descriptions(historical_files, uploaded_image_descriptions)

        if not new_files and not historical_files:
            return None

        logger.debug("New files: %s, historical: %s", [f["filename"] for f in new_files], [f["filename"] for f in historical_files])

        # Create files message and prepend to the last human message content
        files_message = self._create_files_message(new_files, historical_files)

        # Extract original content - handle both string and list formats
        original_content = ""
        if isinstance(last_message.content, str):
            original_content = last_message.content
        elif isinstance(last_message.content, list):
            text_parts = []
            for block in last_message.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            original_content = "\n".join(text_parts)

        # Create new message with combined content.
        # Preserve additional_kwargs (including files metadata) so the frontend
        # can read structured file info from the streamed message.
        updated_message = HumanMessage(
            content=f"{files_message}\n\n{original_content}",
            id=last_message.id,
            additional_kwargs=last_message.additional_kwargs,
        )

        messages[last_message_index] = updated_message

        result = {
            "uploaded_files": new_files,
            "messages": messages,
        }
        if descriptions_changed:
            result["uploaded_image_descriptions"] = uploaded_image_descriptions
        return result

    @override
    async def abefore_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Async before-agent hook that offloads historical upload scanning."""
        messages = list(state.get("messages", []))
        if not messages:
            return None

        last_message_index = len(messages) - 1
        last_message = messages[last_message_index]
        if not isinstance(last_message, HumanMessage):
            return None

        # Resolve uploads directory for existence checks.
        thread_id = (runtime.context or {}).get("thread_id")
        if thread_id is None:
            try:
                from langgraph.config import get_config

                thread_id = get_config().get("configurable", {}).get("thread_id")
            except RuntimeError:
                pass  # get_config() raises outside a runnable context (e.g. unit tests)
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id) if thread_id else None

        # Get newly uploaded files from the current message's additional_kwargs.files.
        new_files = self._files_from_kwargs(last_message, uploads_dir) or []
        uploaded_image_descriptions, descriptions_changed = self._clear_reuploaded_doc_descriptions(
            state.get("uploaded_image_descriptions"),
            new_files,
        )

        # Attach outlines to new files as well
        if uploads_dir:
            for file in new_files:
                phys_path = uploads_dir / file["filename"]
                outline, preview = _extract_outline_for_file(phys_path)
                file["outline"] = outline
                file["outline_preview"] = preview

        self._attach_image_descriptions(new_files, uploaded_image_descriptions)

        # Collect historical files from the uploads directory in a worker thread
        # so async agent execution does not block on filesystem scans.
        historical_files: list[dict] = []
        if uploads_dir and uploads_dir.exists() and thread_id:
            historical_files = await asyncio.to_thread(
                self._load_historical_files,
                uploads_dir,
                thread_id,
                self._collect_related_new_filenames(new_files),
            )
        self._attach_image_descriptions(historical_files, uploaded_image_descriptions)

        if not new_files and not historical_files:
            return None

        logger.debug("New files: %s, historical: %s", [f["filename"] for f in new_files], [f["filename"] for f in historical_files])

        # Create files message and prepend it to the last human message content.
        files_message = self._create_files_message(new_files, historical_files)

        # Extract original content - handle both string and list formats.
        original_content = ""
        if isinstance(last_message.content, str):
            original_content = last_message.content
        elif isinstance(last_message.content, list):
            text_parts = []
            for block in last_message.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            original_content = "\n".join(text_parts)

        # Create new message with combined content.
        # Preserve additional_kwargs (including files metadata) so the frontend
        # can read structured file info from the streamed message.
        updated_message = HumanMessage(
            content=f"{files_message}\n\n{original_content}",
            id=last_message.id,
            additional_kwargs=last_message.additional_kwargs,
        )

        messages[last_message_index] = updated_message

        result = {
            "uploaded_files": new_files,
            "messages": messages,
        }
        if descriptions_changed:
            result["uploaded_image_descriptions"] = uploaded_image_descriptions
        return result

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """Temporarily append docx images to the current model request only."""
        if self._runtime_supports_vision(request.runtime):
            visual_message = self._create_uploaded_visual_context_message(request.state, request.runtime)
            if visual_message is not None:
                request = request.override(messages=[*request.messages, visual_message])
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """Async version of wrap_model_call."""
        if self._runtime_supports_vision(request.runtime):
            visual_message = await self._acreate_uploaded_visual_context_message(request.state, request.runtime)
            if visual_message is not None:
                request = request.override(messages=[*request.messages, visual_message])
        return await handler(request)

    @override
    def after_model(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Persist deterministic image descriptions emitted by the first multimodal turn."""
        messages = state.get("messages", [])
        if not messages:
            return None
        last_message = messages[-1]
        if not isinstance(last_message, AIMessage):
            return None

        stripped_content = self._strip_description_payload(last_message.content)
        parsed = self._parse_uploaded_image_descriptions(last_message.content)
        updates: dict[str, object] = {}

        if stripped_content != last_message.content:
            updates["messages"] = [last_message.model_copy(update={"content": stripped_content})]

        if parsed:
            merged = dict(state.get("uploaded_image_descriptions") or {})
            merged.update(self._build_parsed_uploaded_image_descriptions(parsed, state.get("uploaded_files")))
            updates["uploaded_image_descriptions"] = merged
        elif self._runtime_supports_vision(runtime) and self._get_visual_context_documents(state, runtime):
            failed = self._build_failed_uploaded_image_descriptions(state)
            if failed:
                merged = dict(state.get("uploaded_image_descriptions") or {})
                merged.update(failed)
                updates["uploaded_image_descriptions"] = merged

        return updates or None

    @override
    async def aafter_model(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Async version of after_model."""
        return self.after_model(state, runtime)
