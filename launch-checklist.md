24-hour launch checklist (priority order)

1) Create Lemon Squeezy products and webhook; set webhook to /api/webhooks/lemon and add secret to Vercel.
2) Add environment variables in Vercel (see env.example), deploy cyliatales-launch branch.
3) Deploy worker (Docker) with REDIS_URL and ensure ffmpeg worker can upload to Supabase storage.
4) Generate a real demo (requires OPENROUTER + ELEVENLABS keys). Upload demo MP4 to storage and embed on landing.
5) Send warm-list email and enable Founder checkout link. Monitor orders, seat counts, and model spend.

Operational safeguards:
- Reserve video seconds at job start; deduct on success.
- Throttle heavy jobs and require paid upgrade for >36 pages.
- Set alerts for daily model spend.
