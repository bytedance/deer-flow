CyliaTales Pricing & GTM — Lifetime Founders Plans

Overview
We will launch two limited "Founders Lifetime" plans to maximize early revenue and urgency while keeping product-market-fit and server-costs manageable.

Recommended Lifetime Plans (RECOMMENDED)
1) Founders Lifetime Basic — $199 one-time (limited to 300 seats)
   - Personal use: 1 active project (can create more by converting to Pro or paid add-ons)
   - 25 render credits/month for high-res exports (previews unlimited, low-res)
   - Access to core templates (MVP templates + 10 starter templates)
   - Access to 10 outfit packs (seeded)
   - Community access and updates (bug fixes, minor template additions)
   - Commercial license for small-scale sales (non-exclusive)

2) Founders Lifetime Pro — $799 one-time (limited to 100 seats)
   - Unlimited personal projects
   - 200 render credits/month for high-res exports
   - Access to full premium template library (60 templates) and 60 outfit packs
   - Priority support & 60-min onboarding call (white-glove session)
   - Commercial license, marketplace fast-track & revenue share priority
   - 2 invited collaborator seats (team access)

Why these prices
- $199 lowers friction for individual creators and early adopters; $799 positions Pro as premium with high perceived value and justifies the white-glove extras.
- Revenue scenarios (examples):
  - Conservative mix: 15 Pro ($799) + 20 Basic ($199) = 15*799 + 20*199 = $11,985 + $3,980 = $15,965
  - Modest mix: 10 Pro + 15 Basic = $7,990 + $2,985 = $10,975 (hits your $10k target)
  - High-conversion: 20 Pro = $15,980 (hits $15k)
- These limited-seat lifetime offers create scarcity and can be marketed as early founder pricing.

Alternative lower-price option (if you want easier conversion)
- Basic: $149, Pro: $499 — easier conversions but requires more volume to hit $10–15k.

Monetization add-ons
- Template bundles / Outfit packs: $19–$49 each (one-time)
- High-resolution render credits: additional credit packs ($10 for 10 credits)
- White-glove creation services: $1,500–$3,500 per project (fast revenue)

Payment & Licensing Platform: Lemon Squeezy
- We will use Lemon Squeezy for checkout, license generation, webhooks, and subscription management.
- Lemon Squeezy supports one-time products and license keys which is perfect for lifetime offerings.

Lemon Squeezy integration plan (technical steps)
1. Create products in Lemon Squeezy dashboard:
   - Product: Founders Lifetime Basic ($199) – SKU: CT-LTB-199
   - Product: Founders Lifetime Pro ($799) – SKU: CT-LTP-799
   - Optional: Template & Outfit packs
2. Configure checkout pages and set seat/quantity limits in product descriptions. Use Lemon Squeezy discounts for launch coupons.
3. Webhook endpoint in our backend: /webhooks/lemon
   - Verify webhook signature using Lemon Squeezy docs
   - On successful purchase event: create user account (or link to existing), mark license as active, grant entitlements (templates, credits, seats), send welcome email + onboarding instructions
4. Licensing & entitlement model: store Lemon purchase ID and license keys in our DB, map to user_id and entitlements. Implement license revocation endpoint.
5. Deliverables: purchase confirmation email with license key + quickstart guide (how to use credits, where to generate first story)

Promotion & Scarcity
- Publish launch limited to X seats, add seat counter on landing page.
- Early-bird coupon for first 48 hours to drive urgency.
- Offer 1–2 white-glove engagements to agencies (pay upfront) to secure early cash.

Launch play & KPIs
- Aim to convert 10–20% of waitlist signups to one-time founders purchases within first 30 days using targeted outreach + demos.
- Monitor: conversion rate, average order value, week 1 churn (refund requests), credit usage, and cost per render.

Next actions I’ll take now (if you confirm)
- Create Lemon Squeezy integration doc in repo (webhook skeleton + entitlement mapping)
- Add pricing page skeleton to frontend/landing markdown
- Create tracked GitHub issues for Sprint 0 (CI, S3 helper, Lemon Squeezy docs)

