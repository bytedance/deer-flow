# Plugin End-to-End Testing Queries

Comprehensive end-to-end testing queries for all 11 installed Anthropic knowledge-work plugins. Each section covers both **slash commands** (explicit user-invoked actions) and **skills** (auto-activated domain knowledge).

> **How to use:** Run each query against the Thinktank.ai agent with the corresponding plugin enabled. Verify the agent loads the correct skill/command, follows the documented workflow, and produces the expected output format.

---

## Table of Contents

1. [Sales](#1-sales)
2. [Customer Support](#2-customer-support)
3. [Data](#3-data)
4. [Finance](#4-finance)
5. [Legal](#5-legal)
6. [Marketing](#6-marketing)
7. [Product Management](#7-product-management)
8. [Enterprise Search](#8-enterprise-search)
9. [Bio Research](#9-bio-research)
10. [Productivity](#10-productivity)
11. [Cowork Plugin Management](#11-cowork-plugin-management)

---

## 1. Sales

**Plugin:** `sales` v1.0.0
**Skills:** 6 | **Commands:** 3 | **MCP Servers:** 9 (slack, hubspot, close, clay, zoominfo, notion, atlassian, fireflies, ms365)

### Commands

#### `/sales:call-summary`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 1 | `/sales:call-summary Here are my notes from the call with Acme Corp: They're interested in our Enterprise plan, main concern is data migration timeline. Decision maker is VP of Eng Sarah Chen. Next step: send technical architecture doc by Friday.` | Produces structured call summary with key discussion points, action items with owners/deadlines, next steps, and deal impact assessment |
| 2 | `/sales:call-summary [paste a 2-page call transcript with multiple speakers discussing pricing, features, and timeline]` | Extracts and organizes multi-speaker conversation into topics, captures objections raised, identifies buying signals, lists all commitments made |

#### `/sales:forecast`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 3 | `/sales:forecast Q2 2026` | Generates quarterly sales forecast with pipeline analysis, stage-weighted projections, risk factors, and confidence intervals |
| 4 | `/sales:forecast next month — focus on Enterprise segment only` | Produces segment-filtered forecast with deal-by-deal breakdown, probability weighting, and gap-to-quota analysis |

#### `/sales:pipeline-review`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 5 | `/sales:pipeline-review` | Analyzes full pipeline health with stage conversion rates, aging deals, stuck opportunities, and prioritized weekly action plan |
| 6 | `/sales:pipeline-review Flag any deals that haven't had activity in 14+ days and are supposed to close this quarter` | Identifies stale deals, scores health by activity recency/stage progression/contact coverage, generates re-engagement recommendations |

### Skills

#### Account Research
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 7 | `Research Stripe as a potential customer for our API monitoring product. What's their tech stack, recent news, and who should I reach out to?` | Loads account-research skill, performs web research, produces company overview, tech stack analysis, recent news/triggers, org chart with recommended contacts, and suggested angles |
| 8 | `I have a meeting with the CTO of Datadog next week. Give me a comprehensive account brief.` | Produces detailed account research with company financials, competitive positioning, technology landscape, and key personnel profiles |

#### Call Prep
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 9 | `I have a discovery call with the VP of Engineering at Notion tomorrow at 2pm. Help me prepare.` | Loads call-prep skill, generates attendee research, account context, suggested agenda with discovery questions, potential objections and responses, and success criteria |
| 10 | `Prep me for a renewal call with CloudFlare — they've been a customer for 2 years and their contract is up in 30 days.` | Produces renewal-specific prep with usage/adoption data review, expansion opportunities, risk assessment, and competitive defense talking points |

#### Draft Outreach
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 11 | `Draft a cold outreach email to the Head of Data at Airbnb. We sell a real-time data pipeline tool.` | Loads draft-outreach skill, researches the prospect and company, crafts personalized email with specific pain points, social proof, and clear CTA |
| 12 | `Write a LinkedIn connection request and follow-up sequence for targeting Series B fintech CTOs.` | Generates multi-touch outreach sequence with personalization hooks, value propositions, and timing recommendations |

#### Daily Briefing
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 13 | `Give me my sales briefing for today.` | Loads daily-briefing skill, produces prioritized list of deals requiring attention, meetings summary, tasks due, pipeline changes, and recommended focus areas |

#### Competitive Intelligence
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 14 | `Build me a competitive battlecard for Salesforce vs our CRM product. Focus on mid-market positioning.` | Loads competitive-intelligence skill, researches competitor, produces interactive HTML battlecard with feature comparison, pricing, win/loss themes, objection handling, and competitive positioning |
| 15 | `What are the key weaknesses of HubSpot's enterprise offering that we can exploit in deals?` | Generates competitive analysis with specific weakness areas, customer complaints, feature gaps, and suggested talk tracks |

#### Create an Asset
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 16 | `Create a one-pager for our API monitoring product targeting financial services companies.` | Loads create-an-asset skill, generates a polished one-pager with industry-specific pain points, solution overview, ROI metrics, and customer logos |
| 17 | `Build a custom landing page for the Acme Corp deal that shows how our product solves their specific integration challenges.` | Produces a self-contained HTML landing page tailored to the account with personalized messaging and relevant case studies |

---

## 2. Customer Support

**Plugin:** `customer-support` v1.0.0
**Skills:** 5 | **Commands:** 5 | **MCP Servers:** 7 (slack, intercom, hubspot, guru, atlassian, notion, ms365)

### Commands

#### `/customer-support:triage`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 18 | `/customer-support:triage Customer reports: "Login page returns 500 error since this morning. Affects all users on our Enterprise plan. Can't access any dashboards."` | Categorizes as bug/outage, assigns P1 priority, routes to engineering, checks for related incidents, suggests initial response |
| 19 | `/customer-support:triage "How do I export my data to CSV? I looked in docs but can't find it."` | Categorizes as how-to, assigns P3 priority, routes to Tier 1 support, links relevant documentation |

#### `/customer-support:draft-response`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 20 | `/customer-support:draft-response Customer is frustrated about recurring billing errors for the third month. They're a 3-year Enterprise customer threatening to churn.` | Drafts empathetic, de-escalation-focused response acknowledging history, providing concrete resolution steps, and offering retention-oriented compensation |
| 21 | `/customer-support:draft-response A customer is asking about GDPR compliance for our data processing. They need specifics for their DPA audit.` | Drafts a detailed technical response covering data processing locations, retention policies, and security certifications with appropriate legal disclaimers |

#### `/customer-support:research`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 22 | `/customer-support:research Customer is experiencing intermittent WebSocket disconnections in our real-time collaboration feature. They're on Chrome 120, behind a corporate proxy.` | Conducts multi-source research across docs, known issues, and engineering notes. Synthesizes technical findings with troubleshooting steps |

#### `/customer-support:escalate`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 23 | `/customer-support:escalate Data loss incident: Customer's project files disappeared after our latest deployment. Affects 50+ users. Customer is a Fortune 500 account.` | Packages P1 escalation with reproduction steps, business impact ($ARR at risk), affected accounts, timeline, and suggested engineering response |

#### `/customer-support:kb-article`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 24 | `/customer-support:kb-article We just resolved a common issue where SSO users get stuck in a redirect loop when their IdP session expires. Root cause was token refresh race condition, fix is to clear browser cookies.` | Creates structured KB article with title, problem description, symptoms, root cause, step-by-step solution, and prevention tips |

### Skills

#### Ticket Triage (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 25 | `I have 15 support tickets that came in overnight. Help me prioritize them for the morning standup.` | Loads ticket-triage skill, categorizes each ticket by type and priority (P1-P4), suggests routing, identifies any related/duplicate tickets |

#### Response Drafting (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 26 | `A customer on our free tier is asking for enterprise features. How should I respond?` | Loads response-drafting skill, crafts a diplomatic response that acknowledges the request, explains tier differences, and presents upgrade path |

#### Customer Research (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 27 | `Pull together everything we know about Acme Corp's support history — tickets, common issues, their account health.` | Loads customer-research skill, synthesizes multi-source customer context including ticket history, product usage patterns, and relationship health |

#### Escalation (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 28 | `This bug has been reported by 3 Enterprise customers now. I need to escalate to engineering with full context.` | Loads escalation skill, determines escalation path, assembles full technical context with pattern analysis across reporters |

#### Knowledge Management (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 29 | `We keep getting the same question about SAML configuration. Help me create documentation to reduce ticket volume.` | Loads knowledge-management skill, produces structured KB article optimized for searchability with step-by-step instructions and common pitfalls |

---

## 3. Data

**Plugin:** `data` v1.0.0
**Skills:** 7 | **Commands:** 6 | **MCP Servers:** 6 (snowflake, databricks, bigquery, hex, amplitude, atlassian)

### Commands

#### `/data:write-query`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 30 | `/data:write-query Show me the top 10 customers by revenue in the last 90 days, broken down by product line. We use Snowflake.` | Generates optimized Snowflake SQL with proper date functions, GROUP BY, window functions if needed, and explains query logic |
| 31 | `/data:write-query Find all users who signed up in January but haven't logged in since February. PostgreSQL.` | Produces PostgreSQL query with proper JOIN pattern, date filtering, and NULL handling for the churn analysis use case |

#### `/data:explore-data`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 32 | `/data:explore-data I have a new dataset of 500K e-commerce transactions. Profile it for me — I need to understand data quality before analysis.` | Generates comprehensive data profile: row/column counts, type distributions, null percentages, cardinality, statistical summaries, potential anomalies |

#### `/data:analyze`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 33 | `/data:analyze Why did our conversion rate drop 15% last week compared to the previous week?` | Conducts multi-dimensional analysis: segments by channel/device/geography, identifies contributing factors, validates findings, presents with confidence levels |

#### `/data:create-viz`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 34 | `/data:create-viz Create a chart showing monthly revenue trends for the last 12 months with a forecast line for the next 3 months.` | Produces Python visualization code (matplotlib/plotly) with proper formatting, axis labels, legends, and trend/forecast overlay |

#### `/data:build-dashboard`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 35 | `/data:build-dashboard Build me an executive dashboard showing: MRR trend, churn rate, NPS score, and top 5 accounts by expansion revenue.` | Generates self-contained HTML dashboard with Chart.js visualizations, filters, responsive layout, and interactive elements |

#### `/data:validate`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 36 | `/data:validate I'm about to present this analysis to the C-suite: "Our Q1 revenue grew 23% YoY driven primarily by Enterprise segment expansion." Can you QA this before I share?` | Reviews methodology, checks for survivorship bias, validates percentage calculations, examines segment definitions, and flags any gaps in the analysis |

### Skills

#### SQL Queries (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 37 | `Write me a BigQuery query that calculates 7-day rolling average of daily active users, partitioned by country.` | Loads sql-queries skill, produces dialect-specific BigQuery SQL with window functions, proper partitioning, and performance considerations |

#### Data Visualization (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 38 | `I need to visualize the correlation between marketing spend and lead generation across 5 channels over 12 months.` | Loads data-visualization skill, recommends chart type, generates Python code with publication-quality formatting and accessibility |

#### Statistical Analysis (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 39 | `Is the difference in conversion rates between our A/B test variants statistically significant? Control: 3.2% (n=5000), Treatment: 3.8% (n=4800).` | Loads statistical-analysis skill, performs appropriate hypothesis test (chi-square/z-test), reports p-value, confidence intervals, and practical significance |

#### Interactive Dashboard Builder (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 40 | `Create an interactive sales performance dashboard with filters for region, product, and time period.` | Loads interactive-dashboard-builder skill, builds self-contained HTML/JS dashboard with Chart.js, dropdown filters, and responsive design |

#### Data Exploration (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 41 | `I just got access to a new customer events table. Help me understand its structure, data quality, and what analyses it could support.` | Loads data-exploration skill, systematically profiles the table: schema, completeness, distributions, relationships, and recommended use cases |

#### Data Validation (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 42 | `Check my analysis for errors before I send it to the board. [paste analysis summary]` | Loads data-validation skill, runs through QA checklist: methodology review, calculation verification, bias checks, and presentation recommendations |

#### Data Context Extractor (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 43 | `Help me document our company's data model and business logic so the team can write better queries.` | Loads data-context-extractor skill, facilitates knowledge extraction through targeted questions about schemas, terminology, and business rules |

---

## 4. Finance

**Plugin:** `finance` v1.0.0
**Skills:** 6 | **Commands:** 5 | **MCP Servers:** 5 (snowflake, databricks, bigquery, slack, ms365)

### Commands

#### `/finance:journal-entry`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 44 | `/finance:journal-entry Record the monthly rent expense of $15,000 for our SF office. Prepaid rent was booked in January for 6 months.` | Generates journal entry with proper debit (Rent Expense) and credit (Prepaid Rent) entries, amounts, dates, supporting detail, and period assignment |
| 45 | `/finance:journal-entry We received a $50,000 annual SaaS subscription payment from Acme Corp. Recognize revenue monthly per ASC 606.` | Produces deferred revenue entry with monthly recognition schedule, proper accounts, and ASC 606 compliance notes |

#### `/finance:reconciliation`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 46 | `/finance:reconciliation Reconcile our accounts receivable GL balance of $1.2M against the subledger total of $1.15M. Identify the $50K difference.` | Produces reconciliation worksheet with categorized reconciling items (timing differences, errors, adjustments), action items, and sign-off template |

#### `/finance:income-statement`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 47 | `/finance:income-statement Generate a Q1 2026 income statement with comparison to Q1 2025 and budget.` | Produces formatted income statement with GAAP presentation, YoY comparison, budget variance, and key ratio analysis |

#### `/finance:variance-analysis`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 48 | `/finance:variance-analysis Our COGS came in $200K over budget this quarter. Break down why.` | Decomposes variance into price, volume, mix, and efficiency components with waterfall visualization and narrative explanations for each driver |

#### `/finance:sox-testing`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 49 | `/finance:sox-testing Design SOX test procedures for our revenue recognition controls. We have automated and manual controls.` | Produces SOX 404 test plan with control descriptions, testing methodology, sample sizes, evidence requirements, and documentation templates |

### Skills

#### Financial Statements (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 50 | `Generate a balance sheet as of March 31, 2026 with proper GAAP classification of current vs non-current items.` | Loads financial-statements skill, produces formatted balance sheet with proper classifications, subtotals, and key liquidity/solvency ratios |

#### Close Management (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 51 | `Help me build a month-end close checklist. We're a SaaS company with 3 entities and intercompany transactions.` | Loads close-management skill, generates sequenced close checklist with task dependencies, owners, deadlines, and status tracking |

#### Audit Support (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 52 | `Our auditors just sent their PBC list for year-end. Help me organize and track the document requests.` | Loads audit-support skill, creates organized PBC tracking with document categories, responsible parties, deadlines, and completion status |

---

## 5. Legal

**Plugin:** `legal` v1.0.0
**Skills:** 6 | **Commands:** 5 | **MCP Servers:** 5 (slack, box, egnyte, atlassian, ms365)

### Commands

#### `/legal:review-contract`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 53 | `/legal:review-contract Review this SaaS services agreement. Flag any non-standard terms, especially around liability caps, indemnification, and data processing. [paste contract text]` | Performs clause-by-clause analysis, flags deviations from standard terms, generates redline suggestions, provides business impact assessment for each flagged item |

#### `/legal:triage-nda`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 54 | `/legal:triage-nda Review this incoming mutual NDA from a potential partner. [paste NDA text]` | Classifies as GREEN/YELLOW/RED, checks mutual obligations, definition scope, carve-outs, residuals, non-solicitation, governing law, and provides summary with action needed |

#### `/legal:brief`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 55 | `/legal:brief Prepare a legal briefing on the implications of the new EU AI Act for our SaaS product that uses machine learning for content recommendations.` | Produces structured legal brief with regulatory summary, applicability analysis, compliance requirements, risk assessment, and recommended actions |

#### `/legal:respond`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 56 | `/legal:respond Draft a response to a cease and desist letter claiming our product name infringes on their trademark.` | Drafts a measured legal response addressing the claims, presenting counter-arguments, and proposing resolution options |

#### `/legal:vendor-check`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 57 | `/legal:vendor-check We're evaluating a new cloud infrastructure vendor. Review their MSA and DPA for any concerning terms.` | Reviews vendor agreement for standard vs non-standard terms, data protection adequacy, security commitments, and SLA specifics |

### Skills

#### Contract Review (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 58 | `We just received a 30-page enterprise license agreement from Oracle. Can you review it and highlight the key risk areas?` | Loads contract-review skill, performs systematic clause analysis (liability, indemnification, IP, data protection, termination), flags deviations, suggests negotiation positions |

#### NDA Triage (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 59 | `We have 5 NDAs that came in this week from potential partners. Screen them quickly and tell me which ones I can sign vs which need deeper review.` | Loads nda-triage skill, classifies each NDA using GREEN/YELLOW/RED framework, provides summary table with key concerns per NDA |

#### Compliance (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 60 | `We're expanding to Germany. What GDPR considerations do we need for our data processing of EU customer data?` | Loads compliance skill, outlines GDPR requirements (lawful basis, DPA, cross-border transfers, DPIA), assesses current gaps, recommends compliance roadmap |

#### Legal Risk Assessment (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 61 | `Assess the legal risk of launching a feature that scrapes publicly available job postings for our market intelligence product.` | Loads legal-risk-assessment skill, evaluates risk on severity-by-likelihood matrix, considers CFAA, ToS violations, copyright, data protection, provides risk rating with mitigation steps |

#### Canned Responses (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 62 | `A customer is asking for a copy of our SOC 2 report. Draft a standard response.` | Loads canned-responses skill, generates appropriate template response with NDA requirement, document handling instructions, and follow-up process |

---

## 6. Marketing

**Plugin:** `marketing` v1.0.0
**Skills:** 5 | **Commands:** 7 | **MCP Servers:** 9 (slack, canva, figma, hubspot, amplitude, notion, ahrefs, similarweb, klaviyo)

### Commands

#### `/marketing:draft-content`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 63 | `/marketing:draft-content Write a 1,500-word blog post about "Why Real-Time Data Pipelines Are the Future of Analytics" targeting data engineering leaders.` | Drafts SEO-optimized blog post with proper structure (H2/H3), brand voice, keyword integration, meta description, and social sharing snippets |
| 64 | `/marketing:draft-content Create a LinkedIn post announcing our Series B fundraise. Tone: excited but professional.` | Produces platform-optimized LinkedIn post with appropriate length, hashtags, engagement hooks, and brand voice |

#### `/marketing:campaign-plan`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 65 | `/marketing:campaign-plan Plan a product launch campaign for our new enterprise tier. Budget: $50K. Timeline: 6 weeks. Target: VP/C-level at companies with 500+ employees.` | Generates full campaign brief with objectives, audience segments, channel strategy, content calendar, budget allocation, and KPIs |

#### `/marketing:brand-review`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 66 | `/marketing:brand-review Review this landing page copy for brand consistency. [paste copy]` | Checks against brand voice guidelines, messaging pillars, tone, and style standards; flags inconsistencies and suggests revisions |

#### `/marketing:email-sequence`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 67 | `/marketing:email-sequence Create a 5-email nurture sequence for trial users who haven't converted after 7 days.` | Produces email sequence with subject lines, body copy, send timing, personalization tokens, and A/B test suggestions |

#### `/marketing:performance-report`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 68 | `/marketing:performance-report Analyze our Q1 marketing performance across paid search, organic, and email channels.` | Generates performance report with channel-by-channel metrics, trend analysis, ROI calculations, and optimization recommendations |

#### `/marketing:competitive-brief`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 69 | `/marketing:competitive-brief Prepare a competitive analysis of our top 3 competitors' content marketing strategies.` | Produces competitive brief with content volume, channel presence, messaging analysis, SEO comparison, and strategic gaps/opportunities |

#### `/marketing:seo-audit`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 70 | `/marketing:seo-audit Audit our blog's SEO performance. Our domain is example.com and we target "data pipeline" keywords.` | Generates SEO audit covering keyword rankings, content gaps, technical SEO issues, backlink profile, and prioritized optimization plan |

### Skills

#### Content Creation (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 71 | `Write a case study about how Company X reduced data processing time by 80% using our product.` | Loads content-creation skill, produces structured case study with challenge/solution/results framework, customer quotes, and metrics |

#### Campaign Planning (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 72 | `We need to plan our presence at AWS re:Invent. What should our integrated campaign look like?` | Loads campaign-planning skill, creates event-centered campaign with pre/during/post activities, content needs, lead capture strategy, and ROI targets |

#### Brand Voice (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 73 | `Our CEO's keynote transcript needs to be turned into 10 social posts. Make sure they match our brand voice.` | Loads brand-voice skill, produces social posts with consistent tone, messaging pillars, and platform-appropriate formatting |

#### Competitive Analysis (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 74 | `How does our pricing page compare to our top 3 competitors? What are they doing better?` | Loads competitive-analysis skill, analyzes positioning, pricing transparency, feature presentation, social proof, and CTA effectiveness across competitors |

#### Performance Analytics (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 75 | `Our email open rates dropped from 35% to 22% over the last 3 months. Help me diagnose why and what to do about it.` | Loads performance-analytics skill, investigates potential causes (deliverability, list hygiene, subject lines, send time), recommends data-driven improvements |

---

## 7. Product Management

**Plugin:** `product-management` v1.0.0
**Skills:** 6 | **Commands:** 6 | **MCP Servers:** 12 (slack, linear, asana, monday, clickup, atlassian, notion, figma, amplitude, pendo, intercom, fireflies)

### Commands

#### `/product-management:write-spec`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 76 | `/product-management:write-spec Write a PRD for adding real-time collaboration to our document editor. Users have been requesting this for 6 months.` | Generates structured PRD with problem statement, user stories, requirements (P0/P1/P2), success metrics, technical considerations, and launch criteria |

#### `/product-management:synthesize-research`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 77 | `/product-management:synthesize-research We conducted 12 user interviews about our onboarding flow. Here are the key notes: [paste notes]. Synthesize the findings.` | Produces research synthesis with themes, user personas, pain point taxonomy, opportunity areas, and prioritized recommendations |

#### `/product-management:competitive-brief`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 78 | `/product-management:competitive-brief Analyze Notion, Coda, and Confluence as competitors to our knowledge management product.` | Generates feature comparison matrix, positioning analysis, pricing comparison, and strategic implications with recommended differentiation areas |

#### `/product-management:metrics-review`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 79 | `/product-management:metrics-review Review our product metrics for the last quarter. Key metrics: DAU, retention, activation rate, NPS.` | Produces metrics review with trend analysis, cohort comparisons, goal tracking, anomaly detection, and recommended focus areas |

#### `/product-management:roadmap-update`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 80 | `/product-management:roadmap-update We need to re-prioritize our Q2 roadmap. We lost 2 engineers and have a new enterprise customer requirement.` | Generates updated roadmap with re-prioritized items using RICE/MoSCoW, dependency mapping, resource allocation, and stakeholder communication plan |

#### `/product-management:stakeholder-update`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 81 | `/product-management:stakeholder-update Draft a monthly product update for the executive team. Key highlights: launched 2 features, improved activation by 15%, delayed API v2 by 3 weeks.` | Produces executive-appropriate update with highlights, metrics, risks, and next month outlook tailored to C-level audience |

### Skills

#### Feature Spec (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 82 | `I need to spec out a notification system for our app. Users should be able to set preferences and receive alerts via email, push, and in-app.` | Loads feature-spec skill, generates structured PRD with user stories, acceptance criteria, edge cases, and implementation considerations |

#### User Research Synthesis (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 83 | `I have survey results from 500 users about their satisfaction with our search feature. Help me make sense of the data.` | Loads user-research-synthesis skill, produces thematic analysis, sentiment distribution, key quotes, and actionable recommendations |

#### Roadmap Management (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 84 | `Help me prioritize these 15 feature requests using a structured framework. I'll give you the list with rough effort estimates.` | Loads roadmap-management skill, applies RICE or ICE scoring, produces prioritized backlog with justifications and quick wins identified |

#### Stakeholder Comms (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 85 | `I need to communicate a 4-week delay on our biggest feature to the CEO, the engineering team, and our biggest customer. Help me tailor the message for each audience.` | Loads stakeholder-comms skill, produces three distinct communications tailored to executive (strategic impact), engineering (technical context), and customer (timeline + commitment) |

---

## 8. Enterprise Search

**Plugin:** `enterprise-search` v1.0.0
**Skills:** 3 | **Commands:** 2 | **MCP Servers:** 6 (slack, notion, guru, atlassian, asana, ms365)

### Commands

#### `/enterprise-search:search`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 86 | `/enterprise-search:search What was decided about the pricing change in last week's leadership meeting?` | Decomposes query, searches across connected sources (email, chat, docs, wiki), synthesizes findings with source attribution and confidence scores |
| 87 | `/enterprise-search:search Find all documents and discussions related to our GDPR compliance project from the last 3 months.` | Runs parallel searches across all sources, deduplicates results, presents chronological summary with links to original documents |

#### `/enterprise-search:digest`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 88 | `/enterprise-search:digest Generate my weekly digest for the past 5 business days.` | Produces digest with categorized activity: action items assigned to user, key decisions made, documents updated, mentions, and upcoming deadlines |

### Skills

#### Search Strategy (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 89 | `I need to find out who owns the API rate limiting decision and what the current status is. It could be in Slack, Jira, or Confluence.` | Loads search-strategy skill, decomposes into targeted sub-queries per source, orchestrates parallel searches, and synthesizes cross-source findings |

#### Knowledge Synthesis (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 90 | `Compile everything we know about our biggest customer's renewal coming up next month. Check email, Slack, CRM notes, and meeting recordings.` | Loads knowledge-synthesis skill, aggregates and deduplicates information across sources, presents with confidence scoring and source attribution |

#### Source Management (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 91 | `What data sources do I currently have connected? Are there any I should add to get better search results?` | Loads source-management skill, lists connected MCP sources, identifies gaps based on common enterprise tools, recommends priority connections |

---

## 9. Bio Research

**Plugin:** `bio-research` v1.0.0
**Skills:** 5 | **Commands:** 1 | **MCP Servers:** 10 (pubmed, biorender, biorxiv, c-trials, chembl, synapse, wiley, owkin, ot, benchling)

### Commands

#### `/bio-research:start`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 92 | `/bio-research:start` | Initializes the bio-research environment, lists available MCP tools (PubMed, clinical trials, ChEMBL, etc.), and guides user through available capabilities |

### Skills

#### Single-Cell RNA QC (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 93 | `I have a 10X Genomics single-cell RNA-seq dataset in .h5ad format. Run quality control and filter out low-quality cells.` | Loads single-cell-rna-qc skill, performs MAD-based QC filtering (mitochondrial %, gene counts, UMI counts), generates QC plots, and outputs filtered dataset |

#### scvi-tools (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 94 | `I have single-cell data from 3 different batches. Help me integrate them using scVI for batch correction.` | Loads scvi-tools skill, sets up scVI model for batch integration, trains the model, and generates UMAP visualizations showing before/after batch correction |

#### Nextflow Development (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 95 | `I need to run an RNA-seq analysis pipeline on my FASTQ files using nf-core/rnaseq. Help me set it up.` | Loads nextflow-development skill, configures nf-core/rnaseq pipeline with appropriate parameters, sample sheet format, and execution instructions |

#### Scientific Problem Selection (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 96 | `I'm a postdoc trying to decide between two research directions: CRISPR-based gene therapy for rare diseases vs. developing new base editors. Help me think through this decision.` | Loads scientific-problem-selection skill, facilitates structured decision-making covering novelty, feasibility, impact, career implications, and competitive landscape |

#### Instrument Data to Allotrope (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 97 | `I have UV-Vis spectrophotometer output as a CSV file. Convert it to the Allotrope Simple Model JSON format for our LIMS.` | Loads instrument-data-to-allotrope skill, parses instrument output, maps fields to ASM schema, and produces standardized JSON output |

---

## 10. Productivity

**Plugin:** `productivity` v1.0.0
**Skills:** 2 | **Commands:** 2 | **MCP Servers:** 8 (slack, notion, asana, linear, atlassian, ms365, monday, clickup)

### Commands

#### `/productivity:start`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 98 | `/productivity:start` | Initializes productivity system: creates TASKS.md and CLAUDE.md files, connects to available tools (calendar, email, task managers), presents dashboard overview |

#### `/productivity:update`
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 99 | `/productivity:update Sync my tasks and show me what I need to focus on today.` | Scans connected tools for updates, syncs task status, highlights overdue items, shows calendar conflicts, and produces prioritized daily plan |
| 100 | `/productivity:update --comprehensive Rebuild context from all my connected tools.` | Performs deep scan across all sources, rebuilds working memory, identifies patterns in commitments, and flags anything that needs attention |

### Skills

#### Task Management (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 101 | `I have 8 things I need to get done this week. Help me organize and prioritize them.` | Loads task-management skill, creates structured TASKS.md with prioritized items, effort estimates, and suggested daily breakdown |
| 102 | `Mark the API documentation task as done and add a new task for reviewing PRs.` | Loads task-management skill, updates TASKS.md with completion and new entry, recalculates priorities |

#### Memory Management (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 103 | `Remember that our team standup is at 9:30am, our sprint is 2 weeks, and "Tiger Team" refers to the incident response group.` | Loads memory-management skill, stores context in CLAUDE.md working memory with appropriate categorization (schedule, process, terminology) |
| 104 | `What do you remember about my project deadlines and team structure?` | Loads memory-management skill, retrieves and presents stored context from CLAUDE.md and memory directory |

---

## 11. Cowork Plugin Management

**Plugin:** `cowork-plugin-management` v0.2.1
**Skills:** 2 | **Commands:** 0 | **MCP Servers:** 0

### Skills

#### Cowork Plugin Customizer (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 105 | `I want to customize the sales plugin to match our company's sales methodology (MEDDPICC instead of BANT). How do I modify the skills?` | Loads cowork-plugin-customizer skill, guides through plugin customization: discovering available schemas, updating reference materials, and adjusting skill configurations |
| 106 | `The customer-support plugin references tools we don't use (Intercom). How do I reconfigure it for Zendesk instead?` | Provides step-by-step MCP server reconfiguration guidance, updates .mcp.json references, and adjusts skill instructions accordingly |

#### Create Cowork Plugin (auto-activated)
| # | Test Query | Expected Behavior |
|---|-----------|-------------------|
| 107 | `Create a new plugin for our DevOps team that helps with incident response, runbook management, and post-mortem writing.` | Loads create-cowork-plugin skill, generates plugin scaffold with plugin.json manifest, SKILL.md files for each capability, command templates, and .mcp.json for relevant tools |
| 108 | `I want to build a custom HR plugin with skills for writing job descriptions, screening resumes, and preparing interview guides.` | Creates complete plugin structure from template with properly formatted skills, commands, and configuration files |

---

## Testing Checklist

### Per-Query Verification

For each test query, verify:

- [ ] **Skill/Command Discovery** — Agent identifies and loads the correct skill or command
- [ ] **Progressive Loading** — Agent reads SKILL.md via `read_file` before executing
- [ ] **Instruction Following** — Agent follows the workflow defined in the skill/command
- [ ] **Output Format** — Response matches the expected format (structured data, markdown, HTML artifact, etc.)
- [ ] **MCP Tool Usage** — If MCP servers are connected, agent attempts to use relevant tools
- [ ] **Graceful Degradation** — Without MCP servers, agent falls back to web search or asks for manual input
- [ ] **Error Handling** — Malformed input produces helpful error messages, not crashes

### System-Level Verification

- [ ] **Plugin Loading** — `GET /api/plugins` returns all 11 plugins with correct metadata
- [ ] **Skill Injection** — System prompt `<skill_system>` section includes plugin skills
- [ ] **Command Injection** — System prompt `<command_system>` section lists all 42 commands
- [ ] **Enable/Disable** — `PUT /api/plugins/{name}` toggles plugin and its skills/commands
- [ ] **MCP Namespace** — Plugin MCP servers appear namespaced (e.g., `sales:hubspot`)
- [ ] **No Regressions** — Existing public/custom skills continue to work unchanged
