"""Sectioned long-form writing plugin. No imports from DeerFlow host internals."""

import asyncio

from deerflow_extension_api import ModelTool, PluginContribution, PluginToolResult, extension

from .sections import (
    ASSEMBLE_INDEX,
    ASSEMBLE_TITLE,
    MAX_CONTENT_CHARS,
    MAX_DOCUMENT_BYTES,
    MAX_TITLE_CHARS,
    SectionStore,
)

TOOL_DESCRIPTION = (
    "Persist one section of a long report, then assemble all sections into the final document. "
    "Call with section_index=0 first to store the outline, then 1..N in order for chapters "
    "(keep each section within roughly 1200-2000 characters), and finally section_index=999 "
    "with title '__assemble__' to assemble every stored section into one markdown report, "
    "returned as a downloadable artifact with a short status summary. "
    "Sections are scoped to the current user and thread."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "section_index": {
            "type": "integer",
            "minimum": 0,
            "maximum": ASSEMBLE_INDEX,
            "description": "0 = outline, 1..N = chapters in order, 999 = assemble.",
        },
        "title": {
            "type": "string",
            "maxLength": MAX_TITLE_CHARS,
            "description": "Section title; use '__assemble__' with index 999.",
        },
        "content": {
            "type": "string",
            "maxLength": MAX_CONTENT_CHARS,
            "description": "Full markdown content of this section; ignored when assembling.",
        },
    },
    "required": ["section_index", "title", "content"],
    "additionalProperties": False,
}


def _error(message: str) -> PluginToolResult:
    return PluginToolResult(content=f"ERROR: {message}", artifact=None)


@extension(api="0.2.8", name="report-sections")
def install(registry, config):
    enabled = config.get("enabled", False)
    if type(enabled) is not bool or not isinstance(config.get("storage_path"), str):
        raise ValueError("Configure boolean enabled and an absolute storage_path at deployment")
    store = SectionStore(config["storage_path"])

    async def save_section(payload, context):
        section_index = payload["section_index"]
        title = payload["title"].strip()
        owner = context.principal.user_id
        thread_id = context.thread_id
        if not owner or not thread_id:
            return _error("no user or thread context; cannot save section")

        if section_index == ASSEMBLE_INDEX or title == ASSEMBLE_TITLE:
            assembled = await asyncio.to_thread(store.assemble, owner, thread_id)
            if assembled is None:
                return _error("no sections saved yet; nothing to assemble")
            filename, document, count, total_chars = assembled
            if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
                return _error(f"assembled report is {len(document.encode('utf-8'))} bytes, over the {MAX_DOCUMENT_BYTES}-byte tool-result cap; sections remain stored — assemble fewer sections per thread")
            # content is model-visible and stays short; the artifact carries the
            # full document to the UI without re-entering the model context.
            return PluginToolResult(
                content=(f"OK assembled {count} sections, {total_chars} chars into {filename}. Give the user a brief completion summary now (section list and total length)."),
                artifact={
                    "filename": filename,
                    "sections": count,
                    "chars": total_chars,
                    "document": document,
                },
            )

        content = payload["content"]
        if not content.strip():
            return _error("content is empty")
        await asyncio.to_thread(store.save, owner, thread_id, int(section_index), title, content)
        return PluginToolResult(
            content=f"OK section {section_index} '{title}' saved ({len(content)} chars). Continue with the next section.",
            artifact=None,
        )

    contribution = PluginContribution(
        namespace="community.report-sections",
        title="分段长文写作 / Sectioned long-form writing",
        description=(
            "把万字级长报告分节保存，最后拼装成完整交付文档；拼装时自动去掉与节标题重复的正文标题。"
            " / Store a long report section by section and assemble the final document,"
            " dropping content headings that duplicate the assembled section titles."
        ),
        enabled=enabled,
        tools=(
            ModelTool(
                "save_section",
                TOOL_DESCRIPTION,
                INPUT_SCHEMA,
                save_section,
                response_format="content_and_artifact",
            ),
        ),
    )
    if registry.plugin(contribution) is not True:
        raise RuntimeError("This example requires the full-stack plugin host contract")


__all__ = ["install"]
