# Scheduled-tasks page: full i18n + recipe templates — design

Follow-up to the preset-driven schedule form (commit `1ca27a73`). Scope kept
front-end only and backend-contract-free so it stays reviewable inside PR #3898.

## Background

The preset form i18n'd the schedule section but left the rest of the
scheduled-tasks page in hard-coded English (filters, detail pane, actions, edit
form, run list). A `zh-CN` user saw a half-English page right next to the
i18n'd schedule input. Separately, the page still required users to hand-write
prompts for the headline use cases (GitHub Trending, news digest, issue triage,
weekly report).

## Goals

1. Every visible string on `/workspace/scheduled-tasks` goes through
   `t.scheduledTasks.*` (en + zh).
2. One-click "quick create" via four built-in recipe templates that pre-fill
   title + prompt + schedule.
3. No backend change. No new dependency.

## Design

### Full i18n

Added to the `scheduledTasks` i18n section (types + en-US + zh-CN):

- `create`, `context`, `filters`, `detail`, `actions`, `edit` — UI labels.
- `status`, `runTrigger`, `runStatus` — enum maps so list/detail/run rows render
  localized values instead of raw `enabled` / `manual` / `success`.
- `recipes` — recipe labels (below).

The page maps raw enum values through small lookup helpers
(`statusLabel`, `scheduleTypeLabel`, `contextModeLabel`, `runTriggerLabel`,
`runStatusLabel`) that fall back to the raw value if unknown. E2E selectors
switched from exact English strings to case-insensitive regex so they survive
the i18n capitalization change (`cron · enabled` → `Cron · Enabled`).

### Recipe templates

New `frontend/src/core/scheduled-tasks/recipes.ts` exports `RECIPES: Recipe[]`
with `{ id, icon, titleKey, prompt, schedule }`. Four starters:

| id | icon | schedule | prompt gist |
|---|---|---|---|
| `trending` | 🔥 | daily 09:00 | web_search GitHub Trending, summarize top 10 |
| `news` | 📰 | daily 09:00 | web_search top tech news, 5-item digest |
| `issues` | 🏷️ | daily 09:00 | triage open issues in `{{repo}}` (user fills placeholder) |
| `weekly` | 📅 | weekly Mon 09:00 | weekly report |

`schedule.timezone` is intentionally `""` so the `ScheduledTaskScheduleInput`
falls back to the browser timezone when applied. Recipe titles/descriptions live
in i18n (`recipes.{id}.{title,desc}`); the file only stores the prompt + schedule.

### Wiring into the create form

- A `createNonce` counter state keys the create-form `ScheduledTaskScheduleInput`
  (`key={createNonce}`). Bumping the nonce forces the component to remount so the
  recipe's schedule is re-initialized into its `useState`, not just emitted.
- `applyRecipe(recipe)` sets title + prompt + createSchedule + contextMode +
  bumps the nonce.
- A chip row (`data-testid="schedule-recipes"`) renders above the form fields.

## Verification

- `pnpm check` 0 errors; `pnpm test` all green (403 unit tests).
- Real browser (chrome-devtools, zh-CN): 4 recipe chips render, clicking
  「每周周报」pre-fills title + prompt + preset (weekly) + preview
  `每周 周一 09:00 (Asia/Shanghai)`.
- Playwright `scheduled-tasks` suite re-verified with regex selectors.

## Non-goals (next session)

- Backend dispatch targets / `task_type` (RFC phase 2) — kept out because it
  changes schema/API/executor and would muddy this PR's review.
- Backend-stored / user-authored recipes — front-end built-ins are enough for
  the first cut (YAGNI).
