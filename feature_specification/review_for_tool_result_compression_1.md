# Files you've changed in preview steps
  claude_code_env.sh
  feature_specification/11.md
  feature_specification/tool_result_compression.md
  src/compression/__init__.py
  src/compression/artifact_storage.py
  src/compression/compression_service.py
  src/compression/models.py
  src/config/configuration.py
  src/graph/nodes.py
  src/prompts/compression.md
  src/prompts/compression.zh_CN.md
  src/tools/__init__.py
  src/tools/artifact_retrieval.py
  tests/unit/compression/__init__.py
  tests/unit/compression/test_compression.py

# Suggested Improvements

## 1. Maintain Consistent Code Style

**Goal:** All new code should follow the style of the existing project.

**Steps:**

1. Analyze the existing code base for style conventions.

   * Focus on:

     * Data structures (prefer `dict` over custom classes)
     * Naming conventions
     * Indentation and formatting
     * Function signatures and docstrings
2. Output findings in a **file**:

```
/docs/code_style_analyze.md
```

3. Revise **all new code** to align with the established style.
4. Ensure consistency in:

   * Function naming
   * Variable naming
   * Module structure

---

## 2. Place Compression Module in `util` Directory

**Goal:** Organize utilities for maintainability and discoverability.

**Steps:**

1. Create a module under:

```
/util/compress.py
```

2. Review existing files in `util/` for patterns:

   * Function naming
   * Parameter passing
   * Logging
   * Error handling
3. Implement compression functionality following the established conventions.

---

## 3. Make Raw Tool Result Path Configurable

**Goal:** Avoid hard-coded file paths and support flexibility.

**Steps:**

1. Introduce a configuration mechanism (YAML, JSON, or Python `dict`) for specifying the raw tool storage directory.

Example configuration:

```python
CONFIG = {
    "raw_tool_output_path": "/research_artifacts/"
}
```

2. Refactor all file-writing code to use the configured path:

```python
filepath = os.path.join(CONFIG["raw_tool_output_path"], filename)
```

3. Ensure default path exists and is created if missing.
4. Document the configuration option in the README or a config doc.

---

## 4. Revise Compression Prompt and Code

**Goal:** Follow the new contextual information design.

**Steps:**

1. Remove plan metadata (`plan_title`, `step_title`, `step_description`) from the system prompt.
2. Pass contextual information via a **structured user message** instead.
3. Update compression code to accept:

   * `plan_title`
   * `step_title`
   * `step_description`
   * `tool_name`
   * `raw_tool_output`
4. Generate structured output JSON:

```json
{
  "summary_title": "string",
  "summary": "string",
  "extraction": ["bullet 1", "bullet 2"],
  "is_useful": true
}
```

5. Ensure the assistant message injected into the conversation contains **only**:

```json
{
  "summary_title": "string",
  "summary": "string",
  "extraction": ["..."],
  "artifact_file": "filename.ext"
}
```

6. Update prompt template for the compression LLM accordingly.

---

## 5. Implementation Notes

* **Testing:** Add unit tests for:

  * Compression logic
  * File path configuration
  * JSON output format
* **Logging:** Log compression actions and file writes for traceability.
* **Backward Compatibility:** Ensure old code consuming tool results continues to work with new configuration setup.
* **Documentation:** Update docs to reflect:

  * Configurable paths
  * Compression usage
  * Message format conventions
