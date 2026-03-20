# Thinktank.ai Skills System & Plugin Integration Walkthrough

A comprehensive walkthrough of how skills are selected, loaded, and applied in the Thinktank.ai backend, followed by two development plans: (1) integrating Anthropic's Cowork Plugins and (2) implementing MCP code execution for context efficiency.

---

## Table of Contents

1. [Skills System Architecture Overview](#1-skills-system-architecture-overview)
2. [Skill Discovery & Loading Pipeline](#2-skill-discovery--loading-pipeline)
3. [Skill Parsing & Metadata Extraction](#3-skill-parsing--metadata-extraction)
4. [Skill Enablement via Extensions Config](#4-skill-enablement-via-extensions-config)
5. [Skill Injection into Agent System Prompt](#5-skill-injection-into-agent-system-prompt)
6. [Skill Progressive Loading at Runtime](#6-skill-progressive-loading-at-runtime)
7. [Gateway API for Skill Management](#7-gateway-api-for-skill-management)
8. [Skill Installation from Archives](#8-skill-installation-from-archives)
9. [End-to-End Skill Lifecycle Diagram](#9-end-to-end-skill-lifecycle-diagram)
10. [Development Plan 1: Integrating Anthropic's Knowledge-Work Plugins](#10-development-plan-1-integrating-anthropics-knowledge-work-plugins)
11. [Development Plan 2: MCP Code Execution for Context Efficiency](#11-development-plan-2-mcp-code-execution-for-context-efficiency)

---

## 1. Skills System Architecture Overview

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                        Thinktank.ai Skills Architecture                       │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│   think-tank/                                                                 │
│   ├── skills/                          ← On-disk skill storage                │
│   │   ├── public/                      ← Built-in / committed skills          │
│   │   │   ├── pdf-processing/          ← Each skill = directory + SKILL.md    │
│   │   │   │   ├── SKILL.md             ← YAML frontmatter + instructions      │
│   │   │   │   ├── scripts/             ← Optional resources                   │
│   │   │   │   └── references/                                                 │
│   │   │   └── web-scraping/                                                   │
│   │   └── custom/                      ← User-installed / gitignored          │
│   │       └── my-skill/                                                       │
│   │                                                                           │
│   ├── backend/                                                                │
│   │   └── src/                                                                │
│   │       ├── skills/                  ← Skill loading system                 │
│   │       │   ├── __init__.py          ← Exports: load_skills, Skill          │
│   │       │   ├── loader.py            ← Discovery & loading                  │
│   │       │   ├── parser.py            ← YAML frontmatter parsing             │
│   │       │   └── types.py             ← Skill dataclass                      │
│   │       ├── config/                                                         │
│   │       │   ├── skills_config.py     ← Path configuration                   │
│   │       │   └── extensions_config.py ← Enabled/disabled state               │
│   │       ├── agents/lead_agent/                                              │
│   │       │   └── prompt.py            ← Skill → system prompt injection      │
│   │       └── gateway/routers/                                                │
│   │           └── skills.py            ← REST API for skill CRUD              │
│   │                                                                           │
│   └── extensions_config.json           ← Skill enabled states + MCP servers   │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Key Principle: Skills Are Prompt-Level, Not Code-Level

Unlike MCP tools which provide callable functions, skills are **prompt injections** — they appear in the agent's system prompt as references to files. The agent then uses its existing `read_file` tool to load and follow skill instructions at runtime.

```
┌──────────────┐       ┌──────────────┐       ┌──────────────────────┐
│  SKILL.md    │       │  System      │       │  Agent Runtime       │
│  (on disk)   │──────>│  Prompt      │──────>│  reads SKILL.md via  │
│              │       │  (metadata   │       │  read_file tool when │
│              │       │   injected)  │       │  task matches        │
└──────────────┘       └──────────────┘       └──────────────────────┘
```

---

## 2. Skill Discovery & Loading Pipeline

### Main Function: `load_skills()`

**File**: `src/skills/loader.py`
**Signature**: `load_skills(skills_path=None, use_config=True, enabled_only=False) -> list[Skill]`

```
                           load_skills()
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌─────────────────┐  ┌──────────┐  ┌──────────────────┐
    │ Resolve Path    │  │ Scan     │  │ Apply Enabled    │
    │                 │  │ dirs     │  │ State            │
    │ 1. use_config?  │  │          │  │                  │
    │    get_app_     │  │ public/  │  │ ExtensionsConfig │
    │    config()     │  │ custom/  │  │ .from_file()     │
    │ 2. fallback:    │  │          │  │ is_skill_        │
    │    get_skills_  │  │ For each │  │ enabled()        │
    │    root_path()  │  │ subdir:  │  │                  │
    │    (../skills)  │  │ parse    │  │ Filter if        │
    │                 │  │ SKILL.md │  │ enabled_only     │
    └─────────────────┘  └──────────┘  └──────────────────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Sort by name        │
                    │ Return list[Skill]  │
                    └─────────────────────┘
```

### Step-by-Step Walkthrough

**Step 1: Path Resolution**

```python
# loader.py lines 38-49
if skills_path is None:
    if use_config:
        config = get_app_config()
        skills_path = config.skills.get_skills_path()
    else:
        skills_path = get_skills_root_path()
```

The path resolution checks config.yaml first (the `skills.path` field), then falls back to the default `../skills` relative to the backend directory.

**Step 2: Category Scanning**

```python
# loader.py lines 56-73
for category in ["public", "custom"]:
    category_path = skills_path / category
    for skill_dir in category_path.iterdir():
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            skill = parse_skill_file(skill_file, category=category)
            if skill:
                skills.append(skill)
```

Two fixed categories: `public` (committed, built-in) and `custom` (user-installed, gitignored).

**Step 3: Enabled State Application**

```python
# loader.py lines 80-88
extensions_config = ExtensionsConfig.from_file()  # Always fresh read!
for skill in skills:
    skill.enabled = extensions_config.is_skill_enabled(skill.name, skill.category)
```

Critical detail: `ExtensionsConfig.from_file()` is called directly (not the cached singleton) to ensure changes made by the Gateway API process are immediately visible to the LangGraph server process.

### Helper: `get_skills_root_path()`

**Signature**: `get_skills_root_path() -> Path`

Computes the default path: `backend/../skills` → `think-tank/skills/`

```python
# loader.py lines 7-18
backend_dir = Path(__file__).resolve().parent.parent.parent  # src/skills/__init__.py → backend/
skills_dir = backend_dir.parent / "skills"                    # backend/../skills
```

---

## 3. Skill Parsing & Metadata Extraction

### Main Function: `parse_skill_file()`

**File**: `src/skills/parser.py`
**Signature**: `parse_skill_file(skill_file: Path, category: str) -> Skill | None`

```
SKILL.md File Format:
┌──────────────────────────────────────────┐
│ ---                                      │  ← YAML frontmatter start
│ name: pdf-processing                     │  ← Required: hyphen-case name
│ description: Extract and analyze PDFs    │  ← Required: human-readable
│ license: MIT                             │  ← Optional
│ allowed-tools: read_file, bash           │  ← Optional: tool restrictions
│ ---                                      │  ← YAML frontmatter end
│                                          │
│ # PDF Processing Skill                   │  ← Markdown body (instructions)
│                                          │
│ ## How to Use                            │
│ 1. Read the uploaded PDF...              │
│ 2. Extract tables using...               │
│                                          │
│ ## References                            │
│ - See `./scripts/extract.py`             │  ← Relative resource refs
│ - See `./references/format.md`           │
└──────────────────────────────────────────┘
```

### Parsing Logic

```python
# parser.py lines 26-43
# 1. Extract YAML frontmatter via regex
front_matter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)

# 2. Simple key-value parsing (not full YAML parser)
metadata = {}
for line in front_matter.split("\n"):
    if ":" in line:
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

# 3. Extract required fields
name = metadata.get("name")         # Required
description = metadata.get("description")  # Required
license_text = metadata.get("license")     # Optional
```

Note: The parser uses simple `split(":", 1)` rather than a full YAML library. This is lightweight but means multi-line YAML values won't parse correctly.

### Skill Dataclass

**File**: `src/skills/types.py`

```python
@dataclass
class Skill:
    name: str           # "pdf-processing"
    description: str    # "Extract and analyze PDFs"
    license: str | None # "MIT"
    skill_dir: Path     # /path/to/skills/public/pdf-processing
    skill_file: Path    # /path/to/skills/public/pdf-processing/SKILL.md
    category: str       # "public" or "custom"
    enabled: bool       # From extensions_config.json

    def get_container_path(self, container_base_path="/mnt/skills") -> str:
        # → "/mnt/skills/public/pdf-processing"

    def get_container_file_path(self, container_base_path="/mnt/skills") -> str:
        # → "/mnt/skills/public/pdf-processing/SKILL.md"
```

The `get_container_path()` and `get_container_file_path()` methods translate physical paths to virtual container paths that the agent sees in its sandbox.

---

## 4. Skill Enablement via Extensions Config

### Configuration File: `extensions_config.json`

```json
{
  "mcpServers": { ... },
  "skills": {
    "pdf-processing": { "enabled": true },
    "web-scraping": { "enabled": false },
    "custom-skill": { "enabled": true }
  }
}
```

### Enablement Logic

**File**: `src/config/extensions_config.py`

```python
# extensions_config.py lines 152-166
def is_skill_enabled(self, skill_name: str, skill_category: str) -> bool:
    skill_config = self.skills.get(skill_name)
    if skill_config is None:
        # Default: public & custom skills are enabled if not explicitly configured
        return skill_category in ("public", "custom")
    return skill_config.enabled
```

```
                    is_skill_enabled("my-skill", "public")
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
             ┌──────────┐   ┌──────────┐   ┌──────────────┐
             │ Found in │   │ Found in │   │ Not in       │
             │ config:  │   │ config:  │   │ config:      │
             │ enabled  │   │ disabled │   │ default to   │
             │ = true   │   │ = false  │   │ enabled for  │
             │          │   │          │   │ public/custom│
             │ → true   │   │ → false  │   │ → true       │
             └──────────┘   └──────────┘   └──────────────┘
```

### Cross-Process Freshness

The loader deliberately calls `ExtensionsConfig.from_file()` (not the cached `get_extensions_config()`) to handle the two-process architecture:

```
┌──────────────────┐                    ┌──────────────────┐
│  Gateway API     │  writes to         │  LangGraph       │
│  (port 8001)     │ ─────────────────> │  Server          │
│                  │  extensions_       │  (port 2024)     │
│  PUT /api/skills │  config.json       │                  │
│  updates enabled │                    │  load_skills()   │
│  state           │                    │  reads fresh     │
│                  │                    │  from file       │
└──────────────────┘                    └──────────────────┘
```

---

## 5. Skill Injection into Agent System Prompt

### Main Function: `get_skills_prompt_section()`

**File**: `src/agents/lead_agent/prompt.py`
**Signature**: `get_skills_prompt_section() -> str`

```
get_skills_prompt_section()
         │
         ├─1─ load_skills(enabled_only=True)
         │         │
         │         └── Returns: [Skill, Skill, ...]
         │
         ├─2─ get_app_config().skills.container_path
         │         │
         │         └── Returns: "/mnt/skills" (default)
         │
         ├─3─ Format XML skill items
         │         │
         │         └── For each skill: <skill><name>...<location>...</skill>
         │
         └─4─ Wrap in <skill_system> XML block
                   │
                   └── Returns: Full prompt section string
```

### Generated Prompt Structure

```xml
<skill_system>
You have access to skills that provide optimized workflows for specific tasks.
Each skill contains best practices, frameworks, and references to additional
resources.

**Progressive Loading Pattern:**
1. When a user query matches a skill's use case, immediately call `read_file`
   on the skill's main file using the path attribute provided in the skill tag
2. Read and understand the skill's workflow and instructions
3. The skill file contains references to external resources under the same folder
4. Load referenced resources only when needed during execution
5. Follow the skill's instructions precisely

**Skills are located at:** /mnt/skills

<available_skills>
    <skill>
        <name>pdf-processing</name>
        <description>Extract and analyze PDF content</description>
        <location>/mnt/skills/public/pdf-processing/SKILL.md</location>
    </skill>
    <skill>
        <name>web-scraping</name>
        <description>Scrape and extract web content</description>
        <location>/mnt/skills/public/web-scraping/SKILL.md</location>
    </skill>
</available_skills>

</skill_system>
```

### Integration into System Prompt Template

```python
# prompt.py lines 359-401
def apply_prompt_template(subagent_enabled=False, max_concurrent_subagents=3, thinking_enabled=False):
    memory_context = _get_memory_context()
    skills_section = get_skills_prompt_section()   # ← Skills injected here

    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        skills_section=skills_section,             # ← Fills {skills_section}
        memory_context=memory_context,
        subagent_section=subagent_section,
        subagent_reminder=subagent_reminder,
        subagent_thinking=subagent_thinking,
    )
    return prompt + f"\n<current_date>...</current_date>"
```

The `SYSTEM_PROMPT_TEMPLATE` contains `{skills_section}` which is replaced with the generated `<skill_system>` block:

```
SYSTEM_PROMPT_TEMPLATE = """
<role>You are Thinktank.ai 2.0...</role>
{memory_context}
<thinking_style>...</thinking_style>
<clarification_system>...</clarification_system>
{skills_section}                           ← HERE
{subagent_section}
<working_directory>...</working_directory>
<response_style>...</response_style>
<citations>...</citations>
<critical_reminders>
- Skill First: Always load the relevant skill before starting complex tasks.
- Progressive Loading: Load resources incrementally as referenced in skills
...</critical_reminders>
"""
```

---

## 6. Skill Progressive Loading at Runtime

The "Progressive Loading" pattern is central to how skills work. Instead of dumping all skill content into the system prompt (which would be enormous), skills are loaded on-demand:

```
┌────────────────────────────────────────────────────────────────────────┐
│                  PROGRESSIVE LOADING FLOW                              │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  1. SYSTEM PROMPT (at agent creation)                                  │
│     ┌───────────────────────────────────────────────┐                  │
│     │ <available_skills>                            │                  │
│     │   <skill>                                     │                  │
│     │     <name>pdf-processing</name>               │  Only metadata   │
│     │     <description>Extract PDFs</description>   │  is in the       │
│     │     <location>/mnt/skills/.../SKILL.md</loc>  │  system prompt   │
│     │   </skill>                                    │                  │
│     │ </available_skills>                           │                  │
│     └───────────────────────────────────────────────┘                  │
│                          │                                             │
│  2. USER MESSAGE: "Please extract data from this PDF"                  │
│                          │                                             │
│  3. AGENT THINKING:                                                    │
│     "This matches the pdf-processing skill. I should load it."         │
│                          │                                             │
│  4. AGENT ACTION: read_file("/mnt/skills/public/pdf-processing/        │
│                              SKILL.md")                                │
│                          │                                             │
│     ┌──────────────────────────────────────────────┐                   │
│     │ # PDF Processing Skill                       │                   │
│     │ ## Steps                                     │  Full skill       │
│     │ 1. Read the PDF using ...                    │  instructions     │
│     │ 2. For tables, see ./scripts/extract.py      │  loaded into      │
│     │ 3. Output format: ...                        │  context          │
│     └──────────────────────────────────────────────┘                   │
│                          │                                             │
│  5. AGENT ACTION (if needed): read_file("/mnt/skills/.../extract.py")  │
│                          │                                             │
│     ┌──────────────────────────────────────────────┐                   │
│     │ # extract.py                                 │  Referenced       │
│     │ import tabula                                │  resources        │
│     │ def extract_tables(pdf_path): ...            │  loaded only      │
│     │                                              │  when needed      │
│     └──────────────────────────────────────────────┘                   │
│                          │                                             │
│  6. AGENT EXECUTES: Follows skill instructions to complete the task    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Virtual Path Translation

When the agent calls `read_file("/mnt/skills/public/pdf-processing/SKILL.md")`, the sandbox translates this:

```
Agent sees:     /mnt/skills/public/pdf-processing/SKILL.md
                     │
                     ▼  (replace_virtual_path)
Physical path:  think-tank/skills/public/pdf-processing/SKILL.md
```

This is handled by the sandbox's path translation system in `src/sandbox/tools.py` via `replace_virtual_path()` / `replace_virtual_paths_in_command()`.

---

## 7. Gateway API for Skill Management

**File**: `src/gateway/routers/skills.py`
**Router prefix**: `/api`

### Endpoints

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     SKILLS GATEWAY API                                   │
├──────────────┬──────────────┬────────────────────────────────────────────┤
│ Method       │ Endpoint     │ Description                                │
├──────────────┼──────────────┼────────────────────────────────────────────┤
│ GET          │ /api/skills  │ List all skills (public + custom)          │
│              │              │ Returns: SkillsListResponse                │
│              │              │ Calls: load_skills(enabled_only=False)     │
├──────────────┼──────────────┼────────────────────────────────────────────┤
│ GET          │ /api/skills/ │ Get single skill details                   │
│              │ {name}       │ Returns: SkillResponse (404 if not found)  │
├──────────────┼──────────────┼────────────────────────────────────────────┤
│ PUT          │ /api/skills/ │ Enable/disable a skill                     │
│              │ {name}       │ Body: {"enabled": true/false}              │
│              │              │ Updates: extensions_config.json            │
│              │              │ Reloads: global config cache               │
├──────────────┼──────────────┼────────────────────────────────────────────┤
│ POST         │ /api/skills/ │ Install skill from .skill archive          │
│              │ install      │ Body: {"thread_id": "...", "path": "..."}  │
│              │              │ Extracts: ZIP → skills/custom/{name}/      │
│              │              │ Validates: frontmatter, naming, structure  │
└──────────────┴──────────────┴────────────────────────────────────────────┘
```

### PUT /api/skills/{name} — Enable/Disable Flow

```python
# skills.py lines 276-326
async def update_skill(skill_name, request):
    # 1. Verify skill exists
    skills = load_skills(enabled_only=False)
    skill = next((s for s in skills if s.name == skill_name), None)

    # 2. Update in-memory config
    extensions_config.skills[skill_name] = SkillStateConfig(enabled=request.enabled)

    # 3. Serialize to disk (preserves MCP server config)
    config_data = {
        "mcpServers": { ... },
        "skills": { name: {"enabled": ...} for name, ... }
    }
    json.dump(config_data, f, indent=2)

    # 4. Reload global cache
    reload_extensions_config()
```

### POST /api/skills/install — Installation Flow

```
.skill file (ZIP)
      │
      ▼
┌─────────────────┐
│ 1. Resolve path │ resolve_thread_virtual_path(thread_id, path)
│    from virtual │
│    to physical  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. Validate     │ Is file? Is .skill extension? Is valid ZIP?
│    archive      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. Extract to   │ tempfile.TemporaryDirectory()
│    temp dir     │ zipfile.ZipFile.extractall()
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. Validate     │ _validate_skill_frontmatter()
│    SKILL.md     │ - Has frontmatter?
│    frontmatter  │ - Required: name, description
│                 │ - Name: hyphen-case, ≤64 chars
│                 │ - No unexpected keys
│                 │ - No angle brackets in description
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. Check name   │ 409 Conflict if skills/custom/{name}/ exists
│    collision    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 6. Copy to      │ shutil.copytree(temp_dir, skills/custom/{name}/)
│    custom dir   │
└─────────────────┘
```

### Allowed Frontmatter Properties

```python
ALLOWED_FRONTMATTER_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata"}
```

---

## 8. Skill Installation from Archives

The `.skill` file format is a ZIP archive:

```
my-skill.skill (ZIP)
└── my-skill/          ← Optional wrapper directory
    ├── SKILL.md       ← Required: frontmatter + instructions
    ├── scripts/       ← Optional: helper scripts
    ├── references/    ← Optional: reference materials
    └── assets/        ← Optional: images, data files
```

Key validations during install:

1. File must have `.skill` extension
2. Must be a valid ZIP archive
3. Must contain `SKILL.md` with valid YAML frontmatter
4. Name must be hyphen-case (`^[a-z0-9-]+$`), no leading/trailing hyphens, ≤64 chars
5. Description must not contain `<` or `>`, ≤1024 chars
6. Only allowed frontmatter keys: `name`, `description`, `license`, `allowed-tools`, `metadata`
7. Skill name must not already exist in `skills/custom/`

---

## 9. End-to-End Skill Lifecycle Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       COMPLETE SKILL LIFECYCLE                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐     ┌────────────────┐     ┌─────────────────────────┐         │
│  │ AUTHORING   │     │ INSTALLATION   │     │ CONFIGURATION           │         │
│  │             │     │                │     │                         │         │
│  │ Write       │────>│ Place in       │────>│ extensions_config.json  │         │
│  │ SKILL.md    │     │ skills/public/ │     │ {"skills":{"name":      │         │
│  │ with YAML   │     │ or skills/     │     │   {"enabled": true}}}   │         │
│  │ frontmatter │     │ custom/        │     │                         │         │
│  │             │     │                │     │ OR via Gateway API:     │         │
│  │ OR: create  │     │ OR: POST /api/ │     │ PUT /api/skills/{name}  │         │
│  │ .skill ZIP  │     │ skills/install │     │                         │         │
│  └─────────────┘     └────────────────┘     └───────────┬─────────────┘         │
│                                                         │                       │
│  ═══════════════════════════════════════════════════════╤════════════════════   │
│                                                         │                       │
│  ┌──────────────────────────────────────────────────────┘                       │
│  │                                                                              │
│  ▼  AGENT CREATION (per request)                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │ make_lead_agent(config)                                             │        │
│  │   └── apply_prompt_template()                                       │        │
│  │         └── get_skills_prompt_section()                             │        │
│  │               ├── load_skills(enabled_only=True)                    │        │
│  │               │     ├── Scan skills/public/ and skills/custom/      │        │
│  │               │     ├── Parse each SKILL.md frontmatter             │        │
│  │               │     ├── ExtensionsConfig.from_file() ← fresh!       │        │
│  │               │     └── Filter: only enabled skills                 │        │
│  │               └── Format <skill_system>...<available_skills>        │        │
│  │                     with <name>, <description>, <location>          │        │
│  └─────────────────────────────────────────────────────────────────────┘        │
│                              │                                                  │
│                              ▼                                                  │
│  RUNTIME (during conversation)                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │ User: "Extract data from this PDF"                                  │        │
│  │                                                                     │        │
│  │ Agent (thinking): "This matches pdf-processing skill"               │        │
│  │                                                                     │        │
│  │ Agent: read_file("/mnt/skills/public/pdf-processing/SKILL.md")      │        │
│  │   └── Sandbox translates → think-tank/skills/public/.../SKILL.md    │        │
│  │                                                                     │        │
│  │ Agent: [reads instructions, follows workflow]                       │        │
│  │ Agent: read_file("/mnt/skills/.../scripts/extract.py")  ← if ref'd  │        │
│  │ Agent: [executes according to skill instructions]                   │        │
│  │ Agent: [completes task, presents output]                            │        │
│  └─────────────────────────────────────────────────────────────────────┘        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Class & Function Summary Table

| Component | Location | Inputs | Outputs |
|-----------|----------|--------|---------|
| `Skill` dataclass | `src/skills/types.py` | name, description, license, paths, category, enabled | Container paths via methods |
| `parse_skill_file()` | `src/skills/parser.py` | `skill_file: Path`, `category: str` | `Skill \| None` |
| `get_skills_root_path()` | `src/skills/loader.py` | (none) | `Path` to `think-tank/skills/` |
| `load_skills()` | `src/skills/loader.py` | `skills_path`, `use_config`, `enabled_only` | `list[Skill]` sorted by name |
| `SkillsConfig` | `src/config/skills_config.py` | `path`, `container_path` | Resolved paths via methods |
| `ExtensionsConfig.is_skill_enabled()` | `src/config/extensions_config.py` | `skill_name`, `skill_category` | `bool` |
| `get_skills_prompt_section()` | `src/agents/lead_agent/prompt.py` | (none) | `str` — `<skill_system>` XML block |
| `apply_prompt_template()` | `src/agents/lead_agent/prompt.py` | `subagent_enabled`, etc. | Full system prompt `str` |
| Gateway `list_skills` | `src/gateway/routers/skills.py` | HTTP GET | `SkillsListResponse` |
| Gateway `update_skill` | `src/gateway/routers/skills.py` | HTTP PUT + `SkillUpdateRequest` | `SkillResponse` |
| Gateway `install_skill` | `src/gateway/routers/skills.py` | HTTP POST + `SkillInstallRequest` | `SkillInstallResponse` |

---

## 10. Development Plan 1: Integrating Anthropic's Knowledge-Work Plugins

### Background: What Are Knowledge-Work Plugins?

Anthropic's [knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) is an open-source collection of 11 plugins that transform Claude into role-specific specialists. Each plugin bundles:

```
plugin-name/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest (name, version, description, author)
├── .mcp.json                # MCP server connections
├── commands/                # Slash commands (explicit user actions)
│   └── *.md                 # e.g., /sales:call-prep
└── skills/                  # Domain knowledge (auto-activated)
    └── skill-name/
        └── SKILL.md         # Frontmatter + instructions
```

### Compatibility Analysis: Thinktank.ai vs. Anthropic Plugins

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                 COMPATIBILITY MATRIX                                         │
├──────────────────┬───────────────────┬───────────────────────────────────────┤
│ Plugin Component │ Thinktank.ai Support  │ Gap / Action Required             │
├──────────────────┼───────────────────┼───────────────────────────────────────┤
│ skills/          │ ✅Compatible      │ SKILL.md format is identical.         │
│ SKILL.md         │                   │ Thinktank.ai's parser handles the same│
│                  │                   │ YAML frontmatter. Can load directly.  │
├──────────────────┼───────────────────┼───────────────────────────────────────┤
│ .mcp.json        │ ⚠️ Partial        │ Thinktank.ai uses extensions_config.json│
│                  │                   │ with "mcpServers" key. Format is      │
│                  │                   │ similar but needs merging.            │
├──────────────────┼───────────────────┼───────────────────────────────────────┤
│ commands/        │ ❌ Not supported  │ Thinktank.ai has no slash command system. │
│ *.md             │                   │ New feature needed.                   │
├──────────────────┼───────────────────┼───────────────────────────────────────┤
│ .claude-plugin/  │ ❌ Not supported  │ Thinktank.ai has no plugin manifest    │
│ plugin.json      │                   │ system. Need plugin registry.         │
├──────────────────┼───────────────────┼───────────────────────────────────────┤
│ CONNECTORS.md    │ N/A (docs only)   │ Human-readable docs, no integration   │
│                  │                   │ needed.                               │
└──────────────────┴───────────────────┴───────────────────────────────────────┘
```

### Development Plan

#### Phase 1: Plugin Registry & Manifest System (Week 1-2)

**Goal**: Enable Thinktank.ai to discover and manage plugins as first-class entities.

```
NEW FILES:
  src/plugins/
  ├── __init__.py
  ├── types.py           # PluginManifest, PluginState dataclasses
  ├── loader.py           # discover_plugins(), load_plugin()
  ├── registry.py         # PluginRegistry singleton
  └── installer.py        # install_plugin_from_repo(), install_plugin_from_dir()
```

**Key Data Model**:

```python
@dataclass
class PluginManifest:
    name: str              # "sales"
    version: str           # "1.0.0"
    description: str       # "Prospect research, call prep..."
    author: dict           # {"name": "Anthropic"}
    skills: list[Skill]    # Discovered from skills/ subdirectory
    commands: list[Command] # Discovered from commands/ subdirectory
    mcp_servers: dict      # From .mcp.json

@dataclass
class Command:
    name: str              # "forecast"
    description: str       # From frontmatter
    argument_hint: str     # "<period>"
    content: str           # Full markdown body
    plugin_name: str       # "sales"
```

**Plugin Directory Structure**:

```
think-tank/
├── plugins/                           ← NEW: Plugin storage
│   ├── installed/                     ← Installed plugins
│   │   ├── sales/                     ← From knowledge-work-plugins
│   │   │   ├── .claude-plugin/
│   │   │   │   └── plugin.json
│   │   │   ├── .mcp.json
│   │   │   ├── commands/
│   │   │   └── skills/
│   │   └── data/
│   └── marketplace.json               ← Registry of available sources
└── backend/
    └── src/plugins/                    ← NEW: Plugin management code
```

**Config Extension** (`config.yaml`):

```yaml
plugins:
  path: ../plugins/installed       # Where plugins live
  container_path: /mnt/plugins     # Virtual path in sandbox
  auto_merge_mcp: true             # Auto-merge .mcp.json into extensions_config
```

**Extensions Config Extension** (`extensions_config.json`):

```json
{
  "mcpServers": { ... },
  "skills": { ... },
  "plugins": {
    "sales": { "enabled": true },
    "data": { "enabled": false }
  }
}
```

#### Phase 2: Skill Integration from Plugins (Week 2-3)

**Goal**: Make plugin skills discoverable by the existing skills system.

**Approach**: Modify `load_skills()` to also scan the plugins directory.

```python
# Modified loader.py
def load_skills(skills_path=None, use_config=True, enabled_only=False) -> list[Skill]:
    skills = []

    # Existing: Scan skills/public and skills/custom
    skills.extend(_scan_skills_directory(skills_path))

    # NEW: Scan plugins for their skills
    plugins_path = _get_plugins_path()
    if plugins_path and plugins_path.exists():
        for plugin_dir in plugins_path.iterdir():
            if not plugin_dir.is_dir():
                continue
            plugin_skills_dir = plugin_dir / "skills"
            if plugin_skills_dir.exists():
                for skill_dir in plugin_skills_dir.iterdir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skill = parse_skill_file(
                            skill_file,
                            category=f"plugin:{plugin_dir.name}"  # e.g., "plugin:sales"
                        )
                        if skill:
                            skills.append(skill)

    # Apply enabled states + filter
    ...
    return skills
```

**Container Path Mapping**: Plugin skills would appear at `/mnt/plugins/{plugin}/{skills}/{skill-name}/SKILL.md`.

#### Phase 3: MCP Server Merging (Week 3-4)

**Goal**: Auto-merge plugin `.mcp.json` configs into the system.

```
┌──────────────────┐     ┌─────────────────┐     ┌───────────────────────┐
│ Plugin .mcp.json │     │ Merge Logic     │     │ extensions_config.json│
│                  │────>│                 │────>│ (merged output)       │
│ {                │     │ For each server:│     │                       │
│   "mcpServers":{ │     │ - Check for     │     │ Original MCP servers  │
│     "slack": {   │     │   conflicts     │     │ + Plugin MCP servers  │
│       "url":"."  │     │ - Prefix with   │     │ (namespaced)          │
│     }            │     │   plugin name   │     │                       │
│   }              │     │ - Add to config │     │                       │
│ }                │     │                 │     │                       │
└──────────────────┘     └─────────────────┘     └───────────────────────┘
```

**Conflict Resolution Strategy**:

```python
def merge_plugin_mcp_servers(plugin_name: str, plugin_mcp: dict, existing: dict) -> dict:
    for server_name, server_config in plugin_mcp.get("mcpServers", {}).items():
        # Namespace to avoid conflicts: "sales:slack", "data:slack"
        namespaced_name = f"{plugin_name}:{server_name}"
        if namespaced_name not in existing:
            existing[namespaced_name] = server_config
    return existing
```

#### Phase 4: Command System (Week 4-5)

**Goal**: Implement a slash command system that maps to plugin commands.

```
NEW FILES:
  src/commands/
  ├── __init__.py
  ├── types.py           # Command dataclass
  ├── parser.py           # Parse command .md files
  ├── registry.py         # CommandRegistry
  └── executor.py         # Execute commands via agent
```

**Command Execution Flow**:

```
User: /sales:call-prep Acme Corp
      │
      ▼
┌──────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│ CommandRegistry  │     │ Load command.md  │     │ Inject as user     │
│ .lookup(         │────>│ from plugin dir  │────>│ message + command  │
│  "sales",        │     │ Parse frontmatter│     │ context into agent │
│  "call-prep")    │     │ Extract body     │     │ conversation       │
└──────────────────┘     └──────────────────┘     └────────────────────┘
```

**Implementation Strategy**:
Commands are not tools — they're prompt injections. When a user invokes `/sales:call-prep`, the system:
1. Loads the command markdown
2. Prepends the command instructions to the user's message
3. Passes the augmented message to the agent

```python
def execute_command(plugin_name: str, command_name: str, args: str, state: dict):
    command = registry.get(plugin_name, command_name)
    augmented_message = f"""
    [COMMAND: /{plugin_name}:{command_name}]
    {command.content}

    User arguments: {args}
    """
    state["messages"].append(HumanMessage(content=augmented_message))
    return state
```

#### Phase 5: Gateway API & Frontend (Week 5-6)

**Goal**: REST API for plugin management + frontend UI.

**New Gateway Endpoints**:

```
GET  /api/plugins                    # List installed plugins
GET  /api/plugins/{name}             # Plugin details (skills, commands, MCP servers)
POST /api/plugins/install            # Install from repo URL or .zip
PUT  /api/plugins/{name}             # Enable/disable plugin
DELETE /api/plugins/{name}           # Uninstall plugin
GET  /api/plugins/{name}/commands    # List commands for a plugin
```

#### Architecture After Integration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Thinktank.ai + Plugins Architecture                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐                                                        │
│  │  User Request   │                                                        │
│  │  "Research       │                                                       │
│  │   Stripe for    │                                                        │
│  │   sales call"   │                                                        │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────┐                │
│  │  make_lead_agent(config)                                │                │
│  │  ├── System Prompt Assembly                             │                │
│  │  │   ├── <memory> from memory.json                      │                │
│  │  │   ├── <skill_system>                                 │                │
│  │  │   │   ├── Built-in skills (skills/public/)           │                │
│  │  │   │   ├── Custom skills (skills/custom/)             │                │
│  │  │   │   └── Plugin skills (plugins/installed/*/skills/)│  ← NEW         │
│  │  │   ├── <command_system>                               │  ← NEW         │
│  │  │   │   └── Available slash commands from plugins      │                │
│  │  │   └── <subagent_system>                              │                │
│  │  ├── Tools                                              │                │
│  │  │   ├── Sandbox tools (bash, read_file, etc.)          │                │
│  │  │   ├── Built-in tools (present_files, etc.)           │                │
│  │  │   ├── MCP tools (from extensions_config.json)        │                │
│  │  │   └── Plugin MCP tools (from .mcp.json, merged)      │  ← NEW         │
│  │  └── Middleware chain                                    │               │
│  └─────────────────────────────────────────────────────────┘                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Development Plan 2: MCP Code Execution for Context Efficiency

### Background: The Problem

Traditional MCP tool usage loads all tool definitions into the model's context upfront, creating two problems:

1. **Context bloat from tool definitions**: Every MCP tool's full schema (name, description, parameters, types) consumes tokens even when unused.
2. **Redundant data passage**: When chaining tools (e.g., read from Google Drive → write to Salesforce), intermediate results flow through the model context, multiplying token consumption.

### The Anthropic Approach

Instead of registering MCP tools as direct function calls, present them as a **filesystem-based code API**:

```
Traditional Approach:                    Code Execution Approach:
┌────────────────────────┐              ┌────────────────────────────────┐
│ System Prompt          │              │ System Prompt                  │
│ ┌────────────────────┐ │              │ "You have access to MCP tools  │
│ │ Tool: gdrive_read  │ │              │  organized as a code API at    │
│ │ desc: Read doc...  │ │              │  ./servers/. Explore with ls   │
│ │ params: {id: str}  │ │              │  and read files to discover    │
│ ├────────────────────┤ │              │  available tools."             │
│ │ Tool: gdrive_list  │ │              └────────────────────────────────┘
│ │ desc: List files...│ │
│ │ params: {q: str}   │ │              Agent explores on demand:
│ ├────────────────────┤ │              ls ./servers/
│ │ Tool: sf_update    │ │              → google-drive/  salesforce/
│ │ desc: Update...    │ │
│ │ params: {...}      │ │              read ./servers/google-drive/
│ ├────────────────────┤ │              getDocument.ts
│ │ [50 more tools...] │ │
│ └────────────────────┘ │              (Only loads what's needed)
│                        │
│ ALL tools loaded       │
│ even if unused!        │
└────────────────────────┘
```

### Thinktank.ai Implementation Plan

#### Phase 1: Code Execution MCP Server (Week 1-2)

**Goal**: Create a sandboxed TypeScript/Python execution environment as an MCP tool.

```
NEW FILES:
  src/mcp_code_execution/
  ├── __init__.py
  ├── server.py              # MCP server implementation
  ├── executor.py            # Code execution in sandbox
  ├── tool_registry.py       # Dynamic tool file generation
  └── templates/
      └── tool_wrapper.ts    # Template for wrapping MCP tools as functions
```

**New MCP Server**: `code-executor`

```json
// extensions_config.json
{
  "mcpServers": {
    "code-executor": {
      "enabled": true,
      "type": "stdio",
      "command": "python",
      "args": ["-m", "src.mcp_code_execution.server"],
      "description": "Execute code that orchestrates other MCP tools"
    }
  }
}
```

**Tools Exposed by the Server**:

```
┌──────────────────────────────────────────────────────────────────┐
│ code-executor MCP Server                                         │
├──────────────┬───────────────────────────────────────────────────┤
│ Tool         │ Description                                       │
├──────────────┼───────────────────────────────────────────────────┤
│ execute_code │ Run TypeScript/Python code in sandbox             │
│              │ Input: {code: str, language: "ts" | "py"}         │
│              │ Output: {stdout: str, stderr: str, exit_code: int}│
├──────────────┼───────────────────────────────────────────────────┤
│ search_tools │ Search available MCP tools by keyword             │
│              │ Input: {query: str, detail: "name"|"desc"|"full"} │
│              │ Output: {tools: [{name, desc, schema?}]}          │
├──────────────┼───────────────────────────────────────────────────┤
│ list_servers │ List available MCP servers                        │
│              │ Input: {}                                         │
│              │ Output: {servers: [{name, tool_count}]}           │
└──────────────┴───────────────────────────────────────────────────┘
```

#### Phase 1.1: `list_servers` Tool — Detailed Specification

**Purpose**: The entry point for the agent to discover what MCP servers are available without loading any tool schemas into context.

**Implementation** (`src/mcp_code_execution/tools/list_servers.py`):

```python
from langchain_core.tools import tool
from src.config.extensions_config import ExtensionsConfig
from src.mcp.cache import get_cached_mcp_tools

@tool("list_servers")
def list_servers_tool() -> str:
    """List all available MCP servers and their tool counts.

    Returns a summary of each enabled MCP server with the number of tools
    it provides. Use this to understand what integrations are available
    before searching for specific tools.

    Returns:
        JSON string with server names and tool counts.
    """
    extensions_config = ExtensionsConfig.from_file()
    enabled_servers = extensions_config.get_enabled_mcp_servers()

    # Group cached MCP tools by their server origin
    all_tools = get_cached_mcp_tools()
    server_tool_counts = _group_tools_by_server(all_tools)

    result = {
        "servers": [
            {
                "name": server_name,
                "description": config.description,
                "transport": config.type,
                "tool_count": server_tool_counts.get(server_name, 0),
            }
            for server_name, config in enabled_servers.items()
        ],
        "total_tools": len(all_tools),
    }
    return json.dumps(result, indent=2)
```

**Output Format (returned to agent)**:

```json
{
  "servers": [
    {
      "name": "google-drive",
      "description": "Google Drive file management",
      "transport": "http",
      "tool_count": 8
    },
    {
      "name": "salesforce",
      "description": "Salesforce CRM operations",
      "transport": "http",
      "tool_count": 12
    },
    {
      "name": "slack",
      "description": "Slack messaging",
      "transport": "http",
      "tool_count": 6
    }
  ],
  "total_tools": 26
}
```

**How the Agent Uses This Output**:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Agent Thinking After list_servers() Response                            │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Agent receives the JSON above (~200 tokens) instead of loading          │
│  all 26 tool schemas (~13K tokens).                                      │
│                                                                          │
│  Agent thinks: "User wants to update a Salesforce record with data       │
│  from Google Drive. I see both servers are available. Let me search      │
│  for the specific tools I need."                                         │
│                                                                          │
│  Next action: search_tools(query="document read", server="google-drive") │
│                                                                          │
│  KEY INSIGHT: The agent now knows WHAT servers exist and HOW MANY        │
│  tools each has, without consuming any tool-schema tokens. This          │
│  ~200 token summary replaces ~13K tokens of full tool definitions.       │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Server-to-Tool Grouping Logic**:

The `_group_tools_by_server()` function bridges the gap between LangChain's flat `BaseTool` list and our per-server organization. MCP tools loaded via `langchain-mcp-adapters` carry their server origin in the tool name prefix:

```python
def _group_tools_by_server(tools: list[BaseTool]) -> dict[str, int]:
    """Group MCP tools by their originating server.

    langchain-mcp-adapters names tools as '{server_name}__{tool_name}'.
    We parse this convention to reconstruct the server→tools mapping.

    Example:
        'google_drive__list_files' → server='google-drive', tool='list_files'
        'salesforce__update_record' → server='salesforce', tool='update_record'
    """
    server_counts: dict[str, int] = {}
    for tool in tools:
        if "__" in tool.name:
            server_name = tool.name.split("__")[0].replace("_", "-")
            server_counts[server_name] = server_counts.get(server_name, 0) + 1
        else:
            server_counts.setdefault("_ungrouped", 0)
            server_counts["_ungrouped"] += 1
    return server_counts
```

#### Phase 1.2: `search_tools` Tool — Detailed Specification

**Purpose**: Let the agent find specific tools by keyword without loading all tool schemas. Returns just enough information to decide which tool to use and, optionally, the full JSON Schema for generating code.

**Implementation** (`src/mcp_code_execution/tools/search_tools.py`):

```python
from langchain_core.tools import tool
from src.mcp.cache import get_cached_mcp_tools

@tool("search_tools")
def search_tools_tool(
    query: str,
    server: str | None = None,
    detail: str = "desc",
) -> str:
    """Search available MCP tools by keyword.

    Searches tool names and descriptions for matches. Use this to find
    the right tool before writing code that calls it via execute_code.

    Args:
        query: Search keyword(s) to match against tool names and descriptions.
               Examples: "list files", "send message", "update record"
        server: Optional server name to restrict search to (e.g., "google-drive").
                If omitted, searches all servers.
        detail: Level of detail in results:
                - "name": Tool names only (~minimal tokens)
                - "desc": Names + descriptions (~moderate tokens)
                - "full": Names + descriptions + full JSON Schema parameters
                          (~detailed, use only for tools you plan to call)

    Returns:
        JSON string with matching tools at the requested detail level.
    """
    all_tools = get_cached_mcp_tools()
    query_lower = query.lower()

    # Filter by server if specified
    if server:
        server_prefix = server.replace("-", "_") + "__"
        all_tools = [t for t in all_tools if t.name.startswith(server_prefix)]

    # Search by name and description
    matches = []
    for t in all_tools:
        name_match = query_lower in t.name.lower()
        desc_match = query_lower in (t.description or "").lower()
        if name_match or desc_match:
            matches.append(t)

    # Format based on detail level
    results = []
    for t in matches[:15]:  # Cap at 15 to avoid context bloat
        entry = _format_tool_entry(t, detail)
        results.append(entry)

    return json.dumps({
        "query": query,
        "server_filter": server,
        "match_count": len(matches),
        "showing": len(results),
        "tools": results,
    }, indent=2)


def _format_tool_entry(tool: BaseTool, detail: str) -> dict:
    """Format a single tool entry based on the requested detail level."""
    if "__" in tool.name:
        server, short_name = tool.name.split("__", 1)
        server = server.replace("_", "-")
    else:
        server, short_name = "_unknown", tool.name

    if detail == "name":
        return {"name": tool.name, "short_name": short_name, "server": server}
    elif detail == "desc":
        return {
            "name": tool.name, "short_name": short_name, "server": server,
            "description": (tool.description or "")[:200],
        }
    else:  # "full"
        return {
            "name": tool.name, "short_name": short_name, "server": server,
            "description": tool.description,
            "parameters": tool.args_schema.schema() if tool.args_schema else {},
            "wrapper_path": f"/mnt/code-api/servers/{server}/{short_name}.ts",
        }
```

**Output Examples at Each Detail Level**:

**`detail="name"` — Minimal (for browsing)**:

```json
{
  "query": "document",
  "server_filter": null,
  "match_count": 5,
  "showing": 5,
  "tools": [
    {"name": "google_drive__get_document", "short_name": "get_document", "server": "google-drive"},
    {"name": "google_drive__list_documents", "short_name": "list_documents", "server": "google-drive"},
    {"name": "google_drive__create_document", "short_name": "create_document", "server": "google-drive"},
    {"name": "notion__get_document", "short_name": "get_document", "server": "notion"},
    {"name": "salesforce__get_document_link", "short_name": "get_document_link", "server": "salesforce"}
  ]
}
```

**`detail="desc"` — Moderate (for choosing the right tool)**:

```json
{
  "query": "document",
  "server_filter": "google-drive",
  "match_count": 3,
  "showing": 3,
  "tools": [
    {
      "name": "google_drive__get_document",
      "short_name": "get_document",
      "server": "google-drive",
      "description": "Retrieve a document from Google Drive by its ID. Returns the document content, title, and metadata."
    },
    {
      "name": "google_drive__list_documents",
      "short_name": "list_documents",
      "server": "google-drive",
      "description": "List documents matching a query. Supports filtering by folder, type, and modification date."
    }
  ]
}
```

**`detail="full"` — Complete (for writing code against the tool)**:

```json
{
  "query": "get_document",
  "server_filter": "google-drive",
  "match_count": 1,
  "showing": 1,
  "tools": [
    {
      "name": "google_drive__get_document",
      "short_name": "get_document",
      "server": "google-drive",
      "description": "Retrieve a document from Google Drive by its ID.",
      "parameters": {
        "type": "object",
        "properties": {
          "documentId": {"type": "string", "description": "The ID of the document to retrieve"},
          "format": {"type": "string", "enum": ["text", "html", "markdown"], "default": "text"}
        },
        "required": ["documentId"]
      },
      "wrapper_path": "/mnt/code-api/servers/google-drive/get_document.ts"
    }
  ]
}
```

**How the Agent Turns search_tools Output into Actionable Code**:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│         SEARCH → DISCOVER → CODE GENERATION PIPELINE                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STEP 1: Agent calls search_tools(query="update record", server="salesforce")│
│                                                                              │
│  STEP 2: Agent receives tool metadata with detail="full":                    │
│  ┌─────────────────────────────────────────────────────────────────┐         │
│  │ {                                                               │         │
│  │   "name": "salesforce__update_record",                          │         │
│  │   "parameters": {                                               │         │
│  │     "properties": {                                             │         │
│  │       "objectType": {"type": "string"},                         │         │
│  │       "recordId": {"type": "string"},                           │         │
│  │       "fields": {"type": "object"}                              │         │
│  │     },                                                          │         │
│  │     "required": ["objectType", "recordId", "fields"]            │         │
│  │   },                                                            │         │
│  │   "wrapper_path": "/mnt/code-api/servers/salesforce/            │         │
│  │                     update_record.ts"                           │         │
│  │ }                                                               │         │
│  └─────────────────────────────────────────────────────────────────┘         │
│                                                                              │
│  STEP 3: Agent has TWO PATHS to generate actionable code:                    │
│                                                                              │
│  ┌──────────────────────────────┐   ┌───────────────────────────────┐        │
│  │  PATH A: Use wrapper import  │   │  PATH B: Use callMCPTool()    │        │
│  │  (typed, auto-generated)     │   │  (raw, always available)      │        │
│  │                              │   │                               │        │
│  │  // Agent reads wrapper_path │   │  // Agent uses name +         │        │
│  │  // to see full signature    │   │  // parameters from search    │        │
│  │  import { updateRecord }     │   │  // results directly          │        │
│  │    from './servers/          │   │  import { callMCPTool }       │        │
│  │     salesforce';             │   │    from './helpers/           │        │
│  │                              │   │     callMCPTool';             │        │
│  │  await updateRecord({        │   │                               │        │
│  │    objectType: "Opportunity",│   │  await callMCPTool(           │        │
│  │    recordId: "001abc",       │   │    "salesforce__update_record"│        │
│  │    fields: {                 │   │    {                          │        │
│  │      stage: "Closed Won"     │   │      objectType: "Opportunity │        │
│  │    }                         │   │      recordId: "001abc",      │        │
│  │  });                         │   │      fields: {stage: "Won"}   │        │
│  │                              │   │    }                          │        │
│  │  ✓ Type-safe                │   │  );                            │        │
│  │  ✓ IDE-like experience      │   │                                │        │
│  │  ✗ Requires reading wrapper │   │  ✓ No file read needed         │        │
│  │    file first                │   │  ✓ Fastest path               │        │
│  └──────────────────────────────┘   │  ✗ No type safety             │        │
│                                     └───────────────────────────────┘        │
│                                                                              │
│  STEP 4: Agent writes code and passes to execute_code tool                   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Key Design Decision: `wrapper_path` Field**:

The `wrapper_path` field in `search_tools` output is the bridge between discovery and code execution. It tells the agent: "if you want the full typed API for this tool, read this file." This enables a two-tier approach:

- **Quick path**: Agent already has enough from `detail="full"` to call `callMCPTool()` directly with the raw tool name and parameters
- **Typed path**: Agent reads the wrapper file via `read_file(wrapper_path)` to get the TypeScript interface, then writes typed code using the import

#### Phase 1.3: `execute_code` Tool — Detailed Specification

**Purpose**: The core tool that runs agent-generated code in the sandbox, routing MCP tool calls through a bridge function, and returning only stdout/stderr to the agent context.

**Implementation** (`src/mcp_code_execution/tools/execute_code.py`):

```python
import json
import uuid
from pathlib import Path

from langchain_core.tools import tool
from src.sandbox.tools import ensure_sandbox_initialized

CODE_API_DIR = Path(".think-tank/code-api")


@tool("execute_code")
def execute_code_tool(
    code: str,
    language: str = "typescript",
    timeout: int = 30,
) -> str:
    """Execute code that orchestrates MCP tool calls in the sandbox.

    The code runs in an isolated sandbox with access to all MCP tools
    via typed wrappers or the raw callMCPTool() helper. Only stdout
    and stderr are returned to context — intermediate data stays in
    the sandbox, saving tokens.

    Args:
        code: The code to execute. For TypeScript, you can import from:
              - './servers/{server_name}' for typed tool wrappers
              - './helpers/callMCPTool' for raw MCP tool access
              Use console.log() to emit results back to context.
        language: "typescript" (default) or "python"
        timeout: Max execution time in seconds (default: 30, max: 120)

    Returns:
        JSON string with execution results:
        {
            "exit_code": 0,
            "stdout": "...",
            "stderr": "...",
            "duration_ms": 1234,
            "tools_called": [
                {"tool": "google_drive__get_document", "status": "ok", "ms": 450},
                {"tool": "salesforce__update_record", "status": "ok", "ms": 230}
            ]
        }
    """
    sandbox = ensure_sandbox_initialized()
    timeout = min(timeout, 120)

    exec_id = str(uuid.uuid4())[:8]
    exec_dir = CODE_API_DIR / "executions" / exec_id

    if language == "typescript":
        file_name = f"exec_{exec_id}.ts"
        if "callMCPTool" not in code and "from './servers" not in code:
            code = "import { callMCPTool } from './helpers/callMCPTool';\n\n" + code
        runner_cmd = f"cd {CODE_API_DIR} && npx tsx executions/{exec_id}/{file_name}"
    else:
        file_name = f"exec_{exec_id}.py"
        if "call_mcp_tool" not in code and "from helpers" not in code:
            code = "from helpers.call_mcp_tool import call_mcp_tool\n\n" + code
        runner_cmd = f"cd {CODE_API_DIR} && python executions/{exec_id}/{file_name}"

    sandbox.write_file(str(exec_dir / file_name), code)
    result = sandbox.execute_command(runner_cmd, timeout=timeout)
    audit_log = _read_audit_log(sandbox, exec_dir / "audit.json")
    sandbox.execute_command(f"rm -rf {exec_dir}")

    return json.dumps({
        "exit_code": result.exit_code,
        "stdout": _truncate(result.stdout, max_chars=10000),
        "stderr": _truncate(result.stderr, max_chars=2000),
        "duration_ms": result.duration_ms,
        "tools_called": audit_log,
    }, indent=2)
```

**Output Format (returned to agent context)**:

```json
{
  "exit_code": 0,
  "stdout": "Found 3 quarterly reports.\nLatest: Q4 2025 Financial Summary\nUpdated Salesforce opportunity OPP-001 with summary.\nDone.",
  "stderr": "",
  "duration_ms": 2340,
  "tools_called": [
    {"tool": "google_drive__list_documents", "status": "ok", "ms": 890},
    {"tool": "google_drive__get_document", "status": "ok", "ms": 1120},
    {"tool": "salesforce__update_record", "status": "ok", "ms": 230}
  ]
}
```

**How the Agent Interprets and Acts on `execute_code` Output**:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│          EXECUTE_CODE OUTPUT → AGENT DECISION TREE                           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  execute_code() returns →                                                    │
│                                                                              │
│  ┌─────────────────────────┐                                                 │
│  │ exit_code == 0?         │                                                 │
│  └───┬─────────────┬───────┘                                                 │
│      │ YES         │ NO                                                      │
│      ▼             ▼                                                         │
│  ┌──────────┐  ┌───────────────────────────────────────────────┐             │
│  │ SUCCESS  │  │ FAILURE: Agent reads stderr to diagnose       │             │
│  │          │  │                                               │             │
│  │ Agent    │  │ ┌──────────────────────────────────────────┐  │             │
│  │ reads    │  │ │ stderr contains:                         │  │             │
│  │ stdout   │  │ │                                          │  │             │
│  │ and      │  │ │ A) "TypeError: ... is not a function"    │  │             │
│  │ presents │  │ │    → Wrong tool name or import path      │  │             │
│  │ results  │  │ │    → Agent calls search_tools() to find  │  │             │
│  │ to user  │  │ │      correct tool, rewrites code         │  │             │
│  │          │  │ │                                          │  │             │
│  │ Also     │  │ │ B) "MCP Error: 401 Unauthorized"         │  │             │
│  │ checks:  │  │ │    → Auth issue with MCP server          │  │             │
│  │          │  │ │    → Agent reports to user: "Salesforce  │  │             │
│  │ tools_   │  │ │      connection needs re-authentication" │  │             │
│  │ called[] │  │ │                                          │  │             │
│  │ for      │  │ │ C) "Timeout after 30000ms"               │  │             │
│  │ audit    │  │ │    → Agent retries with higher timeout   │  │             │
│  │ trail    │  │ │    → Or splits into smaller batches      │  │             │
│  │          │  │ │                                          │  │             │
│  └──────────┘  │ │ D) "ValidationError: missing 'recordId'" │  │             │
│                │ │    → Agent reads full schema via         │  │             │
│                │ │      search_tools(detail="full")         │  │             │
│                │ │    → Fixes parameter names, retries      │  │             │
│                │ └──────────────────────────────────────────┘  │             │
│                └───────────────────────────────────────────────┘             │
│                                                                              │
│  AUDIT TRAIL (tools_called[]):                                               │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │ The agent uses tools_called to:                                  │        │
│  │                                                                  │        │
│  │ 1. Verify all expected tools were called                         │        │
│  │    "I see 3 tools called — matches my 3-step workflow"           │        │
│  │                                                                  │        │
│  │ 2. Identify which tool failed (if status != "ok")                │        │
│  │    "salesforce__update_record failed — let me retry that step"   │        │
│  │                                                                  │        │
│  │ 3. Report execution time breakdown to user                       │        │
│  │    "Retrieved Drive doc (1.1s), updated Salesforce (0.2s)"       │        │
│  │                                                                  │        │
│  │ 4. Detect partial failures                                       │        │
│  │    "2 of 3 tools succeeded — the last update failed"             │        │
│  └──────────────────────────────────────────────────────────────────┘        │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Phase 1.4: The `callMCPTool` Bridge — How Code Becomes MCP Calls

The critical infrastructure that makes `execute_code` work is the `callMCPTool` bridge function. This function runs **inside the sandbox** and routes function calls to the actual MCP servers via a local bridge server:

**Bridge Function** (`helpers/callMCPTool.ts` — auto-generated, lives in sandbox):

```typescript
// .think-tank/code-api/helpers/callMCPTool.ts
import * as fs from 'fs';
import * as path from 'path';

const AUDIT_LOG: Array<{tool: string; status: string; ms: number; error?: string}> = [];
const BRIDGE_PORT = process.env.MCP_BRIDGE_PORT || '9876';

/**
 * Call an MCP tool by its full name (e.g., "google_drive__get_document").
 *
 * Sends the call to the MCP bridge server running outside the sandbox,
 * which routes it to the actual MCP server via MultiServerMCPClient.
 *
 * @param toolName - Full tool name in '{server}__{tool}' format
 * @param input - Tool input parameters matching the tool's JSON Schema
 * @returns The tool's response, parsed as JSON
 */
export async function callMCPTool<T = any>(
    toolName: string,
    input: Record<string, any>
): Promise<T> {
    const startTime = Date.now();
    try {
        const response = await fetch(`http://localhost:${BRIDGE_PORT}/call`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool: toolName, input }),
        });
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`MCP Error (${response.status}): ${errorText}`);
        }
        const result = await response.json() as T;
        AUDIT_LOG.push({ tool: toolName, status: 'ok', ms: Date.now() - startTime });
        _writeAuditLog();
        return result;
    } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        AUDIT_LOG.push({ tool: toolName, status: 'error', ms: Date.now() - startTime, error: errorMsg });
        _writeAuditLog();
        throw error;
    }
}

function _writeAuditLog(): void {
    const auditPath = path.join(process.cwd(), 'executions', process.env.EXEC_ID || '', 'audit.json');
    fs.mkdirSync(path.dirname(auditPath), { recursive: true });
    fs.writeFileSync(auditPath, JSON.stringify(AUDIT_LOG, null, 2));
}
```

**Python Equivalent** (`helpers/call_mcp_tool.py`):

```python
# .think-tank/code-api/helpers/call_mcp_tool.py
import json, os, time
from pathlib import Path
import requests

_AUDIT_LOG = []
_BRIDGE_PORT = os.environ.get("MCP_BRIDGE_PORT", "9876")

def call_mcp_tool(tool_name: str, input_data: dict) -> dict:
    """Call an MCP tool by its full name."""
    start = time.time()
    try:
        resp = requests.post(
            f"http://localhost:{_BRIDGE_PORT}/call",
            json={"tool": tool_name, "input": input_data},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        _AUDIT_LOG.append({"tool": tool_name, "status": "ok", "ms": int((time.time() - start) * 1000)})
        _write_audit_log()
        return result
    except Exception as e:
        _AUDIT_LOG.append({"tool": tool_name, "status": "error", "ms": int((time.time() - start) * 1000), "error": str(e)})
        _write_audit_log()
        raise

def _write_audit_log():
    exec_id = os.environ.get("EXEC_ID", "")
    audit_path = Path("executions") / exec_id / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(_AUDIT_LOG, indent=2))
```

**MCP Bridge Server** (runs alongside the sandbox, routes calls to real MCP servers):

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    MCP BRIDGE ARCHITECTURE                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SANDBOX ENVIRONMENT                     Thinktank.ai BACKEND                    │
│  ┌───────────────────────────────┐      ┌────────────────────────────────┐   │
│  │                               │      │                                │   │
│  │  Agent's generated code       │      │  MCP Bridge Server             │   │
│  │  (exec_abc123.ts)             │      │  (port 9876, localhost only)   │   │
│  │  │                            │      │  │                             │   │
│  │  ├── import { callMCPTool }   │      │  ├── POST /call                │   │
│  │  │                            │      │  │   Receives: {tool, input}   │   │
│  │  ├── callMCPTool(             │──────│──│                             │   │
│  │  │     "gdrive__get_document",│ HTTP │  │   Routes to:                │   │
│  │  │     {documentId: "abc"}    │ POST │  │   MultiServerMCPClient      │   │
│  │  │   )                        │      │  │   .call_tool(tool, input)   │   │
│  │  │                            │      │  │                             │   │
│  │  │   ← returns document data ─│──────│──│── Returns: tool response    │   │
│  │  │                            │      │  │                             │   │
│  │  ├── // Process data locally  │      │  └─────────────────────────────│   │
│  │  │   const summary = ...      │      │                                │   │
│  │  │   Data stays in sandbox!   │      │  Bridge Server Implementation: │   │
│  │  │                            │      │  ┌─────────────────────────────│   │
│  │  ├── callMCPTool(             │──────│──│  # bridge.py                │   │
│  │  │     "sf__update_record",   │ HTTP │  │  from fastapi import        │   │
│  │  │     {fields: ...}          │ POST │  │    FastAPI                  │   │
│  │  │   )                        │      │  │  from src.mcp.cache import  │   │
│  │  │                            │      │  │    get_cached_mcp_tools     │   │
│  │  ├── console.log("Done")      │      │  │                             │   │
│  │  │   ↑ Only this goes back    │      │  │  _tool_map = {}             │   │
│  │  │     to agent context!      │      │  │                             │   │
│  │  │                            │      │  │  @app.post("/call")         │   │
│  └───────────────────────────────┘      │  │  async def call_tool(req):  │   │
│                                         │  │    tool = _tool_map[req.tool│   │
│                                         │  │    return await             │   │
│                                         │  │      tool.ainvoke(req.input)│   │
│                                         │  └─────────────────────────────┘   │
│                                         └────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Phase 1.5: Complete Agent Workflow — From Query to Code Execution

Here is the full end-to-end flow showing how all three tools work together:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  USER: "Find the latest quarterly report in Google Drive and update the      │
│         Salesforce opportunity OPP-001 with a summary of the key findings."  │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
═══════════════════════════════════════╪════════════════════════════════════════
  TURN 1: Discovery (~700 tokens)      │
═══════════════════════════════════════╪════════════════════════════════════════
                                       │
  Agent calls: list_servers()    →  Learns google-drive (8 tools), salesforce
                                    (12 tools), slack (6 tools) are available

  Agent calls (parallel):
  ├── search_tools(query="list documents", server="google-drive", detail="full")
  │   → Gets: google_drive__list_documents with full JSON Schema
  │   → Gets: google_drive__get_document with full JSON Schema
  │
  └── search_tools(query="update record", server="salesforce", detail="full")
      → Gets: salesforce__update_record with full JSON Schema

  Discovery cost: ~700 tokens (vs ~13K for loading all 26 tool schemas)

═══════════════════════════════════════╪════════════════════════════════════════
  TURN 2: Code Generation & Execution  │  (~150 tokens result)
═══════════════════════════════════════╪════════════════════════════════════════

  Agent GENERATES code from discovered schemas, calls execute_code({code: `
    import { callMCPTool } from './helpers/callMCPTool';

    // Step 1: Search for quarterly reports
    const files = await callMCPTool('google_drive__list_documents', {
      query: 'quarterly report',
    });

    // Step 2: Get the latest one
    const sorted = files.documents.sort((a, b) =>
      new Date(b.modifiedTime).getTime() - new Date(a.modifiedTime).getTime()
    );
    const latest = sorted[0];
    console.log('Latest report: ' + latest.title);

    // Step 3: Read full document content (stays in sandbox!)
    const doc = await callMCPTool('google_drive__get_document', {
      documentId: latest.id, format: 'text',
    });

    // Step 4: Extract key findings (processed locally, never enters context)
    const keyFindings = doc.content.split('\\n')
      .filter(l => l.match(/key finding|highlight|conclusion/i))
      .slice(0, 5).join('\\n');
    const summary = 'Key Findings from ' + latest.title + ':\\n' + keyFindings;
    console.log('Summary:\\n' + summary);

    // Step 5: Update Salesforce
    await callMCPTool('salesforce__update_record', {
      objectType: 'Opportunity', recordId: 'OPP-001',
      fields: { Description: summary }
    });
    console.log('Updated Salesforce OPP-001 with summary.');
  `})

  Returns to context (~150 tokens):
  {
    "exit_code": 0,
    "stdout": "Latest report: Q4 2025 Financial Summary\n
               Summary:\n- Revenue grew 23% YoY to $4.2B\n
               - Operating margin expanded 180bps\n
               Updated Salesforce OPP-001 with summary.",
    "tools_called": [
      {"tool": "google_drive__list_documents", "status": "ok", "ms": 890},
      {"tool": "google_drive__get_document",   "status": "ok", "ms": 1820},
      {"tool": "salesforce__update_record",    "status": "ok", "ms": 430}
    ]
  }

═══════════════════════════════════════╪════════════════════════════════════════
  TOTAL                                │
═══════════════════════════════════════╪════════════════════════════════════════

  TOTAL CONTEXT USED:     ~1,050 tokens
  WITHOUT CODE EXECUTION: ~213K tokens (26 tool schemas + document + roundtrips)
  SAVINGS:                99.5%
```

#### Phase 2: Tool-as-Code Wrappers (Week 2-3)

**Goal**: Auto-generate typed code wrappers for each MCP tool.

```
Auto-generated at startup:
.think-tank/code-api/
├── servers/
│   ├── google-drive/
│   │   ├── index.ts          # Re-exports all tools
│   │   ├── getDocument.ts    # Typed wrapper
│   │   └── listFiles.ts
│   ├── salesforce/
│   │   ├── index.ts
│   │   ├── updateRecord.ts
│   │   └── queryRecords.ts
│   └── slack/
│       ├── index.ts
│       ├── sendMessage.ts
│       └── searchMessages.ts
└── helpers/
    ├── callMCPTool.ts        # Core MCP bridge function
    └── types.ts              # Shared type definitions
```

**Wrapper Template**:

```typescript
// Auto-generated: servers/google-drive/getDocument.ts
import { callMCPTool } from '../../helpers/callMCPTool';

interface GetDocumentInput {
  documentId: string;
}

interface GetDocumentResponse {
  content: string;
  title: string;
  mimeType: string;
}

/**
 * Retrieve a document from Google Drive by ID.
 */
export async function getDocument(input: GetDocumentInput): Promise<GetDocumentResponse> {
  return callMCPTool<GetDocumentResponse>('google_drive__get_document', input);
}
```

**Generation Logic**:

```python
# tool_registry.py
def generate_code_api(mcp_tools: list[BaseTool]) -> None:
    """Generate TypeScript wrappers for all MCP tools."""
    servers = group_tools_by_server(mcp_tools)

    for server_name, tools in servers.items():
        server_dir = CODE_API_DIR / "servers" / server_name
        server_dir.mkdir(parents=True, exist_ok=True)

        for tool in tools:
            wrapper = generate_wrapper(tool)
            (server_dir / f"{tool.short_name}.ts").write_text(wrapper)

        index = generate_index(tools)
        (server_dir / "index.ts").write_text(index)
```

#### Phase 3: Agent Prompt Adaptation (Week 3-4)

**Goal**: Modify the system prompt to guide the agent toward code execution for multi-tool workflows.

**New System Prompt Section**:

```xml
<code_execution_system>
You have access to MCP tools organized as a code API at /mnt/code-api/servers/.

**When to use code execution (via execute_code tool):**
- Chaining multiple MCP tool calls together
- Processing/filtering large data before returning to context
- Loops over collections (e.g., updating 10 records)
- Data transformation between tools

**When to use direct tool calls (traditional):**
- Single, standalone tool calls
- Simple read operations
- When you need to see the full result

**Discovery Pattern:**
1. list_servers() → see available MCP servers
2. search_tools("search term") → find relevant tools
3. read_file("/mnt/code-api/servers/{server}/{tool}.ts") → see full signature
4. execute_code(code) → run multi-step workflow

**Example:**
Instead of:
  1. Call google_drive_list(query="quarterly report")     → 150K tokens result
  2. Call google_drive_get(id="...")                       → 50K tokens result
  3. Call salesforce_update(data=...)                      → Send data back

Use code execution:
```typescript
const files = await listFiles({query: "quarterly report"});
const latest = files.sort(byDate).slice(0, 1)[0];
const doc = await getDocument({documentId: latest.id});
const summary = doc.content.substring(0, 500);
await updateRecord({object: "Opportunity", data: {notes: summary}});
console.log("Updated Salesforce with summary");
```
Result: Only the console.log output enters context (~50 tokens vs 200K+)
</code_execution_system>
```

#### Phase 4: Sandbox Integration (Week 4-5)

**Goal**: Run generated code safely within Thinktank.ai's sandbox.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    CODE EXECUTION ARCHITECTURE                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Agent                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐        │
│  │ "I need to fetch Drive doc and update Salesforce"            │        │
│  │                                                              │        │
│  │ Tool call: execute_code({                                    │        │
│  │   code: `                                                    │        │
│  │     const doc = await getDocument({id: "abc"});              │        │
│  │     const summary = doc.content.slice(0, 500);               │        │
│  │     await updateRecord({data: {notes: summary}});            │        │
│  │     console.log("Done: " + doc.title);                       │        │
│  │   `,                                                         │        │
│  │   language: "ts"                                             │        │
│  │ })                                                           │        │
│  └────────────────────────────┬─────────────────────────────────┘        │
│                               │                                          │
│  Code Executor MCP Server     │                                          │
│  ┌────────────────────────────▼─────────────────────────────────┐        │
│  │                                                              │        │
│  │  1. Receive code string                                      │        │
│  │  2. Write to temp file in sandbox                            │        │
│  │  3. Execute via sandbox.execute_command("npx tsx temp.ts")   │        │
│  │  4. Code calls callMCPTool() which routes to real MCP        │        │
│  │     servers via the MultiServerMCPClient                     │        │
│  │  5. Capture stdout/stderr                                    │        │
│  │  6. Return only console output to agent                      │        │
│  │                                                              │        │
│  │  ┌──────────────────────────────────────────────────┐        │        │
│  │  │ SANDBOX (isolated execution)                     │        │        │
│  │  │                                                  │        │        │
│  │  │  temp.ts ──exec──> stdout: "Done: Q4 Report"     │        │        │
│  │  │       │                                          │        │        │
│  │  │       ├── callMCPTool("gdrive__get") ──┐         │        │        │
│  │  │       │                                 │        │        │        │
│  │  │       │    ┌────────────────────────┐   │        │        │        │
│  │  │       │    │ Google Drive MCP       │<──┘        │        │        │
│  │  │       │    │ (returns 50KB doc)     │            │        │        │
│  │  │       │    └────────────────────────┘            │        │        │
│  │  │       │         Data stays in sandbox!           │        │        │
│  │  │       │                                          │        │        │
│  │  │       ├── callMCPTool("sf__update") ──┐          │        │        │
│  │  │       │                                │         │        │        │
│  │  │       │    ┌────────────────────────┐  │         │        │        │
│  │  │       │    │ Salesforce MCP         │<─┘         │        │        │
│  │  │       │    │ (receives summary)     │            │        │        │
│  │  │       │    └────────────────────────┘            │        │        │
│  │  │       │                                          │        │        │
│  │  └───────┴──────────────────────────────────────────┘        │        │
│  │                                                              │        │
│  │  Return to agent: {stdout: "Done: Q4 Report", exit: 0}       │        │
│  └──────────────────────────────────────────────────────────────┘        │
│                               │                                          │
│  Agent Context                │                                          │
│  ┌────────────────────────────▼─────────────────────────────────┐        │
│  │ Only ~50 tokens entered context instead of 200K+!            │        │
│  │ Result: "Done: Q4 Report"                                    │        │
│  │                                                              │        │
│  │ 98.7% context reduction for multi-tool workflows             │        │
│  └──────────────────────────────────────────────────────────────┘        │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Phase 5: Progressive Tool Discovery (Week 5-6)

**Goal**: Replace bulk tool loading with on-demand discovery.

**Current approach** (loads ALL MCP tools into context):

```python
# src/tools/tools.py — current
def get_available_tools(...):
    tools = []
    # ... loads ALL MCP tool schemas into tools list
    mcp_tools = get_cached_mcp_tools(...)
    tools.extend(mcp_tools)  # Every tool's full schema enters context
    return tools
```

**New approach** (lazy discovery):

```python
# src/tools/tools.py — proposed
def get_available_tools(..., code_execution_mode=False):
    tools = []

    if code_execution_mode and include_mcp:
        # Instead of loading ALL MCP tools, provide discovery tools
        tools.extend([
            search_tools_tool,    # Search tools by keyword
            list_servers_tool,    # List available servers
            execute_code_tool,    # Execute code that uses tools
        ])
        # MCP tools are NOT loaded into context
        # Agent discovers them via search_tools and reads wrapper files
    else:
        # Fallback: traditional approach for simple tasks
        mcp_tools = get_cached_mcp_tools(...)
        tools.extend(mcp_tools)

    return tools
```

**Decision Logic** (when to use code execution mode):

```python
# In make_lead_agent() or middleware
def should_use_code_execution(config: RunnableConfig) -> bool:
    mcp_tool_count = len(get_cached_mcp_tools())
    # Use code execution when there are many MCP tools
    return (
        config.get("configurable", {}).get("code_execution_mode", "auto") == "always"
        or (mcp_tool_count > 20 and auto_mode)
    )
```

#### Summary: Context Savings

```
┌──────────────────────────────────────────────────────────────────────┐
│                    CONTEXT EFFICIENCY COMPARISON                     │
├─────────────────────────┬────────────────┬───────────────────────────┤
│ Scenario                │ Traditional    │ Code Execution            │
├─────────────────────────┼────────────────┼───────────────────────────┤
│ 50 MCP tools loaded     │ ~25K tokens    │ ~500 tokens (3 tools)     │
│ (tool definitions)      │                │ + on-demand discovery     │
├─────────────────────────┼────────────────┼───────────────────────────┤
│ Read 100KB doc from     │ 100K tokens    │ ~100 tokens               │
│ Drive, summarize,       │ + 50K summary  │ (only console.log output) │
│ update Salesforce       │ + 5K update    │                           │
│                         │ = ~155K tokens │ = ~100 tokens             │
├─────────────────────────┼────────────────┼───────────────────────────┤
│ Update 10 records       │ 10 × 5K        │ ~200 tokens               │
│ in a loop               │ = ~50K tokens  │ (loop runs in sandbox)    │
├─────────────────────────┼────────────────┼───────────────────────────┤
│ TOTAL                   │ ~230K tokens   │ ~800 tokens               │
│                         │                │ (99.6% reduction)         │
└─────────────────────────┴────────────────┴───────────────────────────┘
```

#### Configuration

```yaml
# config.yaml addition
code_execution:
  enabled: true
  mode: "auto"              # "auto" | "always" | "never"
  auto_threshold: 20        # Use code execution when MCP tools > N
  language: "typescript"    # "typescript" | "python"
  sandbox_timeout: 30       # Max execution time in seconds
  max_output_chars: 10000   # Truncate stdout beyond this
```

---

## Appendix: File Reference Quick-Lookup

| File | Purpose | Key Functions |
|------|---------|---------------|
| `src/skills/__init__.py` | Module exports | `load_skills`, `Skill` |
| `src/skills/types.py` | Skill dataclass | `Skill`, `get_container_path()`, `get_container_file_path()` |
| `src/skills/loader.py` | Discovery & loading | `load_skills()`, `get_skills_root_path()` |
| `src/skills/parser.py` | YAML frontmatter parsing | `parse_skill_file()` |
| `src/config/skills_config.py` | Path configuration | `SkillsConfig`, `get_skills_path()`, `get_skill_container_path()` |
| `src/config/extensions_config.py` | Enabled state management | `ExtensionsConfig`, `is_skill_enabled()`, `from_file()` |
| `src/agents/lead_agent/prompt.py` | Prompt injection | `get_skills_prompt_section()`, `apply_prompt_template()` |
| `src/gateway/routers/skills.py` | REST API | `list_skills`, `get_skill`, `update_skill`, `install_skill` |
| `langchain/.../todo.py` | TodoList middleware (reference) | `TodoListMiddleware`, `write_todos` |
