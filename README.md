# CyliaTales

From idea to cinematic saga: instant, interactive, multimodal story creation with studio-grade visuals, characters, and publishing.

This repository is the scaffold for CyliaTales — a next-generation AI-first storytelling & character studio built to deliver studio-grade visuals, character consistency, parametric outfits, and end-to-end publishing & marketplace capabilities.

Goals
- Ship an MVP that enables a single creator to produce a short illustrated story (10 panels) with consistent characters and export it as PDF/web-preview.
- Build a Super-Agent orchestration layer for long-running creative sessions.
- Provide a developer-friendly scaffold for backend, frontend, infra, and product artifacts.

Structure
- backend/        — FastAPI app, agents, workers, model adapters
- frontend/       — Next.js app (editor shell and landing pages)
- infra/          — Terraform / deployment stubs
- docs/           — Product spec, ROADMAP, issues and templates
- .github/        — workflows and community files

Quick start (local dev, high level)
1. Clone the repo
2. Backend: cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt && uvicorn app.main:app --reload
3. Frontend: cd frontend && pnpm install && pnpm dev

Note: This scaffold contains minimal starter code and product artifacts. Follow docs/ROADMAP.md and docs/ISSUES.md to proceed with the prioritized MVP.

Maintainers: @hammouda202344
