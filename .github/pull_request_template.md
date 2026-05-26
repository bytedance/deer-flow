<!-- Reference a related issue with #123. Use Fixes / Closes / Resolves to
     auto-close it on merge. Delete this line if the PR doesn't reference an issue. -->
Fixes #

## Why

<!-- Why are you opening this PR? Cover two things:
       - The trigger — what made you write this? A bug you hit, a feature you need,
         tech debt, or a prod issue?
       - The pain being addressed — user-facing problem, or what it unblocks.
     For non-trivial features, please open an issue/discussion first to align on
     scope before writing code. -->


## What changed

<!-- Describe the change from a user's / caller's perspective, not as a code diff. e.g.:
       - "Settings now has a 'Custom endpoint' field, off by default"
       - "Backend /api/chat gains a `stream` flag, defaults to false"
       - "Default model changed from X to Y — existing users notice on first run" -->


## Surface area

<!-- Check every box that applies. Reviewers use this to scope the review. -->

- [ ] **Frontend UI** — page / component / setting / interaction under `frontend/`
- [ ] **Backend API** — endpoint / SSE event / request-response shape under `backend/app`
- [ ] **Agents / LangGraph** — agent node, graph wiring, `langgraph.json`, or prompt change
- [ ] **Sandbox** — `docker/` or sandboxed execution
- [ ] **Skills** — change under `skills/`
- [ ] **Dependencies** — new/upgraded entry in `backend/pyproject.toml` or `frontend/package.json` (say what it buys us)
- [ ] **Default behavior change** — changes existing behavior without the user opting in (default model, default setting, data shape)
- [ ] **Docs / tests / CI only** — no runtime behavior change


## Screenshots / Recording

<!-- If you checked "Frontend UI", attach screenshots showing the entry point —
     where users discover the change — not just the feature in isolation.
     Before/after is best for behavior changes. Short GIFs welcome. -->


## Bug fix verification

<!-- Skip (delete) this section if this PR is not a bug fix.

     Bugs should be encoded as a failing test that goes red before the fix.
     Confirm:
       - Test path that reproduces the bug:
       - Did it go red on `main` and green on this branch? (yes / no)
       - If a red test wasn't cheap to write, explain why and what you did instead. -->


## Validation

<!-- What you actually ran. Run at least the checks for the area you changed:
       Backend:   cd backend  && make lint && make test
       Frontend:  cd frontend && pnpm format && pnpm lint && pnpm typecheck && BETTER_AUTH_SECRET=local-dev-secret pnpm build && make test
       Frontend E2E (if you touched frontend/): cd frontend && make test-e2e -->

