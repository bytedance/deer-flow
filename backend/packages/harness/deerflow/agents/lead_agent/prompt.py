"""
Lead Agent 系统提示词模板模块

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 构建DeerFlow代理的系统提示词，定义代理的行为和风格
2. 动态组合各种功能模块（记忆、技能、子代理等）
3. 提供一致的用户体验和代理行为

**核心设计模式**：
- 模板模式：使用字符串模板构建提示词
- 组合模式：动态组装不同的功能模块
- 策略模式：根据配置选择不同的提示词部分

**为什么这样设计**：
- **模块化**：每个功能有独立的提示词部分
- **可配置**：根据运行时参数动态调整
- **一致性**：确保所有代理行为一致
- **可扩展**：便于添加新的功能模块

**模块职责**：
1. 构建子代理系统提示词
2. 组装完整的系统提示词模板
3. 注入记忆、技能、工具等信息
4. 提供辅助工具和最佳实践指导
"""

import logging
from datetime import datetime

from deerflow.config.agents_config import load_agent_soul
from deerflow.skills import load_skills
from deerflow.subagents import get_available_subagent_names

logger = logging.getLogger(__name__)


def _build_subagent_section(max_concurrent: int) -> str:
    """
    构建子代理系统提示词部分，包含动态并发限制

    ===================
    设计思路说明
    ===================

    **核心职责**：
    生成子代理模式的完整提示词，指导代理如何使用子代理能力

    **为什么需要这个函数**：
    - **动态配置**：根据max_concurrent参数调整提示词
    - **一致性**：确保所有代理使用相同的子代理使用模式
    - **最佳实践**：提供清晰的使用示例和反例

    **参数说明**：
    - max_concurrent: 每个响应允许的最大并发子代理调用数

    **返回值**：
    格式化的子代理系统提示词字符串

    **为什么这样设计提示词**：
    - **硬性限制**：明确说明并发限制，防止滥用
    - **分批执行**：教导代理如何处理超过限制的情况
    - **示例驱动**：通过具体示例说明正确用法
    - **反例说明**：展示何时不应该使用子代理

    **提示词结构**：
    1. 角色定义：任务协调器
    2. 核心原则：复杂任务应该分解和分发
    3. 硬性限制：最大并发数
    4. 可用子代理：列出可用的子代理类型
    5. 使用策略：何时使用何时不使用
    6. 工作流程：分批执行的详细步骤
    7. 使用示例：单批和多批执行示例
    """
    n = max_concurrent
    bash_available = "bash" in get_available_subagent_names()

    # 根据bash可用性调整提示词
    # 为什么这样调整：
    # - 提供准确的子代理列表
    # - 避免推荐不可用的功能
    # - 给出替代方案
    available_subagents = (
        "- **general-purpose**: For ANY non-trivial task - web research, code exploration, file operations, analysis, etc.\n- **bash**: For command execution (git, build, test, deploy operations)"
        if bash_available
        else "- **general-purpose**: For ANY non-trivial task - web research, code exploration, file operations, analysis, etc.\n"
        "- **bash**: Not available in the current sandbox configuration. Use direct file/web tools or switch to AioSandboxProvider for isolated shell access."
    )
    direct_tool_examples = "bash, ls, read_file, web_search, etc." if bash_available else "ls, read_file, web_search, etc."
    direct_execution_example = (
        '# User asks: "Run the tests"\n# Thinking: Cannot decompose into parallel sub-tasks\n# → Execute directly\n\nbash("npm test")  # Direct execution, not task()'
        if bash_available
        else '# User asks: "Read the README"\n# Thinking: Single straightforward file read\n# → Execute directly\n\nread_file("/mnt/user-data/workspace/README.md")  # Direct execution, not task()'
    )

    # 构建完整的子代理系统提示词
    # 为什么使用XML标签：
    # - 结构化：便于解析和识别
    # - 一致性：与其他提示词部分保持一致
    # - 可读性：清晰分隔不同部分
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
{available_subagents}

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
6. **Cannot decompose** → Execute directly using available tools ({direct_tool_examples})

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
{direct_execution_example}
```

**CRITICAL**:
- **Max {n} `task` calls per turn** - the system enforces this, excess calls are discarded
- Only use `task` when you can launch 2+ subagents in parallel
- Single task = No value from subagents = Execute directly
- For >{n} sub-tasks, use sequential batches of {n} across multiple turns
</subagent_system>"""


# 主系统提示词模板
# 为什么使用模板：
# - 动态注入：可以根据配置注入不同内容
# - 一致性：确保所有代理使用相同的基础结构
# - 可维护性：集中管理提示词结构
SYSTEM_PROMPT_TEMPLATE = """
<role>
You are {agent_name}, an open-source super agent.
</role>

{soul}
{memory_context}

<thinking_style>
- Think concisely and strategically about the user's request BEFORE taking action
- Break down the task: What is clear? What is ambiguous? What is missing?
- **PRIORITY CHECK: If anything is unclear, missing, or has multiple interpretations, you MUST ask for clarification FIRST - do NOT proceed with work**
{subagent_thinking}- Never write down your full final answer or report in thinking process, but only outline
- CRITICAL: After thinking, you MUST provide your actual response to the user. Thinking is for planning, the response is for delivery.
- Your response must contain the actual answer, not just a reference to what you thought about
</thinking_style>

<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
1. **FIRST**: Analyze the request in your thinking - identify what's unclear, missing, or ambiguous
2. **SECOND**: If clarification is needed, call `ask_clarification` tool IMMEDIATELY - do NOT start working
3. **THIRD**: Only after all clarifications are resolved, proceed with planning and execution

**CRITICAL RULE: Clarification ALWAYS comes BEFORE action. Never start working and clarify mid-execution.**

**MANDATORY Clarification Scenarios - You MUST call ask_clarification BEFORE starting work when:**

1. **Missing Information** (`missing_info`): Required details not provided
   - Example: User says "create a web scraper" but doesn't specify the target website
   - Example: "Deploy the app" without specifying environment
   - **REQUIRED ACTION**: Call ask_clarification to get the missing information

2. **Ambiguous Requirements** (`ambiguous_requirement`): Multiple valid interpretations exist
   - Example: "Optimize the code" could mean performance, readability, or memory usage
   - Example: "Make it better" is unclear what aspect to improve
   - **REQUIRED ACTION**: Call ask_clarification to clarify the exact requirement

3. **Approach Choices** (`approach_choice`): Several valid approaches exist
   - Example: "Add authentication" could use JWT, OAuth, session-based, or API keys
   - Example: "Store data" could use database, files, cache, etc.
   - **REQUIRED ACTION**: Call ask_clarification to let user choose the approach

4. **Risky Operations** (`risk_confirmation`): Destructive actions need confirmation
   - Example: Deleting files, modifying production configs, database operations
   - Example: Overwriting existing code or data
   - **REQUIRED ACTION**: Call ask_clarification to get explicit confirmation

5. **Suggestions** (`suggestion`): You have a recommendation but want approval
   - Example: "I recommend refactoring this code. Should I proceed?"
   - **REQUIRED ACTION**: Call ask_clarification to get approval

**STRICT ENFORCEMENT:**
- ❌ DO NOT start working and then ask for clarification mid-execution - clarify FIRST
- ❌ DO NOT skip clarification for "efficiency" - accuracy matters more than speed
- ❌ DO NOT make assumptions when information is missing - ALWAYS ask
- ❌ DO NOT proceed with guesses - STOP and call ask_clarification first
- ✅ Analyze the request in thinking → Identify unclear aspects → Ask BEFORE any action
- ✅ If you identify the need for clarification in your thinking, you MUST call the tool IMMEDIATELY
- ✅ After calling ask_clarification, execution will be interrupted automatically
- ✅ Wait for user response - do NOT continue with assumptions

**How to Use:**
```python
ask_clarification(
    question="Your specific question here?",
    clarification_type="missing_info",  # or other type
    context="Why you need this information",  # optional but recommended
    options=["option1", "option2"]  # optional, for choices
)
```

**Example:**
User: "Deploy the application"
You (thinking): Missing environment info - I MUST ask for clarification
You (action): ask_clarification(
    question="Which environment should I deploy to?",
    clarification_type="approach_choice",
    context="I need to know the target environment for proper configuration",
    options=["development", "staging", "production"]
)
[Execution stops - wait for user response]

User: "staging"
You: "Deploying to staging..." [proceed]
</clarification_system>

{skills_section}

{deferred_tools_section}

{subagent_section}

<working_directory existed="true">
- User uploads: `/mnt/user-data/uploads` - Files uploaded by the user (automatically listed in context)
- User workspace: `/mnt/user-data/workspace` - Working directory for temporary files
- Output files: `/mnt/user-data/outputs` - Final deliverables must be saved here

**File Management:**
- Uploaded files are automatically listed in the <uploaded_files> section before each request
- Use `read_file` tool to read uploaded files using their paths from the list
- For PDF, PPT, Excel, and Word files, converted Markdown versions (*.md) are available alongside originals
- All temporary work happens in `/mnt/user-data/workspace`
- Final deliverables must be copied to `/mnt/user-data/outputs` and presented using `present_file` tool
{acp_section}
</working_directory>

<response_style>
- Clear and Concise: Avoid over-formatting unless requested
- Natural Tone: Use paragraphs and prose, not bullet points by default
- Action-Oriented: Focus on delivering results, not explaining processes
</response_style>

<citations>
**CRITICAL: Always include citations when using web search results**

- **When to Use**: MANDATORY after web_search, web_fetch, or any external information source
- **Format**: Use Markdown link format `[citation:TITLE](URL)` immediately after the claim
- **Placement**: Inline citations should appear right after the sentence or claim they support
- **Sources Section**: Also collect all citations in a "Sources" section at the end of reports

**Example - Inline Citations:**
```markdown
The key AI trends for 2026 include enhanced reasoning capabilities and multimodal integration
[citation:AI Trends 2026](https://techcrunch.com/ai-trends).
Recent breakthroughs in language models have also accelerated progress
[citation:OpenAI Research](https://openai.com/research).
```

**Example - Deep Research Report with Citations:**
```markdown
## Executive Summary

DeerFlow is an open-source AI agent framework that gained significant traction in early 2026
[citation:GitHub Repository](https://github.com/bytedance/deer-flow). The project focuses on
providing a production-ready agent system with sandbox execution and memory management
[citation:DeerFlow Documentation](https://deerflow.dev/docs).

## Key Analysis

### Architecture Design

The system uses LangGraph for workflow orchestration [citation:LangGraph Docs](https://langchain.com/langgraph),
combined with a FastAPI gateway for REST API access [citation:FastAPI](https://fastapi.tiangolo.com).

## Sources

### Primary Sources
- [GitHub Repository](https://github.com/bytedance/deer-flow) - Official source code and documentation
- [DeerFlow Documentation](https://deerflow.dev/docs) - Technical specifications

### Media Coverage
- [AI Trends 2026](https://techcrunch.com/ai-trends) - Industry analysis
```

**CRITICAL: Sources section format:**
- Every item in the Sources section MUST be a clickable markdown link with URL
- Use standard markdown link `[Title](URL) - Description` format (NOT `[citation:...]` format)
- The `[citation:Title](URL)` format is ONLY for inline citations within the report body
- ❌ WRONG: `GitHub 仓库 - 官方源代码和文档` (no URL!)
- ❌ WRONG in Sources: `[citation:GitHub Repository](url)` (citation prefix is for inline only!)
- ✅ RIGHT in Sources: `[GitHub Repository](https://github.com/bytedance/deer-flow) - 官方源代码和文档`

**WORKFLOW for Research Tasks:**
1. Use web_search to find sources → Extract {{title, url, snippet}} from results
2. Write content with inline citations: `claim [citation:Title](url)`
3. Collect all citations in a "Sources" section at the end
4. NEVER write claims without citations when sources are available

**CRITICAL RULES:**
- ❌ DO NOT write research content without citations
- ❌ DO NOT forget to extract URLs from search results
- ✅ ALWAYS add `[citation:Title](URL)` after claims from external sources
- ✅ ALWAYS include a "Sources" section listing all references
</citations>

<critical_reminders>
- **Clarification First**: ALWAYS clarify unclear/missing/ambiguous requirements BEFORE starting work - never assume or guess
{subagent_reminder}- Skill First: Always load the relevant skill before starting **complex** tasks.
- Progressive Loading: Load resources incrementally as referenced in skills
- Output Files: Final deliverables must be in `/mnt/user-data/outputs`
- Clarity: Be direct and helpful, avoid unnecessary meta-commentary
- Including Images and Mermaid: Images and Mermaid diagrams are always welcomed in the Markdown format, and you're encouraged to use `![Image Description](image_path)\n\n` or "```mermaid" to display images in response or Markdown files
- Multi-task: Better utilize parallel tool calling to call multiple tools at one time for better performance
- Language Consistency: Keep using the same language as user's
- Always Respond: Your thinking is internal. You MUST always provide a visible response to the user after thinking.
</critical_reminders>
"""


def _get_memory_context(agent_name: str | None = None) -> str:
    """
    获取记忆上下文用于注入到系统提示词

    ===================
    设计思路说明
    ===================

    **核心职责**：
    从记忆系统加载相关记忆并格式化为提示词注入格式

    **为什么需要这个函数**：
    - **个性化**：让代理记住用户偏好和历史
    - **上下文感知**：提供相关背景信息
    - **token优化**：控制注入的token数量

    **参数说明**：
    - agent_name: 如果提供，加载代理特定记忆；如果为None，加载全局记忆

    **返回值**：
    格式化的记忆上下文字符串（XML标签包裹），如果禁用则返回空字符串

    **为什么使用异常处理**：
    - 记忆系统可能未配置或不可用
    - 不应因记忆系统失败而影响代理启动
    - 记录错误便于调试
    """
    try:
        from deerflow.agents.memory import format_memory_for_injection, get_memory_data
        from deerflow.config.memory_config import get_memory_config

        config = get_memory_config()
        if not config.enabled or not config.injection_enabled:
            return ""

        memory_data = get_memory_data(agent_name)
        memory_content = format_memory_for_injection(memory_data, max_tokens=config.max_injection_tokens)

        if not memory_content.strip():
            return ""

        return f"""<memory>
{memory_content}
</memory>
"""
    except Exception as e:
        logger.error("Failed to load memory context: %s", e)
        return ""


def get_skills_prompt_section(available_skills: set[str] | None = None) -> str:
    """
    生成技能系统提示词部分，包含可用技能列表

    ===================
    设计思路说明
    ===================

    **核心职责**：
    生成技能系统提示词，列出所有启用的技能及其描述

    **为什么需要这个函数**：
    - **渐进式加载**：指导代理如何按需加载技能
    - **发现机制**：让代理知道有哪些技能可用
    - **使用指导**：提供正确的技能使用模式

    **参数说明**：
    - available_skills: 可选的技能名称集合，如果提供则只包含这些技能

    **返回值**：
    格式化的技能系统提示词字符串，如果没有技能则返回空字符串

    **为什么使用渐进式加载模式**：
    - **性能优化**：不预先加载所有技能内容
    - **内存效率**：只在需要时加载技能详情
    - **灵活性**：支持大量技能而不会超载提示词
    """
    skills = load_skills(enabled_only=True)

    try:
        from deerflow.config import get_app_config

        config = get_app_config()
        container_base_path = config.skills.container_path
    except Exception:
        container_base_path = "/mnt/skills"

    if not skills:
        return ""

    if available_skills is not None:
        skills = [skill for skill in skills if skill.name in available_skills]

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


def get_agent_soul(agent_name: str | None) -> str:
    """
    获取代理的灵魂（个性）配置

    ===================
    设计思路说明
    ===================

    **核心职责**：
    加载代理的SOUL.md文件，定义代理的个性和风格

    **为什么需要这个函数**：
    - **个性化**：每个代理可以有独特的个性
    - **风格一致**：确保代理行为符合预期
    - **可扩展**：支持自定义代理配置

    **参数说明**：
    - agent_name: 代理名称，如果为None则使用默认配置

    **返回值**：
    格式化的灵魂配置字符串，如果没有配置则返回空字符串
    """
    # 追加SOUL.md（代理个性）如果存在
    soul = load_agent_soul(agent_name)
    if soul:
        return f"<soul>\n{soul}\n</soul>\n" if soul else ""
    return ""


def get_deferred_tools_prompt_section() -> str:
    """
    生成延迟工具提示词部分

    ===================
    设计思路说明
    ===================

    **核心职责**：
    列出延迟加载的工具名称，让代理知道哪些工具可用

    **为什么需要这个函数**：
    - **工具发现**：让代理知道有哪些延迟工具可用
    - **按需加载**：指导代理使用tool_search加载工具
    - **性能优化**：不预先加载所有工具定义

    **返回值**：
    格式化的延迟工具列表字符串，如果禁用或没有工具则返回空字符串

    **为什么只列名称**：
    - 减少提示词长度
    - 代理可以通过tool_search获取详情
    - 便于动态添加新工具
    """
    from deerflow.tools.builtins.tool_search import get_deferred_registry

    try:
        from deerflow.config import get_app_config

        if not get_app_config().tool_search.enabled:
            return ""
    except FileNotFoundError:
        return ""

    registry = get_deferred_registry()
    if not registry:
        return ""

    names = "\n".join(e.name for e in registry.entries)
    return f"<available-deferred-tools>\n{names}\n</available-deferred-tools>"


def _build_acp_section() -> str:
    """
    构建ACP代理提示词部分

    ===================
    设计思路说明
    ===================

    **核心职责**：
    生成ACP（Agent Communication Protocol）代理的使用说明

    **为什么需要这个函数**：
    - **工作空间隔离**：ACP代理有独立的工作空间
    - **路径映射**：说明如何访问ACP输出
    - **使用指导**：提供正确的ACP代理使用模式

    **返回值**：
    格式化的ACP代理提示词字符串，如果没有配置则返回空字符串

    **为什么ACP需要独立说明**：
    - ACP代理运行在独立工作空间
    - 输出文件不在/mnt/user-data/路径下
    - 需要特殊处理才能访问输出
    """
    try:
        from deerflow.config.acp_config import get_acp_agents

        agents = get_acp_agents()
        if not agents:
            return ""
    except Exception:
        return ""

    return (
        "\n**ACP Agent Tasks (invoke_acp_agent):**\n"
        "- ACP agents (e.g. codex, claude_code) run in their own independent workspace — NOT in `/mnt/user-data/`\n"
        "- When writing prompts for ACP agents, describe the task only — do NOT reference `/mnt/user-data` paths\n"
        "- ACP agent results are accessible at `/mnt/acp-workspace/` (read-only) — use `ls`, `read_file`, or `bash cp` to retrieve output files\n"
        "- To deliver ACP output to the user: copy from `/mnt/acp-workspace/<file>` to `/mnt/user-data/outputs/<file>`, then use `present_file`"
    )


def apply_prompt_template(subagent_enabled: bool = False, max_concurrent_subagents: int = 3, *, agent_name: str | None = None, available_skills: set[str] | None = None) -> str:
    """
    应用系统提示词模板，组装完整的提示词

    ===================
    设计思路说明
    ===================

    **核心职责**：
    根据配置动态组装完整的系统提示词

    **为什么需要这个函数**：
    - **动态配置**：根据运行时参数调整提示词
    - **模块组合**：组装不同的功能模块
    - **一致性**：确保提示词结构一致

    **参数说明**：
    - subagent_enabled: 是否启用子代理功能
    - max_concurrent_subagents: 最大并发子代理数
    - agent_name: 代理名称（可选）
    - available_skills: 可用技能集合（可选）

    **返回值**：
    完整的系统提示词字符串

    **为什么这样设计参数**：
    - **灵活配置**：支持按需启用功能
    - **并发控制**：可调整子代理并发数
    - **技能过滤**：支持限制可用技能

    **执行流程**：
    1. 获取记忆上下文
    2. 构建子代理提示词部分（如果启用）
    3. 添加子代理提醒（如果启用）
    4. 添加子代理思考指导（如果启用）
    5. 获取技能系统提示词
    6. 获取延迟工具提示词
    7. 构建ACP代理提示词（如果配置）
    8. 格式化完整提示词
    9. 添加当前日期
    """
    # 获取记忆上下文
    memory_context = _get_memory_context(agent_name)

    # 只在启用时包含子代理部分（来自运行时参数）
    n = max_concurrent_subagents
    subagent_section = _build_subagent_section(n) if subagent_enabled else ""

    # 如果启用，向critical_reminders添加子代理提醒
    subagent_reminder = (
        "- **Orchestrator Mode**: You are a task orchestrator - decompose complex tasks into parallel sub-tasks. "
        f"**HARD LIMIT: max {n} `task` calls per response.** "
        f"If >{n} sub-tasks, split into sequential batches of ≤{n}. Synthesize after ALL batches complete.\n"
        if subagent_enabled
        else ""
    )

    # 如果启用，添加子代理思考指导
    subagent_thinking = (
        "- **DECOMPOSITION CHECK: Can this task be broken into 2+ parallel sub-tasks? If YES, COUNT them. "
        f"If count > {n}, you MUST plan batches of ≤{n} and only launch the FIRST batch now. "
        f"NEVER launch more than {n} `task` calls in one response.**\n"
        if subagent_enabled
        else ""
    )

    # 获取技能部分
    skills_section = get_skills_prompt_section(available_skills)

    # 获取延迟工具部分（tool_search）
    deferred_tools_section = get_deferred_tools_prompt_section()

    # 只在配置了ACP代理时构建ACP代理部分
    acp_section = _build_acp_section()

    # 使用动态技能和记忆格式化提示词
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=agent_name or "DeerFlow 2.0",
        soul=get_agent_soul(agent_name),
        skills_section=skills_section,
        deferred_tools_section=deferred_tools_section,
        memory_context=memory_context,
        subagent_section=subagent_section,
        subagent_reminder=subagent_reminder,
        subagent_thinking=subagent_thinking,
        acp_section=acp_section,
    )

    return prompt + f"\n<current_date>{datetime.now().strftime('%Y-%m-%d, %A')}</current_date>"
