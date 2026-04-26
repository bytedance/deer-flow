"""
记忆系统提示词模板模块

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 提供记忆更新和注入的提示词模板
2. 定义记忆数据的结构和格式
3. 实现token计数和格式化功能

**核心设计模式**：
- 模板模式：使用字符串模板构建提示词
- 策略模式：根据token预算动态调整内容
- 工具模式：提供各种格式化和转换函数

**为什么这样设计**：
- **一致性**：确保所有记忆操作使用相同的格式
- **优化**：准确控制token使用，避免超限
- **灵活性**：支持不同类型的记忆数据

**模块职责**：
1. 定义记忆更新提示词模板
2. 定义事实提取提示词模板
3. 实现记忆格式化函数
4. 实现token计数功能
5. 实现对话格式化功能
"""

import math
import re
from typing import Any

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# 记忆更新提示词模板
# 为什么需要这样详细的模板：
# - 确保LLM理解记忆更新的目标和要求
# - 定义清晰的数据结构和格式
# - 提供具体的示例和指导原则
MEMORY_UPDATE_PROMPT = """You are a memory management system. Your task is to analyze a conversation and update the user's memory profile.

Current Memory State:
<current_memory>
{current_memory}
</current_memory>

New Conversation to Process:
<conversation>
{conversation}
</conversation>

Instructions:
1. Analyze the conversation for important information about the user
2. Extract relevant facts, preferences, and context with specific details (numbers, names, technologies)
3. Update the memory sections as needed following the detailed length guidelines below

Memory Section Guidelines:

**User Context** (Current state - concise summaries):
- workContext: Professional role, company, key projects, main technologies (2-3 sentences)
  Example: Core contributor, project names with metrics (16k+ stars), technical stack
- personalContext: Languages, communication preferences, key interests (1-2 sentences)
  Example: Bilingual capabilities, specific interest areas, expertise domains
- topOfMind: Multiple ongoing focus areas and priorities (3-5 sentences, detailed paragraph)
  Example: Primary project work, parallel technical investigations, ongoing learning/tracking
  Include: Active implementation work, troubleshooting issues, market/research interests
  Note: This captures SEVERAL concurrent focus areas, not just one task

**History** (Temporal context - rich paragraphs):
- recentMonths: Detailed summary of recent activities (4-6 sentences or 1-2 paragraphs)
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
- Include proper nouns (company names, project names, technology names)
- Preserve technical terminology and version numbers
- Categories:
  * preference: Tools, styles, approaches user prefers/dislikes
  * knowledge: Specific expertise, technologies mastered, domain knowledge
  * context: Background facts (job title, projects, locations, languages)
  * behavior: Working patterns, communication habits, problem-solving approaches
  * goal: Stated objectives, learning targets, project ambitions
- Confidence levels:
  * 0.9-1.0: Explicitly stated facts ("I work on X", "My role is Y")
  * 0.7-0.8: Strongly implied from actions/discussions
  * 0.5-0.6: Inferred patterns (use sparingly, only for clear patterns)

**What Goes Where**:
- workContext: Current job, active projects, primary tech stack
- personalContext: Languages, personality, interests outside direct work tasks
- topOfMind: Multiple ongoing priorities and focus areas user cares about recently (gets updated most frequently)
  Should capture 3-5 concurrent themes: main work, side explorations, learning/tracking interests
- recentMonths: Detailed account of recent technical explorations and work
- earlierContext: Patterns from slightly older interactions still relevant
- longTermBackground: Unchanging foundational facts about the user

**Multilingual Content**:
- Preserve original language for proper nouns and company names
- Keep technical terms in their original form (DeepSeek, LangGraph, etc.)
- Note language capabilities in personalContext

Output Format (JSON):
{{
  "user": {{
    "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1", "fact_id_2"]
}}

Important Rules:
- Only set shouldUpdate=true if there's meaningful new information
- Follow length guidelines: workContext/personalContext are concise (1-3 sentences), topOfMind and history sections are detailed (paragraphs)
- Include specific metrics, version numbers, and proper nouns in facts
- Only add facts that are clearly stated (0.9+) or strongly implied (0.7+)
- Remove facts that are contradicted by new information
- When updating topOfMind, integrate new focus areas while removing completed/abandoned ones
  Keep 3-5 concurrent focus themes that are still active and relevant
- For history sections, integrate new information chronologically into appropriate time period
- Preserve technical accuracy - keep exact names of technologies, companies, projects
- Focus on information useful for future interactions and personalization
- IMPORTANT: Do NOT record file upload events in memory. Uploaded files are
  session-specific and ephemeral — they will not be accessible in future sessions.
  Recording upload events causes confusion in subsequent conversations.

Return ONLY valid JSON, no explanation or markdown."""

# 事实提取提示词模板
# 为什么需要单独的模板：
# - 从单条消息中快速提取事实
# - 用于实时记忆更新
# - 比完整更新更轻量
FACT_EXTRACTION_PROMPT = """Extract factual information about the user from this message.

Message:
{message}

Extract facts in this JSON format:
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal", "confidence": 0.0-1.0 }}
  ]
}}

Categories:
- preference: User preferences (likes/dislikes, styles, tools)
- knowledge: User's expertise or knowledge areas
- context: Background context (location, job, projects)
- behavior: Behavioral patterns
- goal: User's goals or objectives

Rules:
- Only extract clear, specific facts
- Confidence should reflect certainty (explicit statement = 0.9+, implied = 0.6-0.8)
- Skip vague or temporary information

Return ONLY valid JSON."""


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """
    使用tiktoken计算文本的token数

    ===================
    设计思路说明
    ===================

    **核心职责**：
    准确计算文本的token数量，用于控制提示词长度

    **为什么需要这个函数**：
    - **精确控制**：准确控制注入到提示词的token数量
    - **成本优化**：避免超出token预算导致额外成本
    - **性能优化**：确保提示词在模型限制内

    **参数说明**：
    - text: 要计算token的文本
    - encoding_name: 使用的编码（默认cl100k_base，适用于GPT-4/3.5）

    **返回值**：
    文本的token数量

    **为什么有fallback机制**：
    - tiktoken可能未安装
    - 使用字符数/4作为粗略估计
    - 确保函数总是可用
    """
    if not TIKTOKEN_AVAILABLE:
        # 如果tiktoken不可用，回退到基于字符的估计
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        # 错误时回退到字符估计
        return len(text) // 4


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    """
    将类置信度值强制转换为[0, 1]范围内的浮点数

    ===================
    设计思路说明
    ===================

    **核心职责**：
    安全地将各种类型的值转换为有效的置信度浮点数

    **为什么需要这个函数**：
    - **类型安全**：处理各种可能的输入类型
    - **边界保护**：确保值在有效范围内
    - **NaN处理**：防止非有限值破坏排序

    **参数说明**：
    - value: 要转换的值
    - default: 当值无效时使用的默认值

    **返回值**：
    在[0, 1]范围内的浮点数

    **为什么这样处理NaN**：
    - NaN不能正确比较或排序
    - 使用默认值而非NaN
    - 防止排序异常
    """
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, default))
    if not math.isfinite(confidence):
        return max(0.0, min(1.0, default))
    return max(0.0, min(1.0, confidence))


def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
    """
    格式化记忆数据用于注入到系统提示词

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将记忆数据转换为适合注入到系统提示词的格式

    **为什么需要这个函数**：
    - **token优化**：确保注入内容在token预算内
    - **优先级排序**：高置信度事实优先
    - **结构化**：格式化为易于阅读的文本

    **参数说明**：
    - memory_data: 记忆数据字典
    - max_tokens: 最大token数（通过tiktoken精确计数）

    **返回值**：
    格式化的记忆字符串，用于系统提示词注入

    **为什么这样设计格式化逻辑**：
    - **分段计算**：逐个添加事实，避免重复token化
    - **优先级排序**：按置信度排序，优先包含高置信度事实
    - **精确控制**：准确计算token数，避免超限

    **执行流程**：
    1. 格式化用户上下文（工作、个人、当前关注）
    2. 格式化历史（最近、较早、长期背景）
    3. 按置信度排序事实
    4. 逐个添加事实直到达到token预算
    5. 如果超出限制，截断到合适长度
    """
    if not memory_data:
        return ""

    sections = []

    # 格式化用户上下文
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

    # 格式化历史
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

    # 格式化事实（按置信度排序；在token预算允许内包含尽可能多）
    facts_data = memory_data.get("facts", [])
    if isinstance(facts_data, list) and facts_data:
        ranked_facts = sorted(
            (f for f in facts_data if isinstance(f, dict) and isinstance(f.get("content"), str) and f.get("content").strip()),
            key=lambda fact: _coerce_confidence(fact.get("confidence"), default=0.0),
            reverse=True,
        )

        # 计算现有部分的token计数一次，然后为每个事实行增量计算
        # 避免完整的字符串重新token化
        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens(base_text) if base_text else 0
        # 计算现有部分和事实部分之间的分隔符的token
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

            # 每个额外行前面有一个换行符（除了第一个）
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

    # 使用tiktoken进行精确的token计数
    token_count = _count_tokens(result)
    if token_count > max_tokens:
        # 截断以适应token限制
        # 基于token比率估计要删除的字符数
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)  # 95%以留出余量
        result = result[:target_chars] + "\n..."

    return result


def format_conversation_for_update(messages: list[Any]) -> str:
    """
    格式化对话消息用于记忆更新提示词

    ===================
    设计思路说明
    ===================

    **核心职责**：
    将消息列表转换为适合LLM分析的文本格式

    **为什么需要这个函数**：
    - **标准化**：统一消息格式
    - **清理**：移除不相关的内容（如文件上传标签）
    - **简化**：截断过长的消息

    **参数说明**：
    - messages: 对话消息列表

    **返回值**：
    格式化的对话字符串

    **为什么需要清理文件上传标签**：
    - 文件路径是会话特定的
    - 不会在未来的会话中可访问
    - 记录这些信息会造成混淆
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

        # 处理可能是列表的内容（多模态）
        if isinstance(content, list):
            text_parts = []
            for p in content:
                if isinstance(p, str):
                    text_parts.append(p)
                elif isinstance(p, dict):
                    text_val = p.get("text")
                    if isinstance(text_val, str):
                        text_parts.append(text_val)
            content = " ".join(text_parts) if text_parts else str(content)

        # 从人类消息中去除uploaded_files标签
        # 避免将短暂的文件路径信息持久化到长期记忆中
        # 如果去除后没有剩余内容，则跳过该轮（仅上传消息）
        if role == "human":
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue

        # 截断非常长的消息
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
