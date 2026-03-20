# Customer Support Plugin

A customer support plugin primarily designed for [Cowork](https://claude.com/product/cowork), Anthropic's agentic desktop application — though it also works in Claude Code. Provides ticket triage, escalation management, response drafting, customer research, and knowledge base authoring for support teams.

## Installation

```
claude plugins add knowledge-work-plugins/customer-support
```

## What It Does

This plugin turns Claude into a customer support co-pilot. It helps you:

- **Triage incoming tickets** with structured categorization, priority assessment, and routing recommendations
- **Research customer questions** by synthesizing information from multiple sources with confidence scoring
- **Draft professional responses** tailored to the situation, urgency, and communication channel
- **Package escalations** with full context, reproduction steps, and business impact for engineering or product
- **Write KB articles** from resolved issues to reduce future ticket volume

## Commands

| Command | Description |
|---|---|
| `/triage` | Categorize, prioritize, and route a support ticket or customer issue |
| `/research` | Multi-source research on a customer question or topic |
| `/draft-response` | Draft a customer-facing response for any situation |
| `/escalate` | Package an escalation for engineering, product, or leadership |
| `/kb-article` | Draft a knowledge base article from a resolved issue |

## Skills

| Skill | Description |
|---|---|
| `ticket-triage` | Category taxonomy, priority framework (P1-P4), routing rules, duplicate detection |
| `customer-research` | Multi-source research methodology, source prioritization, answer synthesis |
| `response-drafting` | Communication best practices, tone guidelines, templates for common scenarios |
| `escalation` | Escalation tiers, structured escalation format, impact assessment, follow-up cadence |
| `knowledge-management` | Article structure standards, writing for searchability, review cadence, maintenance |

## Data Sources

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](CONNECTORS.md).

Connect your support platform, knowledge base, and communication tools for the best experience. Without them, provide customer context manually.

**Included MCP connections:**
- Chat (Slack) for internal discussions and customer channel context
- Support platform (Intercom) for ticket history and customer conversations
- CRM (HubSpot) for account details and contact information
- Knowledge base (Guru, Notion) for internal documentation and runbooks
- Project tracker (Atlassian) for bug reports and feature requests
- Email and cloud storage (Microsoft 365) for customer correspondence

**Additional options:**
- See [CONNECTORS.md](CONNECTORS.md) for alternative tools in each category

## Example Workflows

### Triaging an Incoming Ticket

```
You: /triage Customer says their dashboard has been showing a blank
     page since this morning — they're on the Enterprise plan

Claude: Analyzing the issue...

## Triage: Dashboard blank page — Enterprise customer

**Category:** Bug
**Priority:** P2 — High (core feature broken, enterprise customer)
**Product area:** Dashboard / Frontend

### Routing Recommendation
Route to: Tier 2 Support (investigate browser/account specifics,
then escalate to Engineering if reproducible)

### Suggested Initial Response
[Draft acknowledging the issue, asking clarifying questions
about browser and any recent changes, offering status page link]
```

### Researching a Customer Question

```
You: /research Does our platform support SSO with Okta?

Claude: Let me check across available sources...

[Searches docs, knowledge base, previous conversations,
 and web sources — synthesizes answer with confidence
 level and source attribution]
```

### Packaging an Escalation

```
You: /escalate API returning 500 errors intermittently — 3
     Enterprise customers reported this week

Claude: I'll gather context and build the escalation brief...

[Pulls ticket history, identifies affected accounts,
 structures reproduction steps, assesses business impact,
 and generates a structured escalation for engineering]
```

### Drafting a Response

```
You: /draft-response Customer escalation — their integration
     has been down for 2 days and they're frustrated

Claude: [Generates empathetic, professional response acknowledging
 the frustration, taking ownership, providing a clear action
 plan with timeline, and offering a call]
```

### Writing a KB Article

```
You: /kb-article How to configure webhook notifications —
     just resolved this for the third customer this month

Claude: [Generates a structured how-to article with prerequisites,
 step-by-step instructions, verification steps, and common
 issues — optimized for search]
```

## Configuration

The plugin works out of the box with the included MCP connections. For the richest experience, connect additional data sources through your Claude settings:

1. **Support platform**: Add your ticketing system for ticket history and customer context
2. **Knowledge base**: Add your wiki for internal documentation and existing KB articles
3. **Project tracker**: Add your issue tracker for bug reports and feature requests
4. **CRM**: Add your CRM for account details and contact information

Without these connections, the plugin will ask you to provide context manually and offer frameworks and templates you can fill in with your own data.
