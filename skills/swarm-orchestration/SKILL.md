# Swarm Orchestration — Multi-Agent Task Decomposition & Coordination

This skill teaches any DeerFlow agent to decompose complex tasks into dependency graphs, dispatch sub-agents in parallel, handle failures, and merge results.

## When To Use This Skill

You need swarm orchestration when:

- A single prompt would be too large or complex for one agent pass
- The task requires expertise from multiple domains
- Different parts of the task can run in parallel
- You want structured failure recovery instead of all-or-nothing

## Core Principles

1. **Decompose until each sub-task fits one agent's capability.** If an agent can finish in under 30 seconds, it is too small. If an agent would struggle to finish, it is too large.
2. **Parallelize at every opportunity.** Every sequential dependency is a bottleneck.
3. **Design for failure, not success.** Assume every agent call may fail. Build retry, fallback, and timeout into every sub-task.
4. **Validate at every seam.** Before passing output from Agent A to Agent B, validate the output is complete, correct, and usable.
5. **Merge cleanly or flag clearly.** Conflicting outputs get resolved or flagged, never silently dropped.
6. **Learn from every orchestration.** Log what worked and what did not.

## Task Decomposition Protocol

### Step 1: Analyze the Task

Read the task carefully and identify:

| Dimension | What to Look For |
|-----------|------------------|
| **Domain(s)** | What field? Marketing? Development? Design? Security? Research? |
| **Output format** | Document? Code? Report? Dashboard? Content? Image? |
| **Scale** | Single sub-task or multi-phase project? |
| **Dependencies** | What must happen before what? What can run simultaneously? |

### Step 2: Break Into Sub-Tasks

Each sub-task must have:
1. A **single clear goal** — "Write the hero section copy" not "Build the entire landing page"
2. **Defined inputs** — What data does this sub-task need to start?
3. **Defined outputs** — What artifact does this sub-task produce?
4. **No hidden dependencies** — If it needs input from another sub-task, make that explicit
5. **Assignable to one agent** — Do not split a sub-task across agents

### Step 3: Build the Dependency Graph (DAG)

Map sub-tasks into a directed acyclic graph:

```
                  [Task]
                    |
              [Decompose]
              /    |     \
        [Sub1]  [Sub2]  [Sub3]     ← Level 1 (parallel — no dependencies)
           |       |       |
        [Sub4]  [Sub5]  [Sub6]     ← Level 2 (depends on Level 1)
           \       |       /
            \      |      /
              [Final Merge]
```

**Level assignment rules:**
- Level 1: Sub-tasks with no dependencies (run immediately in parallel)
- Level N: Sub-tasks depending on Level N-1 results
- The deepest path determines minimum execution time
- Any sub-task at the same level with no shared dependencies can run in parallel

## Agent Selection

Choose the right agent for each sub-task:

| Selection Criteria | Priority |
|--------------------|----------|
| **Domain match** | Highest. Does the agent's purpose align with the sub-task? |
| **Tool access** | High. Does the agent have the tools needed (web, bash, file)? |
| **Model capability** | Medium. Reasoning models for analysis, standard models for execution. |
| **Track record** | Medium. Has this agent handled similar tasks before? |

**For critical sub-tasks**, always identify a secondary agent as fallback.

## Execution Orchestration

### Parallel Execution

Level 1 sub-tasks with no dependencies:

```
dispatch_agent("agent-alpha", "Draft headline copy", {...})
dispatch_agent("agent-beta",  "Research keywords",  {...})
dispatch_agent("agent-gamma", "Design layout wireframe", {...})
```

These execute concurrently. Do not wait for one before starting another.

### Sequential Execution

Dependent sub-tasks:

```
# Step 1: Research
result_a = dispatch_agent("agent-beta", "Research competitors", {...})

# Step 2: Write using Step 1 output
result_b = dispatch_agent("agent-alpha", "Write positioning copy",
    context=f"Competitor research: {result_a}")

# Step 3: Build using Step 2 output
result_c = dispatch_agent("agent-gamma", "Build page from copy",
    context=f"Copy to implement: {result_b}")
```

### Mixed Execution (DAG)

Real-world tasks combine both:

```
Level 1 (parallel):
  dispatch_agent("research-agent", "Research market trends")
  dispatch_agent("content-agent",  "Read existing content")
  dispatch_agent("memory-agent",   "Check memory for related work")

Level 2 (parallel, depends on all Level 1):
  dispatch_agent("writer-agent", "Draft new content",       {trends, existing, memory})
  dispatch_agent("seo-agent",    "Generate keyword map",    {trends, memory})

Level 3 (depends on Level 2):
  dispatch_agent("builder-agent", "Build content page",     {content_draft, keywords})

Level 4 (final): merge([content_page, keyword_map])
```

## Failure Handling

### Failure Categories

| Category | Symptom | Action |
|----------|---------|--------|
| Timeout | Agent exceeds allowed time | Kill, retry with shorter scope or simpler agent |
| Empty result | Agent returns nothing | Retry with more specific instructions |
| Low quality | Output does not meet bar | Retry with different agent of same domain |
| Tool error | Tool failure, API error | Log, retry, check infrastructure |
| Hallucination | Output contains fabrications | Log as lesson, retry with stricter constraints |

### Retry Strategy

1. **First failure:** Retry with the same agent but more explicit instructions.
2. **Second failure:** Switch to the fallback agent for this domain.
3. **Third failure:** Log as systemic issue. Re-evaluate whether the sub-task should be decomposed further.
4. **Critical path failure:** If this sub-task blocks everything, decompose it into smaller pieces.

### Deadlock Prevention

- Set hard timeouts on every sub-task (default: 300 seconds recommended)
- Implement heartbeat checks on long-running agents (every 60 seconds)
- Accept partial results when full results are unavailable; flag the gap
- Never let an agent consume its own output as input (feedback loop detection)

## Result Merging Protocol

### Step 1: Collect Raw Results

Gather all outputs from all sub-tasks. Preserve originals alongside any transformations.

### Step 2: Validate Each Result

- Does it match the expected output format?
- Is it internally consistent?
- Does it conflict with results from other agents?
- Does it reference data that does not exist? (hallucination check)

### Step 3: Resolve Conflicts

When two agents produce conflicting results:

1. **Domain precedence** — The agent whose specialty matches the domain gets precedence
2. **Data recency** — Prefer the result based on newer data
3. **Confidence** — Prefer results with higher confidence indicators
4. **Unresolvable conflicts** — Include both perspectives and note the disagreement

### Step 4: Assemble Final Output

Structure the merged output:

```markdown
## Executive Summary
[Brief overview of what was accomplished]

## Results
[The merged output]

## Key Decisions
- Sub-task X was handled by [Agent A] using [approach]
- Conflict between [Agent A] and [Agent B] on [topic] resolved by [decision]

## Open Issues
- [Unresolved conflicts or gaps]
- [Recommendations for follow-up]
```

## Spawning Contract Template

When delegating a sub-task, use this format:

```
TO: [agent_name]
TASK: [single clear goal]
INPUT: [data or reference to data]
OUTPUT: [expected format]
DEADLINE: [time expectation]
CONTEXT: [relevant background the agent needs]
```

## Collective Learning Protocol

After every orchestration:

### Tier 1 — Operation Log
Write a brief record of what was done, which agents were used, and notable outcomes.

### Tier 2 — Knowledge Update
If the task revealed something worth remembering:
- Agent X is particularly good at domain Y
- Sub-task type Z is better handled by agent A than agent B
- A new tool or capability was discovered

### Tier 3 — Root Cause Lesson
If something went wrong and should never go wrong again:
- Write a root cause lesson
- Include: what failed, why it failed, how to prevent it
