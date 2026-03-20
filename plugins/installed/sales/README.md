# Sales Plugin

A sales productivity plugin primarily designed for [Cowork](https://claude.com/product/cowork), Anthropic's agentic desktop application — though it also works in Claude Code. Helps with prospecting, outreach, pipeline management, call preparation, and deal strategy. Works with any sales team — standalone with web search and your input, supercharged when you connect your CRM, email, and other tools.

## Installation

```bash
claude plugins add knowledge-work-plugins/sales
```

## Commands

Explicit workflows you invoke with a slash command:

| Command | Description |
|---|---|
| `/call-summary` | Process call notes or transcript — extract action items, draft follow-up, generate internal summary |
| `/forecast` | Generate a weighted sales forecast — upload CSV or describe your pipeline, set quota, get projections |
| `/pipeline-review` | Analyze pipeline health — prioritize deals, flag risks, get weekly action plan |

All commands work **standalone** (paste notes, upload CSV, or describe your situation) and get **supercharged** with MCP connectors.

## Skills

Domain knowledge Claude uses automatically when relevant:

| Skill | Description |
|---|---|
| `account-research` | Research a company or person — web search for company intel, key contacts, recent news, hiring signals |
| `call-prep` | Prepare for sales calls — account context, attendee research, suggested agenda, discovery questions |
| `daily-briefing` | Prioritized daily sales briefing — meetings, pipeline alerts, email priorities, suggested actions |
| `draft-outreach` | Research-first outreach — research the prospect, then draft personalized email and LinkedIn messages |
| `competitive-intelligence` | Research competitors — product comparison, pricing intel, recent releases, differentiation matrix, sales talk tracks |
| `create-an-asset` | Generate custom sales assets — landing pages, decks, one-pagers, workflow demos tailored to your prospect |

## Example Workflows

### After a Call

```
/call-summary
```

Paste your notes or transcript. Get a structured summary, action items with owners, and a draft follow-up email. If CRM is connected, offers to log the activity and create tasks.

### Weekly Forecast

```
/forecast
```

Upload a CSV export from your CRM (or paste your deals). Tell me your quota and timeline. Get a weighted forecast with best/likely/worst scenarios, commit vs. upside breakdown, and gap analysis.

### Pipeline Review

```
/pipeline-review
```

Upload a CSV or describe your pipeline. Get a health score, deal prioritization, risk flags (stale deals, past close dates, single-threaded), and a weekly action plan.

### Researching a Prospect

Just ask naturally:
```
Research Acme Corp before my call tomorrow
```

The `account-research` skill triggers automatically and gives you company overview, key contacts, recent news, and recommended approach.

### Drafting Outreach

```
Draft an email to the VP of Engineering at TechStart
```

The `draft-outreach` skill researches the prospect first, then generates personalized outreach with multiple angles.

### Competitive Intel

```
How do we compare to Competitor X?
```

The `competitive-intelligence` skill researches both companies and builds a differentiation matrix with talk tracks.

## Standalone + Supercharged

Every command and skill works without any integrations:

| What You Can Do | Standalone | Supercharged With |
|-----------------|------------|-------------------|
| Process call notes | Paste notes/transcript | Transcripts MCP (e.g. Gong, Fireflies) |
| Forecast pipeline | Upload CSV, paste deals | CRM MCP |
| Review pipeline | Upload CSV, describe deals | CRM MCP |
| Research prospects | Web search | Enrichment MCP (e.g. Clay, ZoomInfo) |
| Prep for calls | Describe meeting | CRM, Email, Calendar MCPs |
| Draft outreach | Web search + your context | CRM, Email MCPs |
| Competitive intel | Web search | CRM (win/loss data), Docs (battlecards) |

## MCP Integrations

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](CONNECTORS.md).

Connect your tools for a richer experience:

| Category | Examples | What It Enables |
|---|---|---|
| **CRM** | HubSpot, Close | Pipeline data, account history, contact records |
| **Transcripts** | Fireflies, Gong, Chorus | Call recordings, transcripts, key moments |
| **Enrichment** | Clay, ZoomInfo, Apollo | Company and contact data enrichment |
| **Chat** | Slack, Teams | Internal discussions, colleague intel |

See [CONNECTORS.md](CONNECTORS.md) for the full list of supported integrations, including email, calendar, and additional CRM options.

## Settings

Create a local settings file at `sales/.claude/settings.local.json` to personalize:

```json
{
  "name": "Your Name",
  "title": "Account Executive",
  "company": "Your Company",
  "quota": {
    "annual": 1000000,
    "quarterly": 250000
  },
  "product": {
    "name": "Your Product",
    "value_props": [
      "Key value proposition 1",
      "Key value proposition 2"
    ],
    "competitors": [
      "Competitor A",
      "Competitor B"
    ]
  }
}
```

The plugin will ask you for this information interactively if it's not configured.
