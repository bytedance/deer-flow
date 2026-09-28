### Message Text Extraction

`message_content_to_text` takes raw message content and treats `None` as empty
text so downstream empty-result, error-detail, and archive-skip fallbacks work.
Keep its other conversions unchanged, including newline-separated list blocks
and literal strings such as `"None"`. Do not replace it with `message_to_text`,
which takes a whole message and uses different list/mapping semantics.
Regression coverage lives in `tests/test_utils_messages.py`,
`tests/test_subagent_executor.py`, and `tests/test_task_continuity.py`.

### Agent / Tool Assembly Off-Load

Tool and agent assembly re-enters `get_available_tools()` and may block on MCP discovery, so the four async assembly entry points — `run_agent`'s `agent_factory` call, `task_tool`, durable batch `_execute_item`, and `abuild_checkpoint_state_accessor` — dispatch through `deerflow.utils.assembly_io.run_assembly`, a dedicated ContextVar-preserving bounded executor (`DEER_FLOW_ASSEMBLY_WORKERS`, default 8) rather than the loop's default executor; a hung MCP server therefore parks an assembly worker instead of queueing unrelated default-executor work, and the pool logs a warning when pending assemblies exceed the worker count. `tests/blocking_io/test_tool_assembly_offloop.py` pins all four offloads plus the ContextVar propagation.

### Uploaded Document Summaries

`file_outline.py` reads outlines and fallback previews as `utf-8-sig` so an
optional leading UTF-8 BOM cannot hide a first-line heading or code fence, or
occupy a preview line. Preserve physical line numbers, embedded U+FEFF
characters, and the original file bytes.

### Active Content MIME Types

`text_detection.py::_is_active_content_mime_type` is the shared download-safety
boundary for artifacts and project documents. Keep platform aliases such as
Windows' `image/svg` aligned with their standard active type (`image/svg+xml`),
and preserve the generic `+xml` rule.

### Conversion Worker Ownership

`convert_file_to_markdown` drains large-file conversion workers across caller
cancellation before returning control to source-file cleanup. Keep conversion
inside `await_drained`, including when the worker fails or cancellation repeats;
upload ingestion owns a temporary source that it removes in `finally`. Coverage
lives in `tests/test_file_conversion_cancellation.py`.
