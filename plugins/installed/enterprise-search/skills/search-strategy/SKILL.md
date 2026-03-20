---
name: search-strategy
description: Query decomposition and multi-source search orchestration. Breaks natural language questions into targeted searches per source, translates queries into source-specific syntax, ranks results by relevance, and handles ambiguity and fallback strategies.
---

# Search Strategy

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../../CONNECTORS.md).

The core intelligence behind enterprise search. Transforms a single natural language question into parallel, source-specific searches and produces ranked, deduplicated results.

## The Goal

Turn this:
```
"What did we decide about the API migration timeline?"
```

Into targeted searches across every connected source:
```
~~chat:  "API migration timeline decision" (semantic) + "API migration" in:#engineering after:2025-01-01
~~knowledge base: semantic search "API migration timeline decision"
~~project tracker:  text search "API migration" in relevant workspace
```

Then synthesize the results into a single coherent answer.

## Query Decomposition

### Step 1: Identify Query Type

Classify the user's question to determine search strategy:

| Query Type | Example | Strategy |
|-----------|---------|----------|
| **Decision** | "What did we decide about X?" | Prioritize conversations (~~chat, email), look for conclusion signals |
| **Status** | "What's the status of Project Y?" | Prioritize recent activity, task trackers, status updates |
| **Document** | "Where's the spec for Z?" | Prioritize Drive, wiki, shared docs |
| **Person** | "Who's working on X?" | Search task assignments, message authors, doc collaborators |
| **Factual** | "What's our policy on X?" | Prioritize wiki, official docs, then confirmatory conversations |
| **Temporal** | "When did X happen?" | Search with broad date range, look for timestamps |
| **Exploratory** | "What do we know about X?" | Broad search across all sources, synthesize |

### Step 2: Extract Search Components

From the query, extract:

- **Keywords**: Core terms that must appear in results
- **Entities**: People, projects, teams, tools (use memory system if available)
- **Intent signals**: Decision words, status words, temporal markers
- **Constraints**: Time ranges, source hints, author filters
- **Negations**: Things to exclude

### Step 3: Generate Sub-Queries Per Source

For each available source, create one or more targeted queries:

**Prefer semantic search** for:
- Conceptual questions ("What do we think about...")
- Questions where exact keywords are unknown
- Exploratory queries

**Prefer keyword search** for:
- Known terms, project names, acronyms
- Exact phrases the user quoted
- Filter-heavy queries (from:, in:, after:)

**Generate multiple query variants** when the topic might be referred to differently:
```
User: "Kubernetes setup"
Queries: "Kubernetes", "k8s", "cluster", "container orchestration"
```

## Source-Specific Query Translation

### ~~chat

**Semantic search** (natural language questions):
```
query: "What is the status of project aurora?"
```

**Keyword search:**
```
query: "project aurora status update"
query: "aurora in:#engineering after:2025-01-15"
query: "from:<@UserID> aurora"
```

**Filter mapping:**
| Enterprise filter | ~~chat syntax |
|------------------|--------------|
| `from:sarah` | `from:sarah` or `from:<@USERID>` |
| `in:engineering` | `in:engineering` |
| `after:2025-01-01` | `after:2025-01-01` |
| `before:2025-02-01` | `before:2025-02-01` |
| `type:thread` | `is:thread` |
| `type:file` | `has:file` |

### ~~knowledge base (Wiki)

**Semantic search** — Use for conceptual queries:
```
descriptive_query: "API migration timeline and decision rationale"
```

**Keyword search** — Use for exact terms:
```
query: "API migration"
query: "\"API migration timeline\""  (exact phrase)
```

### ~~project tracker

**Task search:**
```
text: "API migration"
workspace: [workspace_id]
completed: false  (for status queries)
assignee_any: "me"  (for "my tasks" queries)
```

**Filter mapping:**
| Enterprise filter | ~~project tracker parameter |
|------------------|----------------|
| `from:sarah` | `assignee_any` or `created_by_any` |
| `after:2025-01-01` | `modified_on_after: "2025-01-01"` |
| `type:milestone` | `resource_subtype: "milestone"` |

## Result Ranking

### Relevance Scoring

Score each result on these factors (weighted by query type):

| Factor | Weight (Decision) | Weight (Status) | Weight (Document) | Weight (Factual) |
|--------|-------------------|------------------|--------------------|-------------------|
| Keyword match | 0.3 | 0.2 | 0.4 | 0.3 |
| Freshness | 0.3 | 0.4 | 0.2 | 0.1 |
| Authority | 0.2 | 0.1 | 0.3 | 0.4 |
| Completeness | 0.2 | 0.3 | 0.1 | 0.2 |

### Authority Hierarchy

Depends on query type:

**For factual/policy questions:**
```
Wiki/Official docs > Shared documents > Email announcements > Chat messages
```

**For "what happened" / decision questions:**
```
Meeting notes > Thread conclusions > Email confirmations > Chat messages
```

**For status questions:**
```
Task tracker > Recent chat > Status docs > Email updates
```

## Handling Ambiguity

When a query is ambiguous, prefer asking one focused clarifying question over guessing:

```
Ambiguous: "search for the migration"
→ "I found references to a few migrations. Are you looking for:
   1. The database migration (Project Phoenix)
   2. The cloud migration (AWS → GCP)
   3. The email migration (Exchange → O365)"
```

Only ask for clarification when:
- There are genuinely distinct interpretations that would produce very different results
- The ambiguity would significantly affect which sources to search

Do NOT ask for clarification when:
- The query is clear enough to produce useful results
- Minor ambiguity can be resolved by returning results from multiple interpretations

## Fallback Strategies

When a source is unavailable or returns no results:

1. **Source unavailable**: Skip it, search remaining sources, note the gap
2. **No results from a source**: Try broader query terms, remove date filters, try alternate keywords
3. **All sources return nothing**: Suggest query modifications to the user
4. **Rate limited**: Note the limitation, return results from other sources, suggest retrying later

### Query Broadening

If initial queries return too few results:
```
Original: "PostgreSQL migration Q2 timeline decision"
Broader:  "PostgreSQL migration"
Broader:  "database migration"
Broadest: "migration"
```

Remove constraints in this order:
1. Date filters (search all time)
2. Source/location filters
3. Less important keywords
4. Keep only core entity/topic terms

## Parallel Execution

Always execute searches across sources in parallel, never sequentially. The total search time should be roughly equal to the slowest single source, not the sum of all sources.

```
[User query]
     ↓ decompose
[~~chat query] [~~email query] [~~cloud storage query] [Wiki query] [~~project tracker query]
     ↓            ↓            ↓              ↓            ↓
  (parallel execution)
     ↓
[Merge + Rank + Deduplicate]
     ↓
[Synthesized answer]
```
