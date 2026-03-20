---
name: competitive-intelligence
description: Research your competitors and build an interactive battlecard. Outputs an HTML artifact with clickable competitor cards and a comparison matrix. Trigger with "competitive intel", "research competitors", "how do we compare to [competitor]", "battlecard for [competitor]", or "what's new with [competitor]".
---

# Competitive Intelligence

Research your competitors extensively and generate an **interactive HTML battlecard** you can use in deals. The output is a self-contained artifact with clickable competitor tabs and an overall comparison matrix.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                  COMPETITIVE INTELLIGENCE                        │
├─────────────────────────────────────────────────────────────────┤
│  ALWAYS (works standalone via web search)                        │
│  ✓ Competitor product deep-dive: features, pricing, positioning │
│  ✓ Recent releases: what they've shipped in last 90 days        │
│  ✓ Your company releases: what you've shipped to counter        │
│  ✓ Differentiation matrix: where you win vs. where they win     │
│  ✓ Sales talk tracks: how to position against each competitor   │
│  ✓ Landmine questions: expose their weaknesses naturally        │
├─────────────────────────────────────────────────────────────────┤
│  OUTPUT: Interactive HTML Battlecard                             │
│  ✓ Comparison matrix overview                                    │
│  ✓ Clickable tabs for each competitor                           │
│  ✓ Dark theme, professional styling                             │
│  ✓ Self-contained HTML file — share or host anywhere            │
├─────────────────────────────────────────────────────────────────┤
│  SUPERCHARGED (when you connect your tools)                      │
│  + CRM: Win/loss data, competitor mentions in closed deals      │
│  + Docs: Existing battlecards, competitive playbooks            │
│  + Chat: Internal intel, field reports from colleagues          │
│  + Transcripts: Competitor mentions in customer calls           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

When you run this skill, I'll ask for context:

**Required:**
- What company do you work for? (or I'll detect from your email)
- Who are your main competitors? (1-5 names)

**Optional:**
- Which competitor do you want to focus on first?
- Any specific deals where you're competing against them?
- Pain points you've heard from customers about competitors?

If I already have your seller context from a previous session, I'll confirm and skip the questions.

---

## Connectors (Optional)

| Connector | What It Adds |
|-----------|--------------|
| **CRM** | Win/loss history against each competitor, deal-level competitor tracking |
| **Docs** | Existing battlecards, product comparison docs, competitive playbooks |
| **Chat** | Internal chat intel (e.g. Slack) — what your team is hearing from the field |
| **Transcripts** | Competitor mentions in customer calls, objections raised |

> **No connectors?** Web research works great. I'll pull everything from public sources — product pages, pricing, blogs, release notes, reviews, job postings.

---

## Output: Interactive HTML Battlecard

The skill generates a **self-contained HTML file** with:

### 1. Comparison Matrix (Landing View)
Overview comparing you vs. all competitors at a glance:
- Feature comparison grid
- Pricing comparison
- Market positioning
- Win rate indicators (if CRM connected)

### 2. Competitor Tabs (Click to Expand)
Each competitor gets a clickable card that expands to show:
- Company profile (size, funding, target market)
- What they sell and how they position
- Recent releases (last 90 days)
- Where they win vs. where you win
- Pricing intelligence
- Talk tracks for different scenarios
- Objection handling
- Landmine questions

### 3. Your Company Card
- Your releases (last 90 days)
- Your key differentiators
- Proof points and customer quotes

---

## HTML Structure

```html
<!DOCTYPE html>
<html>
<head>
    <title>Battlecard: [Your Company] vs Competitors</title>
    <style>
        /* Dark theme, professional styling */
        /* Tabbed navigation */
        /* Expandable cards */
        /* Responsive design */
    </style>
</head>
<body>
    <!-- Header with your company + date -->
    <header>
        <h1>[Your Company] Competitive Battlecard</h1>
        <p>Generated: [Date] | Competitors: [List]</p>
    </header>

    <!-- Tab Navigation -->
    <nav class="tabs">
        <button class="tab active" data-tab="matrix">Comparison Matrix</button>
        <button class="tab" data-tab="competitor-1">[Competitor 1]</button>
        <button class="tab" data-tab="competitor-2">[Competitor 2]</button>
        <button class="tab" data-tab="competitor-3">[Competitor 3]</button>
    </nav>

    <!-- Comparison Matrix Tab -->
    <section id="matrix" class="tab-content active">
        <h2>Head-to-Head Comparison</h2>
        <table class="comparison-matrix">
            <!-- Feature rows with you vs each competitor -->
        </table>

        <h2>Quick Win/Loss Guide</h2>
        <div class="win-loss-grid">
            <!-- Per-competitor: when you win, when you lose -->
        </div>
    </section>

    <!-- Individual Competitor Tabs -->
    <section id="competitor-1" class="tab-content">
        <div class="battlecard">
            <div class="profile"><!-- Company info --></div>
            <div class="differentiation"><!-- Where they win / you win --></div>
            <div class="talk-tracks"><!-- Scenario-based positioning --></div>
            <div class="objections"><!-- Common objections + responses --></div>
            <div class="landmines"><!-- Questions to ask --></div>
        </div>
    </section>

    <script>
        // Tab switching logic
        // Expand/collapse sections
    </script>
</body>
</html>
```

---

## Visual Design

### Color System
```css
:root {
    /* Dark theme base */
    --bg-primary: #0a0d14;
    --bg-elevated: #0f131c;
    --bg-surface: #161b28;
    --bg-hover: #1e2536;

    /* Text */
    --text-primary: #ffffff;
    --text-secondary: rgba(255, 255, 255, 0.7);
    --text-muted: rgba(255, 255, 255, 0.5);

    /* Accent (your brand or neutral) */
    --accent: #3b82f6;
    --accent-hover: #2563eb;

    /* Status indicators */
    --you-win: #10b981;
    --they-win: #ef4444;
    --tie: #f59e0b;
}
```

### Card Design
- Rounded corners (12px)
- Subtle borders (1px, low opacity)
- Hover states with slight elevation
- Smooth transitions (200ms)

### Comparison Matrix
- Sticky header row
- Color-coded winner indicators (green = you, red = them, yellow = tie)
- Expandable rows for detail

---

## Execution Flow

### Phase 1: Gather Seller Context

```
If first time:
1. Ask: "What company do you work for?"
2. Ask: "What do you sell? (product/service in one line)"
3. Ask: "Who are your main competitors? (up to 5)"
4. Store context for future sessions

If returning user:
1. Confirm: "Still at [Company] selling [Product]?"
2. Ask: "Same competitors, or any new ones to add?"
```

### Phase 2: Research Your Company (Always)

```
Web searches:
1. "[Your company] product" — current offerings
2. "[Your company] pricing" — pricing model
3. "[Your company] news" — recent announcements (90 days)
4. "[Your company] product updates OR changelog OR releases" — what you've shipped
5. "[Your company] vs [competitor]" — existing comparisons
```

### Phase 3: Research Each Competitor (Always)

```
For each competitor, run:
1. "[Competitor] product features" — what they offer
2. "[Competitor] pricing" — how they charge
3. "[Competitor] news" — recent announcements
4. "[Competitor] product updates OR changelog OR releases" — what they've shipped
5. "[Competitor] reviews G2 OR Capterra OR TrustRadius" — customer sentiment
6. "[Competitor] vs [alternatives]" — how they position
7. "[Competitor] customers" — who uses them
8. "[Competitor] careers" — hiring signals (growth areas)
```

### Phase 4: Pull Connected Sources (If Available)

```
If CRM connected:
1. Query closed-won deals with competitor field = [Competitor]
2. Query closed-lost deals with competitor field = [Competitor]
3. Extract win/loss patterns

If docs connected:
1. Search for "battlecard [competitor]"
2. Search for "competitive [competitor]"
3. Pull existing positioning docs

If chat connected:
1. Search for "[Competitor]" mentions (last 90 days)
2. Extract field intel and colleague insights

If transcripts connected:
1. Search calls for "[Competitor]" mentions
2. Extract objections and customer quotes
```

### Phase 5: Build HTML Artifact

```
1. Structure data for each competitor
2. Build comparison matrix
3. Generate individual battlecards
4. Create talk tracks for each scenario
5. Compile landmine questions
6. Render as self-contained HTML
7. Save as [YourCompany]-battlecard-[date].html
```

---

## Data Structure Per Competitor

```yaml
competitor:
  name: "[Name]"
  website: "[URL]"
  profile:
    founded: "[Year]"
    funding: "[Stage + amount]"
    employees: "[Count]"
    target_market: "[Who they sell to]"
    pricing_model: "[Per seat / usage / etc.]"
    market_position: "[Leader / Challenger / Niche]"

  what_they_sell: "[Product summary]"
  their_positioning: "[How they describe themselves]"

  recent_releases:
    - date: "[Date]"
      release: "[Feature/Product]"
      impact: "[Why it matters]"

  where_they_win:
    - area: "[Area]"
      advantage: "[Their strength]"
      how_to_handle: "[Your counter]"

  where_you_win:
    - area: "[Area]"
      advantage: "[Your strength]"
      proof_point: "[Evidence]"

  pricing:
    model: "[How they charge]"
    entry_price: "[Starting price]"
    enterprise: "[Enterprise pricing]"
    hidden_costs: "[Implementation, etc.]"
    talk_track: "[How to discuss pricing]"

  talk_tracks:
    early_mention: "[Strategy if they come up early]"
    displacement: "[Strategy if customer uses them]"
    late_addition: "[Strategy if added late to eval]"

  objections:
    - objection: "[What customer says]"
      response: "[How to handle]"

  landmines:
    - "[Question that exposes their weakness]"

  win_loss: # If CRM connected
    win_rate: "[X]%"
    common_win_factors: "[What predicts wins]"
    common_loss_factors: "[What predicts losses]"
```

---

## Delivery

```markdown
## ✓ Battlecard Created

[View your battlecard](file:///path/to/[YourCompany]-battlecard-[date].html)

---

**Summary**
- **Your Company**: [Name]
- **Competitors Analyzed**: [List]
- **Data Sources**: Web research [+ CRM] [+ Docs] [+ Transcripts]

---

**How to Use**
- **Before a call**: Open the relevant competitor tab, review talk tracks
- **During a call**: Reference landmine questions
- **After win/loss**: Update with new intel

---

**Sharing Options**
- **Local file**: Open in any browser
- **Host it**: Upload to Netlify, Vercel, or internal wiki
- **Share directly**: Send the HTML file to teammates

---

**Keep it Fresh**
Run this skill again to refresh with latest intel. Recommended: monthly or before major deals.
```

---

## Refresh Cadence

Competitive intel gets stale. Recommended refresh:

| Trigger | Action |
|---------|--------|
| **Monthly** | Quick refresh — new releases, news, pricing changes |
| **Before major deal** | Deep refresh for specific competitor in that deal |
| **After win/loss** | Update patterns with new data |
| **Competitor announcement** | Immediate update on that competitor |

---

## Tips for Better Intel

1. **Be honest about weaknesses** — Credibility comes from acknowledging where competitors are strong
2. **Focus on outcomes, not features** — "They have X feature" matters less than "customers achieve Y result"
3. **Update from the field** — Best intel comes from actual customer conversations, not just websites
4. **Plant landmines, don't badmouth** — Ask questions that expose weaknesses; never trash-talk
5. **Track releases religiously** — What they ship tells you their strategy and your opportunity

---

## Related Skills

- **account-research** — Research a specific prospect before reaching out
- **call-prep** — Prep for a call where you know competitor is involved
- **create-an-asset** — Build a custom comparison page for a specific deal
