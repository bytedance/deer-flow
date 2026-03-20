# Marketing Plugin

A marketing plugin primarily designed for [Cowork](https://claude.com/product/cowork), Anthropic's agentic desktop application — though it also works in Claude Code. Content creation, campaign planning, brand voice management, competitive analysis, and performance reporting.

## Installation

```bash
claude plugins add knowledge-work-plugins/marketing
```

## Commands

| Command | Description |
|---|---|
| `/draft-content` | Draft blog posts, social media, email newsletters, landing pages, press releases, and case studies |
| `/campaign-plan` | Generate a full campaign brief with objectives, channels, content calendar, and success metrics |
| `/brand-review` | Review content against your brand voice, style guide, and messaging pillars |
| `/competitive-brief` | Research competitors and generate a positioning and messaging comparison |
| `/performance-report` | Build a marketing performance report with key metrics, trends, and optimization recommendations |
| `/seo-audit` | Run a comprehensive SEO audit — keyword research, on-page analysis, content gaps, technical checks, and competitor comparison |
| `/email-sequence` | Design and draft multi-email sequences for nurture flows, onboarding, drip campaigns, and more |

## Skills

| Skill | Description |
|---|---|
| `content-creation` | Content type templates, writing best practices by channel, SEO fundamentals, headline formulas, and CTA guidance |
| `campaign-planning` | Campaign frameworks, channel selection, content calendar creation, budget allocation, and success metrics |
| `brand-voice` | Brand voice documentation, voice attributes, tone adaptation, style guide enforcement, and terminology management |
| `competitive-analysis` | Competitive research methodology, messaging comparison, content gap analysis, positioning, and battlecard creation |
| `performance-analytics` | Key metrics by channel, reporting templates, trend analysis, attribution modeling, and optimization frameworks |

## Example Workflows

### Drafting a Blog Post

```
> /draft-content
Type: blog post
Topic: How AI is transforming B2B marketing
Audience: Marketing directors at mid-market SaaS companies
Key messages: AI saves time on repetitive tasks, improves personalization, requires human oversight
Tone: Authoritative but approachable
Length: 1200 words
```

Claude will generate a structured blog post draft with an engaging headline, introduction with a hook, organized sections, SEO-optimized subheadings, and a clear call to action.

### Planning a Campaign

```
> /campaign-plan
Goal: Drive 500 signups for our new product launch
Audience: Technical decision-makers at enterprise companies
Timeline: 6 weeks
Budget range: $20,000-$30,000
```

Claude will produce a campaign brief covering objectives, audience segmentation, key messages, channel strategy, a week-by-week content calendar, and KPIs to track.

### Reviewing Content Against Brand Guidelines

```
> /brand-review
[paste your draft content]
```

If your brand style guide is configured in local settings, Claude will check your content against voice, tone, terminology, and messaging pillars. If not configured, Claude will ask about your guidelines or provide a generic review for clarity, consistency, and professionalism.

## Configuration

Configure your brand voice, style guide, and target personas in a local settings file for personalized output. This allows commands like `/draft-content` and `/brand-review` to automatically apply your brand standards without prompting each time.

## MCP Integrations

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](CONNECTORS.md).

This plugin works with the following MCP servers:

- **Slack** — Share drafts, reports, and briefs with your team
- **Canva** — Create and edit design assets
- **Figma** — Access design files and brand assets
- **HubSpot** — Pull campaign data, manage contacts, and track marketing automation
- **Amplitude** — Pull product analytics and user behavior data for performance reporting
- **Notion** — Access briefs, style guides, and campaign documents
- **Ahrefs** — SEO keyword research, backlink analysis, and site audits
- **Similarweb** — Competitive traffic analysis and market benchmarking
- **Klaviyo** — Draft and review email marketing sequences and campaigns
