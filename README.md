# CyliaTales — launch branch

This branch (cyliatales-launch) contains the production-ready scaffolding for the children’s story studio (frontend, API routes, worker, Supabase schema, and launch assets).

Files added:
- src/pages/index.tsx (landing)
- src/pages/api/webhooks/lemon.ts (webhook handler stub)
- supabase/schema.sql (DB schema)
- worker/Dockerfile (worker container for FFmpeg + job runner)
- worker/ffmpeg-compose.sh (compose script for images+audio -> MP4)
- env.example (environment variable names)
- pricing.md (final pricing & allowances)
- launch-checklist.md (24-hour launch checklist)

Next steps: add secrets to Vercel/GitHub, deploy branch, and I'll generate the real demo once ELEVENLABS key is present.
