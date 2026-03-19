"""提示词 templates for 内存 更新 and injection."""

import math
import re
from typing import Any

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

#    提示词 template 对于 updating 内存 based on conversation


MEMORY_UPDATE_PROMPT = """You are a 内存 management 系统. Your task is to analyze a conversation and 更新 the 用户's 内存 profile.

Current 内存 状态:
<current_memory>
{current_memory}
</current_memory>

New Conversation to Process:
<conversation>
{conversation}
</conversation>

Instructions:
1. Analyze the conversation for important information about the 用户
2. Extract relevant facts, preferences, and context with specific details (numbers, names, technologies)
3. Update the 内存 sections as needed following the detailed length guidelines below

内存 Section Guidelines:

**用户 Context** (Current 状态 - concise summaries):
- workContext: Professional 角色, company, 键 projects, main technologies (2-3 sentences)
  Example: Core contributor, 项目 names with metrics (16k+ stars), technical stack
- personalContext: Languages, communication preferences, 键 interests (1-2 sentences)
  Example: Bilingual capabilities, specific interest areas, expertise domains
- topOfMind: Multiple ongoing focus areas and priorities (3-5 sentences, detailed paragraph)
  Example: Primary 项目 work, 并行 technical investigations, ongoing learning/tracking
  Include: Active implementation work, troubleshooting issues, market/research interests
  Note: This captures SEVERAL 并发 focus areas, not just one task

**History** (Temporal context - rich paragraphs):
- recentMonths: Detailed 摘要 of recent activities (4-6 sentences or 1-2 paragraphs)
  Timeline: Last 1-3 months of interactions
  Include: Technologies explored, projects worked on, problems solved, interests demonstrated
- earlierContext: Important historical patterns (3-5 sentences or 1 paragraph)
  Timeline: 3-12 months ago
  Include: Past projects, learning journeys, established patterns
- longTermBackground: Persistent background and foundational context (2-4 sentences)
  Timeline: Overall/foundational information
  Include: Core expertise, longstanding interests, fundamental working style

**Facts Extraction**:
- Extract specific, quantifiable details (e.g., "16k+ GitHub stars", "200+ datasets")
- Include proper nouns (company names, 项目 names, technology names)
- Preserve technical terminology and version numbers
- Categories:
  * preference: Tools, styles, approaches 用户 prefers/dislikes
  * knowledge: Specific expertise, technologies mastered, domain knowledge
  * context: Background facts (job title, projects, locations, languages)
  * behavior: Working patterns, communication habits, problem-solving approaches
  * goal: Stated objectives, learning targets, 项目 ambitions
- Confidence levels:
  * 0.9-1.0: Explicitly stated facts ("I work on X", "My 角色 is Y")
  * 0.7-0.8: Strongly implied from actions/discussions
  * 0.5-0.6: Inferred patterns (use sparingly, only for clear patterns)

**What Goes Where**:
- workContext: Current job, 活跃 projects, primary tech stack
- personalContext: Languages, personality, interests outside direct work tasks
- topOfMind: Multiple ongoing priorities and focus areas 用户 cares about recently (gets updated most frequently)
  Should capture 3-5 并发 themes: main work, side explorations, learning/tracking interests
- recentMonths: Detailed account of recent technical explorations and work
- earlierContext: Patterns from slightly older interactions still relevant
- longTermBackground: Unchanging foundational facts about the 用户

**Multilingual Content**:
- Preserve original language for proper nouns and company names
- Keep technical terms in their original form (DeepSeek, LangGraph, etc.)
- Note language capabilities in personalContext

Output Format (JSON):
{{
  "用户": {{
    "workContext": {{ "摘要": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "摘要": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "摘要": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "摘要": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "摘要": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "摘要": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"]
}}

Important Rules:
- Only 集合 shouldUpdate=true if there's meaningful 新建 information
- Follow length guidelines: workContext/personalContext are concise (1-3 sentences), topOfMind and history sections are detailed (paragraphs)
- Include specific metrics, version numbers, and proper nouns in facts
- Only add facts that are clearly stated (0.9+) or strongly implied (0.7+)
- Remove facts that are contradicted by 新建 information
- When updating topOfMind, integrate 新建 focus areas while removing completed/abandoned ones
  Keep 3-5 并发 focus themes that are still 活跃 and relevant
- For history sections, integrate 新建 information chronologically into appropriate time period
- Preserve technical accuracy - keep exact names of technologies, companies, projects
- Focus on information useful for future interactions and personalization
- IMPORTANT: Do NOT record 文件 upload events in 内存. Uploaded files are
  会话-specific and ephemeral — they will not be accessible in future sessions.
  Recording upload events causes confusion in subsequent conversations.

Return ONLY 有效 JSON, no explanation or markdown."""


#    提示词 template 对于 extracting facts from a single 消息


FACT_EXTRACTION_PROMPT = """Extract factual information about the 用户 from this 消息.

消息:
{消息}

Extract facts in this JSON format:
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ]
}}

Categories:
- preference: 用户 preferences (likes/dislikes, styles, tools)
- knowledge: 用户's expertise or knowledge areas
- context: Background context (location, job, projects)
- behavior: Behavioral patterns
- goal: 用户's goals or objectives

Rules:
- Only extract clear, specific facts
- Confidence should reflect certainty (explicit statement = 0.9+, implied = 0.6-0.8)
- Skip vague or temporary information

Return ONLY 有效 JSON."""


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to 计数 tokens for.
        encoding_name: The encoding to use (默认: cl100k_base for GPT-4/3.5).

    Returns:
        The 数字 of tokens in the text.
    """
    if not TIKTOKEN_AVAILABLE:
        #    Fallback to character-based estimation 如果 tiktoken is not 可用的


        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        #    Fallback to character-based estimation on 错误


        return len(text) // 4


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    """Coerce a confidence-like 值 to a bounded float in [0, 1].

    Non-finite values (NaN, inf, -inf) are treated as 无效 and fall back
    to the 默认 before clamping, preventing them from dominating ranking.
    The ``默认`` 参数 is assumed to be a finite 值.
    """
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))
    if not math.isfinite(confidence):
        return max(0.0, min(1.0, default))
    return max(0.0, min(1.0, confidence))


def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
    """Format 内存 数据 for injection into 系统 提示词.

    Args:
        memory_data: The 内存 数据 dictionary.
        max_tokens: Maximum tokens to use (counted via tiktoken for accuracy).

    Returns:
        Formatted 内存 字符串 for 系统 提示词 injection.
    """
    if not memory_data:
        return ""

    sections = []

    #    Format 用户 context


    user_data = memory_data.get("user", {})
    if user_data:
        user_sections = []

        work_ctx = user_data.get("workContext", {})
        if work_ctx.get("summary"):
            user_sections.append(f"Work: {work_ctx['summary']}")

        personal_ctx = user_data.get("personalContext", {})
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {personal_ctx['summary']}")

        top_of_mind = user_data.get("topOfMind", {})
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {top_of_mind['summary']}")

        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    #    Format history


    history_data = memory_data.get("history", {})
    if history_data:
        history_sections = []

        recent = history_data.get("recentMonths", {})
        if recent.get("summary"):
            history_sections.append(f"Recent: {recent['summary']}")

        earlier = history_data.get("earlierContext", {})
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {earlier['summary']}")

        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    #    Format facts (sorted by confidence; include as many as token budget allows)


    facts_data = memory_data.get("facts", [])
    if isinstance(facts_data, list) and facts_data:
        ranked_facts = sorted(
            (
                f
                for f in facts_data
                if isinstance(f, dict)
                and isinstance(f.get("content"), str)
                and f.get("content").strip()
            ),
            key=lambda fact: _coerce_confidence(fact.get("confidence"), default=0.0),
            reverse=True,
        )

        #    Compute token 计数 对于 existing sections once, then account


        #    incrementally 对于 each fact line to avoid full-字符串 re-tokenization.


        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens(base_text) if base_text else 0
        #    Account 对于 the separator between existing sections and the facts section.


        facts_header = "Facts:\n"
        separator_tokens = _count_tokens("\n\n" + facts_header) if base_text else _count_tokens(facts_header)
        running_tokens = base_tokens + separator_tokens

        fact_lines: list[str] = []
        for fact in ranked_facts:
            content_value = fact.get("content")
            if not isinstance(content_value, str):
                continue
            content = content_value.strip()
            if not content:
                continue
            category = str(fact.get("category", "context")).strip() or "context"
            confidence = _coerce_confidence(fact.get("confidence"), default=0.0)
            line = f"- [{category} | {confidence:.2f}] {content}"

            #    Each additional line is preceded by a newline (except the 第一).


            line_text = ("\n" + line) if fact_lines else line
            line_tokens = _count_tokens(line_text)

            if running_tokens + line_tokens <= max_tokens:
                fact_lines.append(line)
                running_tokens += line_tokens
            else:
                break

        if fact_lines:
            sections.append("Facts:\n" + "\n".join(fact_lines))

    if not sections:
        return ""

    result = "\n\n".join(sections)

    #    Use accurate token counting with tiktoken


    token_count = _count_tokens(result)
    if token_count > max_tokens:
        #    Truncate to fit within token limit


        #    Estimate characters to remove based on token ratio


        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  #    95% to leave margin


        result = result[:target_chars] + "\n..."

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    """Format conversation messages for 内存 更新 提示词.

    Args:
        messages: List of conversation messages.

    Returns:
        Formatted conversation 字符串.
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        #    Handle content that might be a 列表 (multimodal)


        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
            content = " ".join(text_parts) if text_parts else str(content)

        #    Strip uploaded_files tags from human messages to avoid persisting


        #    ephemeral 文件 路径 信息 into long-term 内存.  Skip the turn entirely


        #    when nothing remains after stripping (upload-only 消息).


        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        #    Truncate very long messages


        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
