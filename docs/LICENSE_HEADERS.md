# License Header Management

This document explains how to manage license headers in the DeerFlow project.

## License Header Format

All source files in this project should include license headers.

### Python Files

```python
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
```

For files with a shebang (`#!/usr/bin/env python3`), the header is placed after the shebang:

```python
#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import something
```

### TypeScript Files

```typescript
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { something } from "somewhere";
```

## Makefile Targets

### Check License Headers

Check if all Python and TypeScript files have the required license header:

```bash
# Check all files (Python and TypeScript)
make check-license-all

# Check only Python files
make check-license

# Check only TypeScript files
make check-license-ts
```

These commands:
- Scan all source files in `src/`, `tests/`, `web/src/`, `web/tests/`, and root-level files
- Report files missing the license header
- Return exit code 1 if any files are missing headers (useful for CI/CD)
- Return exit code 0 if all files have headers

### Add License Headers

Automatically add license headers to files that don't have them:

```bash
# Add to all files (Python and TypeScript)
make add-license-all

# Add only to Python files
make add-license

# Add only to TypeScript files
make add-license-ts
```

These commands:
- Add the appropriate license header to files that don't have it
- Preserve shebangs at the top of Python files
- Add appropriate spacing after headers
- Show vTypeScript files
uv run python scripts/license_header.py web/src/components/ --check

# Check a single file (works for both .py and .ts/.tsx)
uv run python scripts/license_header.py src/workflow.py --check
uv run python scripts/license_header.py web/src/core/api/chat.ts --check
```

### Script Options

- `--check`: Check mode - verify headers without modifying files
- `--verbose` / `-v`: Show detailed output for each file processed
- `paths`: One or more paths (files or directories) to process

### Supported File Types

The script automatically detects and processes:
- Python files (`.py`)
- TypeScript files (`.ts`)
- TypeScript React files (`.tsx`)
uv run python scripts/license_header.py src/agents/ --check

# Add headers to specific files
uv run python scripts/license_header.py src/new_module/ --verbose

# Check a single file
uv run python scripts/license_header.py src/workflow.py --check
```

### Script Options
-all`)** - checks both Python and TypeScript

If any files are missing license headers, the commit will be blocked. Run `make add-license-all
- `paths`: One or more paths (files or directories) to process

## Pre-commit Hook

The license header check is integrated into the pre-commit hook. Before allowing a commit, it will:

1. Run linting (`make lint`)
2. Run formatting -all
```

This ensures all merged code has proper license headers for both Python and TypeScript fileill be blocked. Run `make add-license` to fix.

## CI/CD Integration

For continuous integration, add the license check to your workflow:

```bash
# In your CI script or GitHub Actions
ma`.next` (Next.js build directory)
- ke check-license
```

This ensures all merged code has proper license headers.

## Files Excluded

The license header tool automatically skips:
- `__pycache__` directories
- `.pytest_cache`, `.ruff_cache`, `.mypy_cache`
- `node_modules`
- Virtual environment directories (`.venv`, `venv`, `.tox`)
- Build artifacts (`build`, `dist`)
- `.git` directory

## Customization

### Changing the License Header
S` dictionary in `scripts/license_header.py`:

```python
LICENSE_HEADERS: Dict[str, str] = {
    "python": """# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
""",
    "typescript": """// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT
""",
}
```

### Adding Mo-all:
    @uv run python scripts/license_header.py src/ tests/ scripts/ web/src/ web/test
1. Add the extension to `FILE_TYPE_MAP` in `scripts/license_header.py`
2. Add the corresponding header format to `LICENSE_HEADERS`

```python
FILE_TYPE_MAP = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",  # Example: adding JavaScript support
}

LICENSE_HEADERS = {
    # ... existing headers ...
    "javascript": """// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT
""",
}PDX-License-Identifier: MIT
"""
```
-all
Checking license headers in all source files...
✅ All 289 source file(s) have license headers.
```

### Example 2: Check Only TypeScript Files
```bash
$ make check-license-ts
Checking license headers in TypeScript files...
❌ 3 file(s) missing license header:
  - web/src/components/new-component.tsx
  - web/src/core/api/new-api.ts
  - web/tests/new-test.test.ts

Run 'make add-license-ts' to add headers.
```

### Example 3: Add Headers to New Module
```bash
$ make add-license-all
Adding license headers to all source files...
✅ Added license header to 11 file(s).
```

### Example 4: Check Specific Directory
```bash
$ uv run python scripts/license_header.py web/src/components/ --check --verbose
Header already present: web/src/components/deer-flow/logo.tsx
Header already present: web/src/components/deer-flow/markdown.tsx
Header already present: web/src/components/editor/index.tsx
✅ All 24 sourceooks for exact matches (ignoring leading/trailing whitespace)

### "Pre-commit hook blocks my commit"
- Run `make add-license` to add headers to all files
- Or disable the check temporarily by editing the `pre-commit` file

## Examples

### Example 1: Check All Files
```bash
$ make check-license
Checking license headers in Python files...
✅ All 156 Python file(s) have license headers.
```

### Example 2: Add Headers to New Module
```bash
$ make add-license
Adding license headers to Python files...
✅ Added license header to 11 file(s).
```

### Example 3: Check Specific Directory
```bash
$ uv run python scripts/license_header.py src/agents/ --check --verbose
Header already present: src/agents/base.py
Header already present: src/agents/coordinator.py
✅ All 8 Python file(s) have license headers.
```
