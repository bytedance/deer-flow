from datetime import datetime

from src.agents.lead_agent.prompts.composer import PromptComposer
from src.skills import load_skills

# Singleton composer instance (fragments are cached on first load)
_composer = PromptComposer()


def _build_subagent_section(max_concurrent: int) -> str:
    """Build the subagent system prompt section with dynamic concurrency limit.

    Args:
        max_concurrent: Maximum number of concurrent subagent calls allowed per response.

    Returns:
        Formatted subagent section string.
    """
    n = max_concurrent
    return f"""<subagent_system>
**🚀 SUBAGENT MODE ACTIVE - DECOMPOSE, DELEGATE, SYNTHESIZE**

You are running with subagent capabilities enabled. Your role is to be a **task orchestrator**:
1. **DECOMPOSE**: Break complex tasks into parallel sub-tasks
2. **DELEGATE**: Launch multiple subagents simultaneously using parallel `task` calls
3. **SYNTHESIZE**: Collect and integrate results into a coherent answer

**CORE PRINCIPLE: Complex tasks should be decomposed and distributed across multiple subagents for parallel execution.**

**⛔ HARD CONCURRENCY LIMIT: MAXIMUM {n} `task` CALLS PER RESPONSE. THIS IS NOT OPTIONAL.**
- Each response, you may include **at most {n}** `task` tool calls. Any excess calls are **silently discarded** by the system — you will lose that work.
- **Before launching subagents, you MUST count your sub-tasks in your thinking:**
  - If count ≤ {n}: Launch all in this response.
  - If count > {n}: **Pick the {n} most important/foundational sub-tasks for this turn.** Save the rest for the next turn.
- **Multi-batch execution** (for >{n} sub-tasks):
  - Turn 1: Launch sub-tasks 1-{n} in parallel → wait for results
  - Turn 2: Launch next batch in parallel → wait for results
  - ... continue until all sub-tasks are complete
  - Final turn: Synthesize ALL results into a coherent answer
- **Example thinking pattern**: "I identified 6 sub-tasks. Since the limit is {n} per turn, I will launch the first {n} now, and the rest in the next turn."

**Available Subagents:**
- **general-purpose**: For ANY non-trivial task - web research, code exploration, file operations, analysis, etc.
- **bash**: For command execution (git, build, test, deploy operations)

**Your Orchestration Strategy:**

✅ **DECOMPOSE + PARALLEL EXECUTION (Preferred Approach):**

For complex queries, break them down into focused sub-tasks and execute in parallel batches (max {n} per turn):

**Example 1: "Why is Tencent's stock price declining?" (3 sub-tasks → 1 batch)**
→ Turn 1: Launch 3 subagents in parallel:
- Subagent 1: Recent financial reports, earnings data, and revenue trends
- Subagent 2: Negative news, controversies, and regulatory issues
- Subagent 3: Industry trends, competitor performance, and market sentiment
→ Turn 2: Synthesize results

**Example 2: "Compare 5 cloud providers" (5 sub-tasks → multi-batch)**
→ Turn 1: Launch {n} subagents in parallel (first batch)
→ Turn 2: Launch remaining subagents in parallel
→ Final turn: Synthesize ALL results into comprehensive comparison

**Example 3: "Refactor the authentication system"**
→ Turn 1: Launch 3 subagents in parallel:
- Subagent 1: Analyze current auth implementation and technical debt
- Subagent 2: Research best practices and security patterns
- Subagent 3: Review related tests, documentation, and vulnerabilities
→ Turn 2: Synthesize results

✅ **USE Parallel Subagents (max {n} per turn) when:**
- **Complex research questions**: Requires multiple information sources or perspectives
- **Multi-aspect analysis**: Task has several independent dimensions to explore
- **Large codebases**: Need to analyze different parts simultaneously
- **Comprehensive investigations**: Questions requiring thorough coverage from multiple angles

❌ **DO NOT use subagents (execute directly) when:**
- **Task cannot be decomposed**: If you can't break it into 2+ meaningful parallel sub-tasks, execute directly
- **Ultra-simple actions**: Read one file, quick edits, single commands
- **Need immediate clarification**: Must ask user before proceeding
- **Meta conversation**: Questions about conversation history
- **Sequential dependencies**: Each step depends on previous results (do steps yourself sequentially)

**CRITICAL WORKFLOW** (STRICTLY follow this before EVERY action):
1. **COUNT**: In your thinking, list all sub-tasks and count them explicitly: "I have N sub-tasks"
2. **PLAN BATCHES**: If N > {n}, explicitly plan which sub-tasks go in which batch:
   - "Batch 1 (this turn): first {n} sub-tasks"
   - "Batch 2 (next turn): next batch of sub-tasks"
3. **EXECUTE**: Launch ONLY the current batch (max {n} `task` calls). Do NOT launch sub-tasks from future batches.
4. **REPEAT**: After results return, launch the next batch. Continue until all batches complete.
5. **SYNTHESIZE**: After ALL batches are done, synthesize all results.
6. **Cannot decompose** → Execute directly using available tools (bash, read_file, web_search, etc.)

**⛔ VIOLATION: Launching more than {n} `task` calls in a single response is a HARD ERROR. The system WILL discard excess calls and you WILL lose work. Always batch.**

**Remember: Subagents are for parallel decomposition, not for wrapping single tasks.**

**How It Works:**
- The task tool runs subagents asynchronously in the background
- The backend automatically polls for completion (you don't need to poll)
- The tool call will block until the subagent completes its work
- Once complete, the result is returned to you directly

**Usage Example 1 - Single Batch (≤{n} sub-tasks):**

```python
# User asks: "Why is Tencent's stock price declining?"
# Thinking: 3 sub-tasks → fits in 1 batch

# Turn 1: Launch 3 subagents in parallel
task(description="Tencent financial data", prompt="...", subagent_type="general-purpose")
task(description="Tencent news & regulation", prompt="...", subagent_type="general-purpose")
task(description="Industry & market trends", prompt="...", subagent_type="general-purpose")
# All 3 run in parallel → synthesize results
```

**Usage Example 2 - Multiple Batches (>{n} sub-tasks):**

```python
# User asks: "Compare AWS, Azure, GCP, Alibaba Cloud, and Oracle Cloud"
# Thinking: 5 sub-tasks → need multiple batches (max {n} per batch)

# Turn 1: Launch first batch of {n}
task(description="AWS analysis", prompt="...", subagent_type="general-purpose")
task(description="Azure analysis", prompt="...", subagent_type="general-purpose")
task(description="GCP analysis", prompt="...", subagent_type="general-purpose")

# Turn 2: Launch remaining batch (after first batch completes)
task(description="Alibaba Cloud analysis", prompt="...", subagent_type="general-purpose")
task(description="Oracle Cloud analysis", prompt="...", subagent_type="general-purpose")

# Turn 3: Synthesize ALL results from both batches
```

**Counter-Example - Direct Execution (NO subagents):**

```python
# User asks: "Run the tests"
# Thinking: Cannot decompose into parallel sub-tasks
# → Execute directly

bash("npm test")  # Direct execution, not task()
```

**CRITICAL**:
- **Max {n} `task` calls per turn** - the system enforces this, excess calls are discarded
- Only use `task` when you can launch 2+ subagents in parallel
- Single task = No value from subagents = Execute directly
- For >{n} sub-tasks, use sequential batches of {n} across multiple turns
</subagent_system>"""


def _get_memory_context(user_id: str | None = None) -> str:
    """Get memory context for injection into system prompt.

    Args:
        user_id: The user identifier for per-user memory. Falls back to default if None.

    Returns:
        Formatted memory context string wrapped in XML tags, or empty string if disabled.
    """
    try:
        from src.agents.memory import format_memory_for_injection, get_memory_data
        from src.config.memory_config import get_memory_config

        config = get_memory_config()
        if not config.enabled or not config.injection_enabled:
            return ""

        memory_data = get_memory_data(user_id=user_id or "local")
        memory_content = format_memory_for_injection(memory_data, max_tokens=config.max_injection_tokens)

        if not memory_content.strip():
            return ""

        return f"""<memory>
{memory_content}
</memory>
"""
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"Failed to load memory context: {e}")
        return ""


def get_skills_prompt_section() -> str:
    """Generate the skills prompt section with available skills list.

    Returns the <skill_system>...</skill_system> block listing all enabled skills,
    suitable for injection into any agent's system prompt.
    """
    skills = load_skills(enabled_only=True)

    try:
        from src.config import get_app_config

        config = get_app_config()
        container_base_path = config.skills.container_path
    except Exception:
        container_base_path = "/mnt/skills"

    if not skills:
        return ""

    skill_items = "\n".join(
        f"    <skill>\n        <name>{skill.name}</name>\n        <description>{skill.description}</description>\n        <location>{skill.get_container_file_path(container_base_path)}</location>\n    </skill>" for skill in skills
    )
    skills_list = f"<available_skills>\n{skill_items}\n</available_skills>"

    return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks. Each skill contains best practices, frameworks, and references to additional resources.

**Progressive Loading Pattern:**
1. When a user query matches a skill's use case, immediately call `read_file` on the skill's main file using the path attribute provided in the skill tag below
2. Read and understand the skill's workflow and instructions
3. The skill file contains references to external resources under the same folder
4. Load referenced resources only when needed during execution
5. Follow the skill's instructions precisely

**Skills are located at:** {container_base_path}

{skills_list}

</skill_system>"""


def _build_ptc_section() -> str:
    """Build the PTC (Programmatic Tool Calling) system prompt section.

    Lists available MCP tool modules with import examples so the LLM knows
    it can use ``execute_python`` with MCP tool wrappers.

    Returns:
        Formatted PTC section string, or empty string if PTC is not enabled
        or no MCP tools are available.
    """
    try:
        from src.config.app_config import get_app_config

        config = get_app_config()
        if not config.sandbox or not config.sandbox.ptc_enabled:
            return ""
    except Exception:
        return ""

    try:
        from src.mcp.cache import get_cached_mcp_tools_by_server
        from src.ptc.client_codegen import _sanitize_identifier
        from src.tools.catalog import ToolCatalog

        by_server = get_cached_mcp_tools_by_server()
        if not by_server:
            return ""

        # Build catalog for schema info
        all_tools = []
        mcp_map = {}
        for server_name, tools in by_server.items():
            all_tools.extend(tools)
            for t in tools:
                mcp_map[t.name] = server_name

        catalog = ToolCatalog.from_tools(tools=all_tools, core_tool_names=set(), mcp_server_map=mcp_map)
        catalog_by_server = catalog.get_tools_by_server()

        # Build import examples
        module_lines: list[str] = []
        for server_name, entries in sorted(catalog_by_server.items(), key=lambda x: x[0] or ""):
            if server_name is None:
                continue
            safe = _sanitize_identifier(server_name)
            func_names = ", ".join(_sanitize_identifier(e.name) for e in entries[:5])
            if len(entries) > 5:
                func_names += ", ..."
            module_lines.append(f"  - from tools.{safe} import {func_names}")

        if not module_lines:
            return ""

        modules_str = "\n".join(module_lines)

        return f"""<ptc_system>
Programmatic Tool Calling (PTC) is enabled.
When calling 3+ MCP tools or filtering/aggregating results in code,
use execute_python with tool imports instead of individual tool calls.
This reduces round-trips and keeps intermediate data out of the conversation.

Available modules:
{modules_str}

Example:
  from tools.postgres import query
  import json
  results = query(sql="SELECT * FROM sales WHERE region='West'")
  filtered = [r for r in json.loads(results) if r['revenue'] > 10000]
  print(json.dumps(filtered))

Rules:
- Each execute_python call is stateless. Import all needed modules at the top.
- Only the final print() output enters the conversation context.
- Use PTC when programmatic filtering, aggregation, or multi-tool orchestration is beneficial.
- For simple single-tool calls, use the tool directly (no need for PTC).
</ptc_system>"""

    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to build PTC section: %s", e)
        return ""


def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    thinking_enabled: bool = False,
    tool_policies: str = "",
    tool_search_section: str = "",
    ptc_section: str = "",
) -> str:
    # Get memory context
    memory_context = _get_memory_context()

    # Include subagent section only if enabled (from runtime parameter)
    n = max_concurrent_subagents
    subagent_section = _build_subagent_section(n) if subagent_enabled else ""

    # Add subagent reminder to critical_reminders if enabled
    subagent_reminder = (
        "- **Orchestrator Mode**: You are a task orchestrator - decompose complex tasks into parallel sub-tasks. "
        f"**HARD LIMIT: max {n} `task` calls per response.** "
        f"If >{n} sub-tasks, split into sequential batches of ≤{n}. Synthesize after ALL batches complete.\n"
        if subagent_enabled
        else ""
    )

    # Add subagent thinking guidance if enabled
    subagent_thinking = (
        "- **DECOMPOSITION CHECK: Can this task be broken into 2+ parallel sub-tasks? If YES, COUNT them. "
        f"If count > {n}, you MUST plan batches of ≤{n} and only launch the FIRST batch now. "
        f"NEVER launch more than {n} `task` calls in one response.**\n"
        if subagent_enabled
        else ""
    )

    # Get skills section
    skills_section = get_skills_prompt_section()

    # Assemble via PromptComposer
    return _composer.compose(
        memory_context=memory_context,
        subagent_section=subagent_section,
        subagent_thinking=subagent_thinking,
        subagent_reminder=subagent_reminder,
        tool_policies=tool_policies,
        tool_search_section=tool_search_section,
        ptc_section=ptc_section,
        skills_section=skills_section,
        current_date=datetime.now().strftime("%Y-%m-%d, %A"),
    )
