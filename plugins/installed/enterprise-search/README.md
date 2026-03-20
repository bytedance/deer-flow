# Enterprise Search

An enterprise search plugin primarily designed for [Cowork](https://claude.com/product/cowork), Anthropic's agentic desktop application — though it also works in Claude Code. Search across all your company's tools in one place — email, chat, documents, and wikis — without switching between apps.

---

## How It Works

One query searches all your connected tools simultaneously. Claude decomposes your question, runs targeted searches across every source, and synthesizes the results into a single coherent answer with source attribution.

```
You: "What did we decide about the API redesign?"
              ↓ Claude searches
~~chat: #engineering thread from Tuesday with the decision
~~email: Follow-up email from Sarah with the spec
~~cloud storage: Updated API design doc (modified yesterday)
              ↓ Claude synthesizes
"The team decided on Tuesday to go with REST over GraphQL.
 Sarah sent the updated spec Thursday. The design doc
 reflects the final approach."
```

No tab switching. No remembering which tool has what. Ask the question, get the answer.

---

## What It Searches

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](CONNECTORS.md).

Connect any combination of sources. The more you connect, the more complete your answers.

| Source | What it finds |
|--------|---------------|
| **~~chat** | Messages, threads, channels, DMs |
| **~~email** | Emails, attachments, conversations |
| **~~cloud storage** | Docs, sheets, slides, PDFs |
| **Wiki / Knowledge Base** | Internal documentation, runbooks |
| **Project Management** | Tasks, issues, epics, milestones |
| **CRM** | Accounts, contacts, opportunities |
| **Ticketing** | Support tickets, customer issues |

Each source is an MCP connection. Add more sources in your MCP settings to expand what Claude can search.

---

## Commands

| Command | What it does |
|---------|--------------|
| `/search` | Search across all connected sources in one query |
| `/digest` | Generate a daily or weekly digest of activity across all sources |

### Search

```
/enterprise-search:search what's the status of Project Aurora?
/enterprise-search:search from:sarah about:budget after:2025-01-01
/enterprise-search:search decisions made in #product this week
```

Supports filters: `from:`, `in:`, `after:`, `before:`, `type:` — applied intelligently across each source's native query syntax.

### Digest

```
/enterprise-search:digest --daily      # What happened today across all sources
/enterprise-search:digest --weekly     # Weekly rollup grouped by project/topic
```

Highlights action items, decisions, and mentions of you. Groups activity by topic so you can skim what matters.

---

## Skills

Three skills power the search experience:

**Search Strategy** — Query decomposition and source-specific translation. Breaks your natural language question into targeted searches per source, handles ambiguity, and falls back gracefully when sources are unavailable.

**Source Management** — Knows which MCP sources are available, guides you to connect new ones, manages source priority, and handles rate limits.

**Knowledge Synthesis** — Combines results from multiple sources into coherent answers. Deduplicates cross-source information, attributes sources, scores confidence based on freshness and authority, and summarizes large result sets.

---

## Example Workflows

### Finding a decision

```
You: /enterprise-search:search when did we decide to switch to Postgres?

Claude searches:
  ~~chat → #engineering, #infrastructure for "postgres" "switch" "decision"
  ~~email → threads with "postgres" in subject
  ~~cloud storage → docs mentioning database migration

Result: "The decision was made March 3 in #infrastructure (link).
         Sarah's email on March 4 confirmed the timeline.
         The migration plan doc was updated March 5."
```

### Catching up after time off

```
You: /enterprise-search:digest --weekly

Claude scans:
  ~~chat → channels you're in, DMs, mentions
  ~~email → inbox activity
  ~~cloud storage → docs shared with you or modified

Result: Grouped summary by project with action items
        flagged and decisions highlighted.
```

### Finding an expert

```
You: /enterprise-search:search who knows about our Kubernetes setup?

Claude searches:
  ~~chat → messages about Kubernetes, k8s, clusters
  ~~cloud storage → docs authored about infrastructure
  Wiki → runbooks and architecture docs

Result: "Based on message history and doc authorship,
         Alex and Priya are your go-to people for k8s.
         Here's the main runbook (link)."
```

---

## Getting Started

```bash
# 1. Install
claude plugins add knowledge-work-plugins/enterprise-search

# 2. Search across everything
/enterprise-search:search [your question here]

# 3. Get a digest
/enterprise-search:digest --daily
```

The more sources you connect via MCP, the more complete your search results. Start with ~~chat, ~~email, and ~~cloud storage, then add your wiki, project management tool, and CRM as needed.

---

## Philosophy

Knowledge workers spend hours every week hunting for information scattered across tools. The answer exists somewhere — in a Slack thread, an email chain, a doc, a wiki page — but finding it means searching each tool individually, cross-referencing results, and hoping you checked the right place.

Enterprise Search treats all your tools as one searchable knowledge base. One query, all sources, synthesized results. Your company's knowledge shouldn't be locked in silos. Search everything at once.
