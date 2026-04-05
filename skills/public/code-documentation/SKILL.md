---
name: code-documentation
description: Use this skill when the user requests to generate, create, or improve documentation for code, APIs, libraries, repositories, or software projects. Supports README generation, API reference documentation, inline code comments, architecture documentation, changelog generation, and developer guides. Trigger on requests like "document this code", "create a README", "generate API docs", "write developer guide", or when analyzing codebases for documentation purposes.
---

# Code Documentation Skill

## Overview

This skill generates professional, comprehensive documentation for software projects, codebases, libraries, and APIs. It follows industry best practices from projects like React, Django, Stripe, and Kubernetes to produce documentation that is accurate, well-structured, and useful for both new contributors and experienced developers.

The output ranges from single-file READMEs to multi-document developer guides, always matched to the project's complexity and the user's needs.

## Core Capabilities

- Generate comprehensive README.md files with badges, installation, usage, and API reference
- Create API reference documentation from source code analysis
- Produce architecture and design documentation with diagrams
- Write developer onboarding and contribution guides
- Generate changelogs from commit history or release notes
- Create inline code documentation following language-specific conventions
- Support JSDoc, docstrings, GoDoc, Javadoc, and Rustdoc formats
- Adapt documentation style to the project's language and ecosystem

## When to Use This Skill

**Always load this skill when:**

- User asks to "document", "create docs", or "write documentation" for any code
- User requests a README, API reference, or developer guide
- User shares a codebase or repository and wants documentation generated
- User asks to improve or update existing documentation
- User needs architecture documentation, including diagrams
- User requests a changelog or migration guide

## Documentation Workflow

### Phase 1: Codebase Analysis

Before writing any documentation, thoroughly understand the codebase.

#### Step 1.1: Project Discovery

Identify the project fundamentals:

| Field | How to Determine |
|-------|-----------------|
| **Language(s)** | Check file extensions, `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, etc. |
| **Framework** | Look at dependencies for known frameworks (React, Django, Express, Spring, etc.) |
| **Build System** | Check for `Makefile`, `CMakeLists.txt`, `webpack.config.js`, `build.gradle`, etc. |
| **Package Manager** | npm/yarn/pnpm, pip/uv/poetry, cargo, go modules, etc. |
| **Project Structure** | Map out the directory tree to understand the architecture |
| **Entry Points** | Find main files, CLI entry points, exported modules |
| **Existing Docs** | Check for existing README, docs/, wiki, or inline documentation |

#### Step 1.2: Code Structure Analysis

Use sandbox tools to explore the codebase:

```bash
# Get directory structure
ls /mnt/user-data/uploads/project-dir/

# Read key files
read_file /mnt/user-data/uploads/project-dir/package.json
read_file /mnt/user-data/uploads/project-dir/pyproject.toml

# Search for public API surfaces
grep -r "export " /mnt/user-data/uploads/project-dir/src/
grep -r "def " /mnt/user-data/uploads/project-dir/src/ --include="*.py"
grep -r "func " /mnt/user-data/uploads/project-dir/ --include="*.go"
```

#### Step 1.3: Identify Documentation Scope

Based on analysis, determine what documentation to produce:

| Project Size | Recommended Documentation |
|-------------|--------------------------|
| **Single file / script** | Inline comments + usage header |
| **Small library** | README with API reference |
| **Medium project** | README + API docs + examples |
| **Large project** | README + Architecture + API + Contributing + Changelog |

### Phase 2: Documentation Generation

#### Step 2.1: README Generation

Every project needs a README. Follow this structure:

```markdown
# Project Name

[One-line project description — what it does and why it matters]

[![Badge](link)](#) [![Badge](link)](#)

## Features

- [Key feature 1 — brief description]
- [Key feature 2 — brief description]
- [Key feature 3 — brief description]

## Quick Start

### Prerequisites

- [Prerequisite 1 with version requirement]
- [Prerequisite 2 with version requirement]

### Installation

[Installation commands with copy-paste-ready code blocks]

### Basic Usage

[Minimal working example that demonstrates core functionality]

## Documentation

- [Link to full API reference if separate]
- [Link to architecture docs if separate]
- [Link to examples directory if applicable]

## API Reference

[Inline API reference for smaller projects OR link to generated docs]

## Configuration

[Environment variables, config files, or runtime options]

## Examples

[2-3 practical examples covering common use cases]

## Development

### Setup

[How to set up a development environment]

### Testing

[How to run tests]

### Building

[How to build the project]

## Contributing

[Contribution guidelines or link to CONTRIBUTING.md]

## License

[License information]
```

#### Step 2.2: API Reference Generation

For each public API surface, document:

**Function / Method Documentation**:

```markdown
### `functionName(param1, param2, options?)`

Brief description of what this function does.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `param1` | `string` | Yes | — | Description of param1 |
| `param2` | `number` | Yes | — | Description of param2 |
| `options` | `Object` | No | `{}` | Configuration options |
| `options.timeout` | `number` | No | `5000` | Timeout in milliseconds |

**Returns:** `Promise<Result>` — Description of return value

**Throws:**
- `ValidationError` — When param1 is empty
- `TimeoutError` — When the operation exceeds the timeout

**Example:**

\`\`\`javascript
const result = await functionName("hello", 42, { timeout: 10000 });
console.log(result.data);
\`\`\`
```

**Class Documentation**:

```markdown
### `ClassName`

Brief description of the class and its purpose.

**Constructor:**

\`\`\`javascript
new ClassName(config)
\`\`\`

| Parameter | Type | Description |
|-----------|------|-------------|
| `config.option1` | `string` | Description |
| `config.option2` | `boolean` | Description |

**Methods:**

- [`method1()`](#method1) — Brief description
- [`method2(param)`](#method2) — Brief description

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `property1` | `string` | Description |
| `property2` | `number` | Read-only. Description |
```

#### Step 2.3: Architecture Documentation

For medium-to-large projects, include architecture documentation:

```markdown
# Architecture Overview

## System Diagram

[Include a Mermaid diagram showing the high-level architecture]

\`\`\`mermaid
graph TD
    A[Client] --> B[API Gateway]
    B --> C[Service A]
    B --> D[Service B]
    C --> E[(Database)]
    D --> E
\`\`\`

## Component Overview

### Component Name
- **Purpose**: What this component does
- **Location**: `src/components/name/`
- **Dependencies**: What it depends on
- **Public API**: Key exports or interfaces

## Data Flow

[Describe how data flows through the system for key operations]

## Design Decisions

### Decision Title
- **Context**: What situation led to this decision
- **Decision**: What was decided
- **Rationale**: Why this approach was chosen
- **Trade-offs**: What was sacrificed
```

#### Step 2.4: Inline Code Documentation

Generate language-appropriate inline documentation:

**Python (Docstrings — Google style)**:
```python
def process_data(input_path: str, options: dict | None = None) -> ProcessResult:
    """Process data from the given file path.

    Reads the input file, applies transformations based on the provided
    options, and returns a structured result object.

    Args:
        input_path: Absolute path to the input data file.
            Supports CSV, JSON, and Parquet formats.
        options: Optional configuration dictionary.
            - "validate" (bool): Enable input validation. Defaults to True.
            - "format" (str): Output format ("json" or "csv"). Defaults to "json".

    Returns:
        A ProcessResult containing the transformed data and metadata.

    Raises:
        FileNotFoundError: If input_path does not exist.
        ValidationError: If validation is enabled and data is malformed.

    Example:
        >>> result = process_data("/data/input.csv", {"validate": True})
        >>> print(result.row_count)
        1500
    """
```

**TypeScript (JSDoc / TSDoc)**:
```typescript
/**
 * Fetches user data from the API and transforms it for display.
 *
 * @param userId - The unique identifier of the user
 * @param options - Configuration options for the fetch operation
 * @param options.includeProfile - Whether to include the full profile. Defaults to `false`.
 * @param options.cache - Cache duration in seconds. Set to `0` to disable.
 * @returns The transformed user data ready for rendering
 * @throws {NotFoundError} When the user ID does not exist
 * @throws {NetworkError} When the API is unreachable
 *
 * @example
 * ```ts
 * const user = await fetchUser("usr_123", { includeProfile: true });
 * console.log(user.displayName);
 * ```
 */
```

**Go (GoDoc)**:
```go
// ProcessData reads the input file at the given path, applies the specified
// transformations, and returns the processed result.
//
// The input path must be an absolute path to a CSV or JSON file.
// If options is nil, default options are used.
//
// ProcessData returns an error if the file does not exist or cannot be parsed.
func ProcessData(inputPath string, options *ProcessOptions) (*Result, error) {
```

### Phase 3: Quality Assurance

#### Step 3.1: Documentation Completeness Check

Verify the documentation covers:

- [ ] **What it is** — Clear project description that a newcomer can understand
- [ ] **Why it exists** — Problem it solves and value proposition
- [ ] **How to install** — Copy-paste-ready installation commands
- [ ] **How to use** — At least one minimal working example
- [ ] **API surface** — All public functions, classes, and types documented
- [ ] **Configuration** — All environment variables, config files, and options
- [ ] **Error handling** — Common errors and how to resolve them
- [ ] **Contributing** — How to set up dev environment and submit changes

#### Step 3.2: Quality Standards

| Standard | Check |
|----------|-------|
| **Accuracy** | Every code example must actually work with the described API |
| **Completeness** | No public API surface left undocumented |
| **Consistency** | Same formatting and structure throughout |
| **Freshness** | Documentation matches the current code, not an older version |
| **Accessibility** | No jargon without explanation, acronyms defined on first use |
| **Examples** | Every complex concept has at least one practical example |

#### Step 3.3: Cross-reference Validation

Ensure:
- All mentioned file paths exist in the project
- All referenced functions and classes exist in the code
- All code examples use the correct function signatures
- Version numbers match the project's actual version
- All links (internal and external) are valid

## Documentation Style Guide

### Writing Principles

1. **Lead with the "why"** — Before explaining how something works, explain why it exists
2. **Progressive disclosure** — Start simple, add complexity gradually
3. **Show, don't tell** — Prefer code examples over lengthy explanations
4. **Active voice** — "The function returns X" not "X is returned by the function"
5. **Present tense** — "The server starts on port 8080" not "The server will start on port 8080"
6. **Second person** — "You can configure..." not "Users can configure..."

### Formatting Rules

- Use ATX-style headers (`#`, `##`, `###`)
- Use fenced code blocks with language specification (` ```python `, ` ```bash `)
- Use tables for structured information (parameters, options, configuration)
- Use admonitions for important notes, warnings, and tips
- Keep line length readable (wrap prose at ~80-100 characters in source)
- Use `code formatting` for function names, file paths, variable names, and CLI commands

### Language-Specific Conventions

| Language | Doc Format | Style Guide |
|----------|-----------|-------------|
| Python | Google-style docstrings | PEP 257 |
| TypeScript/JavaScript | TSDoc / JSDoc | TypeDoc conventions |
| Go | GoDoc comments | Effective Go |
| Rust | Rustdoc (`///`) | Rust API Guidelines |
| Java | Javadoc | Oracle Javadoc Guide |
| C/C++ | Doxygen | Doxygen manual |

## Output Handling

After generation:

- Save documentation files to `/mnt/user-data/outputs/`
- For multi-file documentation, maintain the project directory structure
- Present generated files to the user using the `present_files` tool
- Offer to iterate on specific sections or adjust the level of detail
- Suggest additional documentation that might be valuable

## Notes

- Always analyze the actual code before writing documentation — never guess at API signatures or behavior
- When existing documentation exists, preserve its structure unless the user explicitly asks for a rewrite
- For large codebases, prioritize documenting the public API surface and key abstractions first
- Documentation should be written in the same language as the project's existing docs; default to English if none exist
- When generating changelogs, use the [Keep a Changelog](https://keepachangelog.com/) format
- This skill works well in combination with the `deep-research` skill for documenting third-party integrations or dependencies
