# Russian (ru-RU) localization — draft implementation

Tracking: https://github.com/bytedance/deer-flow/issues/8121

## Scope and current quality

This branch is **not a complete Russian translation**. It adds the `ru-RU` language
selection, initial human-reviewed Russian strings in high-visibility screens
(usage, common controls, welcome, chat/sidebar, composer, settings/appearance),
and a typed `en-US` fallback for every untranslated dictionary entry.

Do not label this release as "fully localized". Before an upstream PR or
production rollout, complete a key-by-key coverage review against
`frontend/src/core/i18n/locales/types.ts`, audit placeholders and formatting
functions, review Russian grammar and pluralization, and run browser E2E.

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

## Deployment safety

This is an isolated Git worktree and branch. No containers or production
services were restarted, rebuilt, or updated. Do not deploy automatically:
complete Russian translation review, maintainers' scope decision, CI,
and staged browser smoke tests first.
