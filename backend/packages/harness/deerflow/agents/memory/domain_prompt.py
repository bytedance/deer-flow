"""Prompt templates for domain memory extraction."""

DOMAIN_FACT_EXTRACTION_PROMPT = """You are a domain knowledge extraction system. Your task is to identify domain-specific facts from a conversation.

Conversation:
<conversation>
{conversation}
</conversation>

Instructions:
1. Identify facts about specific entities (equipment, systems, processes, components)
2. For each fact, determine the domain category and the entity it refers to
3. Extract only concrete, verifiable facts — not opinions or speculation
4. Assign a confidence score based on how explicitly the fact is stated

Domain Categories:
- equipment: Physical machines, devices, instruments (pumps, motors, sensors, valves)
- process: Operational procedures, workflows, sequences
- system: Larger assemblies or subsystems (HVAC, electrical, control systems)
- material: Substances, chemicals, raw materials
- location: Physical locations, facilities, zones
- specification: Technical parameters, thresholds, limits

Entity Recognition:
- Extract the specific entity name (e.g., "Pump A", "Reactor #1", "Building 3 HVAC")
- Use the exact name as mentioned in the conversation
- If an entity is referred to by pronoun only ("it", "that pump"), try to resolve it from context

Output Format (JSON):
{{
  "facts": [
    {{
      "content": "The fact text",
      "domain": "equipment|process|system|material|location|specification",
      "entity_id": "Entity Name",
      "confidence": 0.0-1.0
    }}
  ]
}}

Confidence Guidelines:
- 0.9-1.0: Explicitly stated fact ("Pump A has a flow rate of 500 GPM")
- 0.7-0.8: Strongly implied from context
- 0.5-0.6: Inferred from discussion (use sparingly)

Examples:
- User: "The main feed pump is showing high vibration levels"
  -> {{ "content": "Main feed pump showing high vibration levels", "domain": "equipment", "entity_id": "Main Feed Pump", "confidence": 0.95 }}

- User: "We changed the operating procedure for reactor startup"
  -> {{ "content": "Operating procedure changed for reactor startup", "domain": "process", "entity_id": "Reactor", "confidence": 0.9 }}

- User: "The HVAC system in Building 3 needs maintenance"
  -> {{ "content": "HVAC system in Building 3 needs maintenance", "domain": "system", "entity_id": "Building 3 HVAC", "confidence": 0.9 }}

Rules:
- Only extract facts that are clearly about a specific entity
- Skip vague statements without identifiable entities
- Preserve technical terminology exactly
- Do NOT extract personal preferences or opinions
- Do NOT extract facts about the user themselves (those belong in User Memory)

Return ONLY valid JSON, no explanation or markdown."""


def format_conversation_for_domain(messages: list) -> str:
    """Format conversation messages for domain extraction prompt.

    Args:
        messages: List of conversation messages.

    Returns:
        Formatted conversation string.
    """
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))

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

        if len(str(content)) > 500:
            content = str(content)[:500] + "..."

        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
