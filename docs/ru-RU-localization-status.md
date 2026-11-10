# Russian (ru-RU) localization — draft implementation

Tracking: https://github.com/bytedance/deer-flow/issues/8121

## Scope and current quality

This branch provides an **expanded, but not yet complete, Russian translation**:
1,845 of 1,916 English UI keys are explicitly translated (96% by static AST
audit). All other keys inherit the original English fallback. The main UI,
chat, settings, memory, models, users, token displays, automation scheduler,
agents, integrations, projects, tools and extension screens are translated.

A few intentionally untranslated items remain, including provider and brand
names, technical parameters, identity fields, and some advanced server forms.
The translation needs human linguistic QA, full browser E2E and an upstream
maintainer review before it can be described as complete.

## Cross-layer implementation

- `frontend/src/core/i18n/locales/ru-RU.ts`: initial translation overlay.
- `frontend/src/core/i18n/locale.ts`: locale registry and normalization.
- `frontend/src/core/i18n/{index,client-translations,translations}.ts` and
  `locales/index.ts`: client/server dictionary registration.
- `frontend/src/components/workspace/settings/appearance-settings-page.tsx`:
  selectable Russian language.
- `frontend/src/core/settings/preferences-sync.ts` and
  `backend/app/gateway/routers/user_preferences.py`: avoid rejecting the
  browser's `ru-RU` preference.
- `contracts/ui_locales.v1.json`,
  `backend/packages/harness/deerflow/agents/language.py`, and
  `backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/updater.py`:
  make agent response language and DeerMem language recognize Russian.
- `frontend/src/core/utils/datetime.ts`: use Russian relative-date formatting.
- `frontend/src/core/voice-input/speech-recognition.ts`: allow Russian
  browser speech recognition, subject to browser support.

The IM channel reply/scheduled-notification catalogs currently contain
English and Simplified Chinese copy. The existing English fallback remains
for those server-generated messages; they have NOT been translated to Russian.

## Verification (isolated from the running deployment)

- `node --check` on changed TypeScript files: passed.
- `python3 -m py_compile` on the 3 edited Python files: passed.
- `git diff --check`: passed.
- Frontend Rstest locale suite in an ephemeral Docker container with
  read-only source mounts: **11/11 passed**.
- Backend pytest suites `test_ui_language_preference.py` and
  `test_user_preferences.py` in an ephemeral Docker container with
  read-only overlays: **39/39 passed**.
- TypeScript: initial run failed only because the existing Bookmarks extension
  test imports an absent build artifact. A separate `tsconfig` excluding
  exactly that unrelated test completed successfully (`tsc --noEmit`).
  The normal complete project-wide check therefore remains unresolved.

## Independent UI audit

- `frontend/scripts/audit-ru-localization.cjs`: compares leaf dictionary
  keys with explicit Russian overrides. 1,845/1,916 keys localized.
- `frontend/scripts/audit-ru-hardcoded-ui.cjs`: scans 269 frontend TSX
  components and routes for likely English JSX copy. First pass found 35
  candidates, including 8 workspace labels. The 8 workspace findings and
  most authentication/setup labels have been addressed.
  The final scan still finds 20 candidates, mostly on the separate marketing
  landing page (feature descriptions and demonstration animation), one
  generic sidebar accessibility sentence and an intentionally unchanged
  example email address. The audit is heuristic, not a browser E2E test.
- Regression tests cover Russian navigation, user/model settings, token usage,
  prompt suggestions, file selection and relative date localization.
- The 11 frontend i18n tests passed and TypeScript completed successfully
  when excluding exactly the unrelated Bookmarks extension test, whose built
  artifact is absent from the isolated build image.

## Deployment safety

This is an isolated Git worktree and branch, with the live Compose frontend
using its source bind mount. The first Russian build was already deployed
to the user's own Home PC at port 2026. Its Next.js volume
`deerflow_next_ru_20261111` is retained for rollback; the original
`deerflow_next_prod_v2` build is also preserved. User data, sessions,
databases and Redis volumes are outside these build volumes.

Use a **new** Next.js output volume for the revised translation and replace
only the frontend container after a successful isolated build and preview.
For upstream publication, request maintainer review and complete browser E2E.
