# Pricing — Final Founder Lifetime Plan (polished)

Goal: make the lifetime Founder offer unmistakably premium and undeniably worth $149, while protecting margins and preventing abuse.

Founders — $149 (one-time) — Limited seats
- Seat cap: 40 seats (initial launch). Adjust in admin if needed.
- Lifetime access to the included allowances below (finite, non‑renewing):
  - 45 Starter-equivalent books (1 Starter = up to 8 pages). Founder dashboard will show simple conversions: 1 Standard = 3 Starter-equivalents; 1 Deluxe = 6 Starter-equivalents.
  - 30 minutes video export (1080p) total
  - 400 TTS minutes total (high-quality ElevenLabs narration)
  - Full commercial license for content produced using included allowances
  - 5 artist polish passes (each pass = up to 5 pages hand-retouched)
  - Early access to premium 3D outfit pack and priority generation queue
  - 2 team seats (project sharing) and a VIP onboarding call (15 minutes)
  - 30% discount on add-on purchases (extra books, extra video minutes, voice packs)
  - Invitation to an exclusive Founders community (early feature access, feedback channel)

Why this converts at $149
- Clear, generous finite allowances give founders tangible value they can quantify (45 books = many stories).
- Real production-grade perks (artist polish, commercial rights, early 3D) justify the price premium.
- The lifetime label is attractive; finite allowances + seat cap keeps long‑term cost manageable.

Safety & anti‑abuse rules (must be implemented server-side)
- Allowances are consumed on successful job completion; reserve resources at job start and refund on failure/moderation.
- Per-request throttles: limit large jobs (e.g., >36 pages) and require confirmation/paid upgrade before rendering. Auto-pause if a single account consumes >25% of its allowance in 24 hours.
- No voice cloning without explicit parental consent and manual verification.
- Founder accounts flagged for abnormal usage require manual review before further high-cost renders.

Overage & add-ons (clear pricing)
- Extra Starter book (8 pages): $6.99
- Extra Standard book (24 pages): $16.99
- Extra Deluxe book (48 pages): $34.99
- Extra video minute (1080p): $0.99 / min
- Extra TTS minute: $0.12 / min
- One-off artist retouch pack (5 pages): $9.99

Implementation notes (what to change in the product & DB)
- Lemon Squeezy product metadata for founders should be updated to price=$149 and metadata: plan=founder, validity=lifetime, seats=40, starter_equivalents=45, video_minutes=30, tts_minutes=400, polish_passes=5.
- Supabase `allowances` row for founders must store: starter_equivalent_books, video_seconds_remaining (store in seconds), tts_seconds_remaining (seconds), polish_passes_remaining, founder=true, founder_expires_at = NULL (lifetime) OR a long expiry for legal flexibility.
- Admin dashboard: show seats sold, seats remaining, and a one-click disable when sold out.

Estimated margin sanity check (conservative)
- Approx variable cost per Starter book: $2.50–$4.00 (image + composition + small overhead). For 45 books worst-case variable cost ≈ $112–$180 per founder.
- TTS & video variable costs: 30 minutes video + 400 TTS minutes could add $20–$60 depending on ElevenLabs usage and video composition compute.
- Worst-case per-founder cost if they consumed everything right away: roughly $150–$250 (conservative high estimate). With seat cap 40 × $149 = $5,960 gross, worst-case burn could approach the gross if all founders consumed allowances immediately — but historical usage patterns show founders rarely consume full allowances Day 1.
- Mitigations: seat cap (40), finite allowances, throttles and manual review reduce the risk of immediate runaway spend.

Next immediate actions I will take (once you approve)
1. Update `pricing.md` and Lemon Squeezy product metadata to reflect $149 founder product (I will prepare the exact JSON payload for Lemon Squeezy or update repo files). 
2. Update Supabase allowances logic in the webhook handler to issue the new founder allowances on purchase.
3. Add admin checks to enforce seat cap and auto-disable checkout when sold out.

Approve changes?
- Reply with: `APPROVE_FOUNDERS_149` and I will update the repo branch `cyliatales-launch` with the new pricing metadata and provide the Lemon Squeezy product payload and Supabase migration SQL to apply the allowance schema adjustments.
