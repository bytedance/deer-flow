---
description: Run a comprehensive SEO audit — keyword research, on-page analysis, content gaps, technical checks, and competitor comparison
argument-hint: "<url or topic> [audit type]"
---

# /seo-audit

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Audit a website's SEO health, research keyword opportunities, identify content gaps, and benchmark against competitors. Produces a prioritized action plan a marketer can execute immediately.

## Trigger

User runs `/seo-audit` or asks for an SEO audit, keyword research, content gap analysis, technical SEO check, or competitor SEO comparison.

## Inputs

Gather the following from the user. If not provided, ask before proceeding:

1. **URL or domain** — the site to audit, or a topic/keyword if running in keyword research mode

2. **Audit type** — one of:
   - **Full site audit** — end-to-end SEO review covering all sections below
   - **Keyword research** — identify keyword opportunities for a topic or domain
   - **Content gap analysis** — find topics competitors rank for that you don't
   - **Technical SEO check** — crawlability, speed, structured data, and infrastructure issues
   - **Competitor SEO comparison** — head-to-head SEO benchmarking against specific competitors

   If not specified, default to **full site audit**.

3. **Target keywords or topics** (optional) — specific keywords the user is already targeting or wants to rank for

4. **Competitors** (optional) — domains or companies to compare against. If not provided and the audit type requires competitor data, use web search to identify 2-3 likely competitors based on the user's domain and keyword space.

## Process

### 1. Keyword Research

Research keywords related to the user's domain, topic, or target keywords.

**If ~~SEO tools are connected:**
- Pull keyword data, search volume, keyword difficulty scores, and ranking positions automatically
- Identify keywords the site currently ranks for and where it's gaining or losing ground

**If ~~product analytics are connected:**
- Cross-reference keyword targets with actual organic traffic data to validate which keywords are driving visits and conversions

**If tools are not connected:**
- Use web search to research the keyword landscape
- Note: "For more precise volume and difficulty data, connect an SEO tool like Ahrefs or Semrush via MCP. The audit will auto-populate with ranking data."

For each keyword opportunity, assess:
- **Primary keywords** — high-intent terms directly tied to the user's product or service
- **Secondary keywords** — supporting terms and variations
- **Search volume signals** — relative demand (high, medium, low) based on available data
- **Keyword difficulty** — how competitive the term is (easy, moderate, hard)
- **Long-tail opportunities** — specific, lower-competition phrases with clear intent
- **Question-based keywords** — "how to", "what is", "why does" queries that mirror People Also Ask results
- **Intent classification** — informational, navigational, commercial, or transactional

### 2. On-Page SEO Audit

For each key page (homepage, top landing pages, recent blog posts), evaluate:

- **Title tags** — present, unique, within 50-60 characters, includes target keyword
- **Meta descriptions** — present, compelling, within 150-160 characters, includes a call to action
- **H1 tags** — exactly one per page, includes primary keyword
- **H2/H3 structure** — logical hierarchy, uses secondary keywords where natural
- **Keyword usage** — primary keyword appears in the first 100 words, used naturally throughout, not over-stuffed
- **Internal linking** — pages link to related content, orphan pages identified, anchor text is descriptive
- **Image alt text** — all images have descriptive alt attributes, keywords included where relevant
- **URL structure** — clean, readable, includes keywords, no excessive parameters or depth

### 3. Content Gap Analysis

Identify what's missing from the user's content strategy:

- **Competitor topic coverage** — topics and keywords competitors rank for that the user's site does not cover
- **Content freshness** — pages that haven't been updated in 12+ months and may be losing rankings
- **Thin content** — pages with insufficient depth to rank (under 300 words for informational queries, lacking substance)
- **Missing content types** — formats competitors use that the user doesn't (guides, comparison pages, glossaries, tools, templates)
- **Funnel gaps** — missing content at specific buyer journey stages (awareness, consideration, decision)
- **Topic clusters** — opportunities to build pillar pages with supporting content

### 4. Technical SEO Checklist

Evaluate technical foundations that affect crawlability and rankings:

- **Page speed** — identify slow-loading pages and likely causes (large images, render-blocking scripts, excessive redirects)
- **Mobile-friendliness** — responsive design, tap targets, font sizes, viewport configuration
- **Structured data** — opportunities for schema markup (FAQ, HowTo, Product, Article, Organization, Breadcrumb)
- **Crawlability** — robots.txt configuration, XML sitemap presence and accuracy, canonical tags, noindex/nofollow usage
- **Broken links** — internal and external 404s, redirect chains
- **HTTPS** — secure connection, mixed content issues
- **Core Web Vitals signals** — LCP, FID/INP, CLS indicators based on observable page behavior
- **Indexation** — pages that should be indexed but may not be, duplicate content risks

### 5. Competitor SEO Comparison

For each competitor, compare:

- **Keyword overlap** — keywords both sites rank for, and where each site ranks higher
- **Keyword gaps** — terms the competitor ranks for that the user does not
- **Domain authority signals** — relative site strength based on backlink profiles, referring domains, and content depth
- **Content depth** — average content length, topic coverage breadth, publishing frequency
- **Backlink profile observations** — types of sites linking to competitors, link-worthy content they've produced
- **SERP feature ownership** — which competitor appears in featured snippets, People Also Ask, image packs, or knowledge panels
- **Technical advantages** — site speed differences, mobile experience, structured data usage

## Output

### Executive Summary

Open with a 3-5 sentence summary of overall SEO health. Highlight:
- The site's biggest strength
- The top 3 priorities that will have the most impact
- An overall assessment: strong foundation, needs work, or critical issues

### Keyword Opportunity Table

| Keyword | Est. Difficulty | Opportunity Score | Current Ranking | Intent | Recommended Content Type |
|---------|----------------|-------------------|-----------------|--------|--------------------------|

Opportunity score: high, medium, or low — based on the combination of search demand, difficulty, and relevance to the user's business.

Include 15-25 keyword opportunities, sorted by opportunity score.

### On-Page Issues Table

| Page | Issue | Severity | Recommended Fix |
|------|-------|----------|-----------------|

Severity levels:
- **Critical** — directly hurting rankings or preventing indexation
- **High** — significant impact on SEO performance
- **Medium** — best practice violation, moderate impact
- **Low** — minor optimization opportunity

### Content Gap Recommendations

For each content gap identified, provide:
- **Topic or keyword** to target
- **Why it matters** — search demand, competitor coverage, funnel stage
- **Recommended format** — blog post, landing page, guide, comparison page, etc.
- **Priority** — high, medium, or low
- **Estimated effort** — quick win (1-2 hours), moderate (half day), substantial (multi-day)

### Technical SEO Checklist

| Check | Status | Details |
|-------|--------|---------|

Status: Pass, Fail, or Warning.

### Competitor Comparison Summary

| Dimension | Your Site | Competitor A | Competitor B | Winner |
|-----------|-----------|--------------|--------------|--------|

Include rows for: keyword count, content depth, publishing frequency, backlink signals, technical score, SERP feature presence.

### Prioritized Action Plan

Split recommendations into two categories:

**Quick Wins (do this week):**
- Actions that take under 2 hours and have immediate impact
- Examples: fix title tags, add meta descriptions, fix broken links, add alt text

**Strategic Investments (plan for this quarter):**
- Actions that require more effort but drive long-term growth
- Examples: build a topic cluster, create a pillar page, launch a link-building campaign, overhaul site structure

For each action item, include:
- What to do (specific and concrete)
- Expected impact (high, medium, low)
- Effort estimate
- Dependencies (if any)

## Follow-Up

After presenting the audit, ask:

"Would you like me to:
- Draft content briefs for the top keyword opportunities?
- Create optimized title tags and meta descriptions for your key pages?
- Build a content calendar based on the gap analysis?
- Dive deeper into any specific section of the audit?
- Run this same analysis for a different competitor or domain?"
