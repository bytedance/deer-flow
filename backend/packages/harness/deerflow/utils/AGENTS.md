### Goal Objective Validation

`goal_objective.py` owns the dependency-free normalized 4000-character objective
validation shared by runtime and scheduled-task capability/repository admission.
`runtime.goal` re-exports the helper for compatibility. Validation does not replace
the saved original text; blank or over-limit text is rejected before persistence.

### Message Text Extraction

`message_content_to_text` takes raw message content and treats `None` as empty
text so downstream empty-result, error-detail, and archive-skip fallbacks work.
Keep its other conversions unchanged, including newline-separated list blocks
and literal strings such as `"None"`. Do not replace it with `message_to_text`,
which takes a whole message and uses different list/mapping semantics.
Regression coverage lives in `tests/test_utils_messages.py`,
`tests/test_subagent_executor.py`, and `tests/test_task_continuity.py`.

`llm_text.py::strip_think_blocks` scans opening and closing tags forward so
repeated unclosed `<think>` prefixes in model output do not rescan the same
suffix. Keep its case-insensitive tag handling, optional whitespace before
the closing `>`, and the `truncate_unclosed` behavior. Regression coverage
lives in `tests/test_utils_llm_text.py`.

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

### Host Path Portability

`host_paths.py` rejects Windows device names for host-visible creation paths on
every platform, including the `COM`/`LPT` aliases with superscript ¹, ² and ³.
Do not normalize arbitrary Unicode digits into device numbers: names such as
`COM⁴.txt` and `COM¹notes.txt` are ordinary portable names. Read/removal callers
retain their existing portability exemptions.
