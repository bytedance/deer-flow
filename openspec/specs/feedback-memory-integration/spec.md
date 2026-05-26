# Feedback Memory Integration

## ADDED Requirements

### Requirement: Create memory fact from applied improvement

When an improvement suggestion is applied via the admin dashboard, the system SHALL create a memory fact in the agent memory system by calling an extended version of `create_memory_fact()` that accepts a custom `source` parameter. The fact SHALL have source="feedback_loop", category="improvement", and confidence=0.9. The fact content SHALL be derived from the suggestion text and evidence.

#### Scenario: Applied suggestion creates memory fact with custom source

- **WHEN** an admin applies improvement suggestion "Review data validation logic in ai-report--daily agent" with target="agent:ai-report--daily"
- **THEN** a memory fact is created with content="ai-report--daily agent: review data validation logic — 12 negative feedback entries cited inaccurate_data", source="feedback_loop", category="improvement", confidence=0.9

#### Scenario: Memory fact enters standard injection pipeline

- **WHEN** a memory fact is created from an applied improvement
- **THEN** the fact is included in the next agent system prompt injection alongside other memory facts, subject to the standard max_injection_tokens limit

### Requirement: Memory fact deduplication with existing facts

Improvement-derived memory facts SHALL be deduplicated against existing memory facts using the same content-normalization logic as the memory updater (whitespace-trimmed comparison). If a similar fact already exists, the existing fact's confidence SHALL be boosted instead of creating a duplicate.

#### Scenario: Duplicate improvement fact not created

- **WHEN** an improvement suggestion is applied but a memory fact with identical content already exists
- **THEN** no new fact is created; instead, the existing fact's confidence is increased by 0.1 (capped at 1.0) and its updatedAt is refreshed

### Requirement: Improvement facts respect memory limits

Improvement-derived memory facts SHALL count toward the configured max_facts limit. When the limit is reached, improvement facts with the lowest confidence are evicted first, same as other fact categories.

#### Scenario: Max facts reached with improvement facts

- **WHEN** the memory store is at max_facts=100 and a new improvement fact with confidence=0.9 is added
- **THEN** the fact with the lowest confidence (whether improvement or other category) is evicted to make room

### Requirement: Improvement fact provenance tracking

Each improvement-derived memory fact SHALL retain a reference to the source suggestion ID so administrators can trace which feedback loop cycle produced which behavioral change.

#### Scenario: Trace fact back to suggestion

- **WHEN** an administrator queries memory and sees a fact with source="feedback_loop"
- **THEN** the fact metadata includes suggestion_id referencing the original ImprovementSuggestion record

### Requirement: Extend create_memory_fact API

The `create_memory_fact()` function in `deerflow.agents.memory.updater` SHALL accept an optional `source` parameter (default "manual" for backward compatibility). When provided, this value SHALL be stored in the fact's `source` field instead of the hardcoded "manual" value.

#### Scenario: Backward compatibility preserved

- **WHEN** existing code calls `create_memory_fact(content="...", category="context")` without a source parameter
- **THEN** the fact is created with source="manual" as before, maintaining backward compatibility

#### Scenario: Custom source accepted

- **WHEN** the insights system calls `create_memory_fact(content="...", category="improvement", confidence=0.9, source="feedback_loop")`
- **THEN** the fact is created with source="feedback_loop" in the source field
